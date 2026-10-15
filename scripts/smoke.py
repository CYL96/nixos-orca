#!/usr/bin/env python3
"""Exercise the installed native server, not Electron, in disposable user data."""

import argparse
import base64
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit


class SmokeError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise SmokeError(message)




class Server:
    def __init__(self, executable, env, port):
        self.executable = executable
        self.env = env
        self.port = port
        self.process = None
        self.events = queue.Queue()

    def start(self):
        self.events = queue.Queue()
        self.process = subprocess.Popen(
            [str(self.executable), "--bind", "127.0.0.1", "--port", str(self.port),
             "--json", "--pairing-address", "127.0.0.1"],
            env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, start_new_session=True,
        )

        def consume():
            for line in self.process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.events.put(event)
            self.events.put(None)

        self.thread = threading.Thread(target=consume, daemon=True)
        self.thread.start()

    def stop(self, strict=False):
        if self.process is None:
            return
        process = self.process
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        try:
            code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            raise SmokeError("server did not shut down within 30 seconds")
        finally:
            self.thread.join(timeout=2)
            process.stdout.close()
            self.process = None
        if strict:
            require(code == 0, "server shutdown did not exit successfully")


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def command(arguments, env, cwd=None, timeout=30):
    result = subprocess.run(arguments, env=env, cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    # Child output may contain pairing credentials: never echo it, even on failure.
    require(result.returncode == 0, "smoke subprocess exited unsuccessfully")
    return result.stdout


def ready(server):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            event = server.events.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty:
            break
        require(event is not None, "server exited before announcing readiness")
        if event.get("type") == "orca_server_ready":
            require(event.get("pairing", {}).get("available") is True,
                    "server did not offer runtime pairing")
            pairing = event["pairing"]["url"]
            encoded = parse_qs(urlsplit(pairing).query).get("code", [])
            require(len(encoded) == 1, "server emitted an invalid pairing URL")
            payload = json.loads(base64.urlsafe_b64decode(encoded[0] + "=" * (-len(encoded[0]) % 4)))
            require(urlsplit(payload["endpoint"]).hostname == "127.0.0.1",
                    "server advertised pairing outside loopback")
            return pairing, event
    raise SmokeError("server did not announce readiness within 90 seconds")


def cli(executable, env, pairing, *arguments):
    output = command([str(executable), "--pairing-code", pairing, "--json",
                      *map(str, arguments)], env, timeout=40)
    response = json.loads(output)
    require(response.get("ok") is True, "native CLI RPC did not succeed")
    return response["result"]


def assert_status(result, version):
    require(result["runtime"]["reachable"] is True, "paired runtime is unreachable")
    require(result["runtime"]["state"] == "ready", "paired runtime graph is not ready")
    require(result["runtime"].get("appVersion") == version,
            "paired runtime reported a different application version")


def stop_private_daemons(root):
    # Only PID records under this smoke's private data tree are eligible. Verify
    # the exact daemon entry in /proc as protection against stale/reused PIDs.
    for record in root.rglob("daemon-v*.pid"):
        try:
            value = json.loads(record.read_text())
            pid = value if isinstance(value, int) else value["pid"]
            arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            if not any(argument.endswith(b"/daemon-entry.js") for argument in arguments):
                continue
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 8
            while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            if Path(f"/proc/{pid}").exists():
                current = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                if current == arguments:
                    os.kill(pid, signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError):
            pass


def smoke(package):
    expected = json.loads((Path(__file__).resolve().parent.parent / "source.json").read_text())["version"]
    executable = package / "bin/orca-server"
    client = package / "bin/orca-server-cli"
    require(executable.is_file() and client.is_file(), "package lacks the native server commands")
    with tempfile.TemporaryDirectory(prefix="orca-smoke-") as temporary:
        root = Path(temporary)
        home, state, runtime = root / "home", root / "state", root / "runtime"
        for directory in (home, state, runtime, root / "tmp"):
            directory.mkdir(mode=0o700)
        # Do not inherit host Orca sessions, credentials, display, shell startup,
        # Git overrides, or user-manager sockets from the caller.
        env = {key: os.environ[key] for key in ("PATH", "SSL_CERT_FILE", "NIX_SSL_CERT_FILE")
               if key in os.environ}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                   XDG_CACHE_HOME=str(home / ".cache"), XDG_DATA_HOME=str(home / ".local/share"),
                   XDG_STATE_HOME=str(home / ".local/state"), XDG_RUNTIME_DIR=str(runtime),
                   TMPDIR=str(root / "tmp"), ORCA_USER_DATA=str(state), ORCA_USER_DATA_PATH=str(state),
                   ORCA_TELEMETRY_DISABLED="1", DO_NOT_TRACK="1", CI="1", TERM="xterm-256color",
                   GIT_CONFIG_NOSYSTEM="1", LANG="C.UTF-8")
        require(command([str(client), "--version"], env).strip() == expected,
                "native CLI version does not match source.json")
        repo = root / "repository"
        repo.mkdir()
        command(["git", "init", "--initial-branch=main", str(repo)], env)
        command(["git", "-C", str(repo), "config", "user.name", "Orca smoke"], env)
        command(["git", "-C", str(repo), "config", "user.email", "orca-smoke@example.invalid"], env)
        (repo / "fixture.txt").write_text("native Orca smoke fixture\n")
        command(["git", "-C", str(repo), "add", "fixture.txt"], env)
        command(["git", "-C", str(repo), "commit", "-m", "smoke fixture"], env)
        server = Server(executable, env, free_port())
        terminal = pairing = None
        try:
            server.start()
            pairing, announcement = ready(server)
            assert_status(cli(client, env, pairing, "status"), expected)
            require(announcement["health"]["nodeVersion"].split(".")[0] == "24",
                    "server is not running Node.js 24")
            registered = cli(client, env, pairing, "repo", "add", "--path", repo)["repo"]
            repo_id = str(registered["id"])
            require(Path(registered["path"]) == repo, "registered repository path differs")
            worktree = cli(client, env, pairing, "worktree", "create", "--repo", f"id:{repo_id}",
                           "--name", "native-smoke", "--setup", "skip", "--no-parent")["worktree"]
            worktree_id = str(worktree["id"])
            worktree_path = Path(worktree["path"])
            require(worktree_path != repo and (worktree_path / "fixture.txt").is_file(),
                    "Orca did not create a real checkout worktree")
            registered_worktrees = command(["git", "-C", str(repo), "worktree", "list", "--porcelain"], env)
            require(f"worktree {worktree_path}\n" in registered_worktrees,
                    "created worktree is absent from Git's worktree registry")
            terminal = cli(client, env, pairing, "terminal", "create", "--worktree", f"id:{worktree_id}",
                           "--title", "native-smoke")["terminal"]["handle"]
            marker = "ORCA_PTY_" + secrets.token_hex(12)
            # The complete marker is not present in echoed input. Seeing it in
            # terminal output therefore proves the shell executed the command.
            split = len(marker) // 2
            shell_command = f"test -t 0 && test -t 1 && printf '%s%s\\n' '{marker[:split]}' '{marker[split:]}'"
            sent = cli(client, env, pairing, "terminal", "send", "--terminal", terminal,
                       "--text", shell_command, "--enter")
            require(sent["send"]["accepted"] is True, "PTY command input was refused")
            deadline = time.monotonic() + 30
            while True:
                output = cli(client, env, pairing, "terminal", "read", "--terminal", terminal,
                             "--limit", "200")["terminal"]["tail"]
                if marker in "\n".join(output):
                    break
                require(time.monotonic() < deadline, "PTY did not execute the terminal marker command")
                time.sleep(0.25)
            cli(client, env, pairing, "terminal", "close", "--terminal", terminal)
            terminal = None
            server.stop(strict=True)
            server.start()
            ready(server)
            # Deliberately keep the OLD pairing URL: generating a fresh offer
            # must not conceal broken persisted pairing/reconnection semantics.
            assert_status(cli(client, env, pairing, "status"), expected)
            repositories = cli(client, env, pairing, "repo", "list")["repos"]
            require(any(str(item["id"]) == repo_id and Path(item["path"]) == repo
                        for item in repositories), "repository registration did not survive restart")
            worktrees = cli(client, env, pairing, "worktree", "list", "--repo", f"id:{repo_id}")["worktrees"]
            require(any(str(item["id"]) == worktree_id for item in worktrees),
                    "worktree registration did not survive restart")
            server.stop(strict=True)
        finally:
            try:
                if terminal and pairing and server.process and server.process.poll() is None:
                    cli(client, env, pairing, "terminal", "close", "--terminal", terminal)
            finally:
                try:
                    server.stop()
                finally:
                    stop_private_daemons(root)
    print(f"Orca {expected}: version, encrypted pairing RPC, repository, worktree, PTY and restart smoke passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        smoke(arguments.package.resolve())
    except (SmokeError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        # Do not stringify arbitrary exceptions: argv, RPC payloads and server
        # stdout may embed the private pairing URL/token.
        detail = str(error) if isinstance(error, SmokeError) else type(error).__name__
        print(f"Orca smoke failed: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
