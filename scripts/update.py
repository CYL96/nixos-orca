#!/usr/bin/env python3
"""Update source.json from an official stable Orca release using only stdlib."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY = "stablyai/orca"
API = f"https://api.github.com/repos/{REPOSITORY}/releases"
SOURCE = Path(__file__).resolve().parents[1] / "source.json"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def release_metadata(version):
    endpoint = f"{API}/tags/v{version}" if version else f"{API}/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nixos-orca-updater",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        if not re.fullmatch(r"[!-~]+", token):
            raise ValueError("GITHUB_TOKEN contains invalid header characters")
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(endpoint, headers=headers), timeout=60) as response:
        release = json.load(response)
    if not isinstance(release, dict):
        raise ValueError("GitHub did not return a release object")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("only published, non-prerelease releases are supported")
    tag = release.get("tag_name", "")
    if not isinstance(tag, str) or not tag.startswith("v") or not VERSION.fullmatch(tag[1:]):
        raise ValueError("release tag is not a supported stable version")
    actual_version = tag[1:]
    if version and actual_version != version:
        raise ValueError("GitHub returned a different release than requested")
    filename = f"orca-ide_{actual_version}_amd64.deb"
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("GitHub release does not contain an asset list")
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == filename]
    if len(matches) != 1:
        raise ValueError(f"release must contain exactly one {filename} asset")
    asset = matches[0]
    expected_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}"
    if asset.get("browser_download_url") != expected_url:
        raise ValueError("release asset URL is not the expected official download URL")
    size = asset.get("size")
    if type(size) is not int or size <= 0:
        raise ValueError("release asset has no valid size")
    return actual_version, expected_url, size


def file_hash(url, expected_size):
    # Download the actual public asset, not an API digest or a Nix fake hash.
    # Do not send GITHUB_TOKEN to the asset host or its CDN redirects.
    request = Request(url, headers={"User-Agent": "nixos-orca-updater", "Accept-Encoding": "identity"})
    digest = hashlib.sha256()
    size = 0
    magic = b""
    with urlopen(request, timeout=60) as response:
        while chunk := response.read(1024 * 1024):
            if len(magic) < 8:
                magic += chunk[: 8 - len(magic)]
            size += len(chunk)
            digest.update(chunk)
    if size != expected_size:
        raise ValueError(f"asset size mismatch: expected {expected_size} bytes, received {size}")
    if magic != b"!<arch>\n":
        raise ValueError("downloaded asset is not a Debian archive")
    return "sha256-" + base64.b64encode(digest.digest()).decode("ascii")


def read_source():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(source, dict) or set(source) != {"version", "hash"}:
        raise ValueError("source.json must contain exactly version and hash")
    if not isinstance(source["version"], str) or not VERSION.fullmatch(source["version"]):
        raise ValueError("source.json has an invalid version")
    sri = source["hash"]
    if not isinstance(sri, str) or not sri.startswith("sha256-"):
        raise ValueError("source.json has an invalid SHA-256 SRI hash")
    if len(base64.b64decode(sri[7:], validate=True)) != 32:
        raise ValueError("source.json has an invalid SHA-256 SRI hash")
    return source


def write_source(source):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=SOURCE.parent, prefix=".source-", delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, SOURCE.stat().st_mode & 0o777)
            json.dump(source, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, SOURCE)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="exact stable version, for example 1.4.224 (default: GitHub latest stable)")
    parser.add_argument("--check", action="store_true", help="only check release metadata; exit 1 if version differs, without downloading or writing")
    args = parser.parse_args()
    if args.version is not None and not VERSION.fullmatch(args.version):
        parser.error("--version must have the form 1.4.224, without a v prefix")
    current = read_source()
    version, url, size = release_metadata(args.version)
    if version == current["version"]:
        print(f"Orca {version} is already pinned; no asset download or file changes.")
        return 0
    if args.check:
        print(f"Orca update available: {current['version']} -> {version}; source.json unchanged.")
        return 1
    updated = {"version": version, "hash": file_hash(url, size)}
    if updated != current:
        write_source(updated)
        print(f"Updated Orca {current['version']} -> {version} in source.json.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HTTPError as error:
        print(f"error: GitHub request failed with HTTP {error.code}; no update written.", file=sys.stderr)
        sys.exit(2)
    except (URLError, OSError, ValueError, TimeoutError) as error:
        print(f"error: {error}; no update written.", file=sys.stderr)
        sys.exit(2)
