# Repository Guidelines

## Project Overview

This repository packages Orca's prebuilt headless server and CLI for Nix; it does not contain Orca application source. Changes normally belong in the packaging derivation, release pin, or Python maintenance scripts—not an application build system.

## Architecture & Data Flow

- `scripts/update.py` resolves an official stable `stablyai/orca` release, downloads its amd64 `.deb`, computes SHA-256 SRI, and atomically updates `source.json`.
- `flake.nix` injects pinned nixpkgs dependencies through `callPackage ./package.nix`. It exposes `packages.x86_64-linux.{default,orca-server}` and `overlays.default`.
- `package.nix` fetches the pinned archive, extracts a whitelist of shared server files and `linux-x64-glibc` native payloads, and fixes ELF linkage with `autoPatchelfHook`.
- Installation places the payload in `$out/lib/orca-native`. Node.js wrappers expose `orca-server` (`orcad-server.js`) and `orca-server-cli` (`out/cli/index.js`).
- CI builds the package, exercises that exact output with `scripts/smoke.py`, and publishes only verified trusted-main outputs to Cachix.

Preserve these boundaries: no Electron, other architectures, or bundled runtime-selection markers; those markers can trigger upstream Node downloads. Keep upstream JS/native payloads intact apart from linkage fixes. This repository supplies no NixOS service module.

## Key Directories

- `scripts/`: Python-stdlib release maintenance and installed-package integration testing.
- `.github/workflows/`: build/smoke/publish gating and release-update PR automation.
- Packaging code lives at the root. `result` and `result-*` are ignored build links, not editable source.

## Development Commands

Run from the repository root:

```sh
# Build, then validate the exact installed output.
nix build .#orca-server --out-link result
python3 scripts/smoke.py --package result

# Run the installed CLI or start a loopback-only server.
./result/bin/orca-server-cli --version
./result/bin/orca-server --bind 127.0.0.1 --port 4010

# Check upstream metadata without downloading the asset or writing source.json.
python3 scripts/update.py --check

# Update the pin to latest stable, or specify an exact version without a v prefix.
python3 scripts/update.py
python3 scripts/update.py --version 1.4.226
```

There is no configured lint/format command or development shell. Do not substitute `nix flake check` for the smoke test: the flake defines no `checks` output.

## Code Conventions & Common Patterns

- Match existing formatting: two-space Nix/JSON indentation; four-space Python indentation, `snake_case` functions, `UPPER_CASE` constants, and `PascalCase` classes. No formatter is configured.
- Keep dependency injection in the `package.nix` argument set and use `callPackage`; do not introduce ambient runtime dependencies. Wrappers provide Node, Git, Bash, coreutils, version variables, and CA defaults while preserving caller-supplied certificate settings.
- `source.json` is the release source of truth and must contain exactly `version` and `hash`. Use the updater rather than guessed hashes; it validates the actual downloaded archive and atomically replaces the file. Preserve the release asset basename in `fetchurl.name` to reuse fixed-output store objects.
- Python tools use only the standard library. The updater uses synchronous HTTP/streaming I/O and explicit validation errors; its exit codes are `0` for success/current pin, `1` for an update found by `--check`, and `2` for handled failures.
- The smoke harness uses a subprocess plus reader thread/queue, bounded waits, and `try/finally` cleanup—not asyncio. Preserve its disposable HOME/XDG state and isolation from host Orca sessions.

## Documentation Boundaries

- Keep `README.md` focused on installation, usage, deployment responsibilities, and essential maintenance steps; do not add a standalone CI configuration or release-boundary section.
- Place user-relevant cache publication guarantees in the binary-cache section and required update-PR validation steps in the upstream-update section. Link to the workflows rather than repeating their configuration.
- Keep maintainer-only CI details—path-filter lists, Secrets, Actions permissions, and branch-protection setup—in workflow comments or `AGENTS.md`, not the README. Avoid repeating guarantees already documented elsewhere in the README.

## Important Files

- `package.nix`: extraction whitelist, native target overlay, wrapper environment, platform/Node assertions, and installed licenses.
- `flake.nix` and `flake.lock`: package/overlay entry points and pinned nixpkgs revision; keep an intentional pin change consistent between them.
- `source.json`: upstream version and archive hash; avoid duplicating either in package logic.
- `scripts/smoke.py`: real server/CLI acceptance contract; `scripts/update.py`: release-validation and atomic-write contract.
- `.github/workflows/ci.yml`: build/smoke/publication rules; `.github/workflows/update.yml`: updater PR scope and manual-validation requirement.
- `LICENSE` and `LICENSE.upstream`: build inputs installed in the package, not documentation-only files; retain their build-CI coverage.

## Runtime/Tooling Preferences

- Use Nix with flakes enabled on `x86_64-linux`. Prebuilt addons require **Node.js 24**; both the derivation and smoke test enforce it. Node is supplied by Nix, not a host Node/Bun installation.
- Maintenance scripts require Python 3; smoke testing also requires Git on `PATH` and Linux `/proc` for private-daemon cleanup. No npm, Bun, pip dependencies, or application compilation step are defined.
- Retain the pinned nixpkgs input when preserving cache compatibility. Using a consumer's nixpkgs via `follows` or the overlay can change the derivation and lose cache reuse.

## Testing & QA

- The acceptance test is `python3 scripts/smoke.py --package result`; there is no separate unit-test framework or configured coverage threshold.
- It verifies the pinned CLI version, live Node major, encrypted pairing RPC, real Git worktree creation, PTY command execution, persisted pairing/repository/worktree state after restart, and clean shutdown. Preserve these behavioral assertions when changing packaging or the harness.
- Rebuild and smoke-test release or packaging changes together: the harness compares the output against the current `source.json`.
- Updater-only changes are excluded from build CI; validate their affected behavior explicitly. PRs created by `GITHUB_TOKEN` do not automatically trigger PR CI: manually run **Build and publish Orca** on `update/orca` before merging. Publishing remains restricted to trusted `main` runs.
