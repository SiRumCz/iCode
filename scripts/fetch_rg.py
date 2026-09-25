#!/usr/bin/env python3
# coding: utf-8
"""Download official ripgrep release binaries into openjiuwen_icode/vendor/rg.

Usage:
  python scripts/fetch_rg.py              # all supported platforms
  python scripts/fetch_rg.py --platform linux-x86_64
  python scripts/fetch_rg.py --force      # re-download even if present

Offline evals (Harbor / LoLBench) must ship these binaries in the tree or
run this script during the networked install phase.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RG_VERSION = "15.2.0"
BASE_URL = (
    f"https://github.com/BurntSushi/ripgrep/releases/download/{RG_VERSION}"
)

# platform_key → (asset archive name, binary name inside archive)
PLATFORMS: dict[str, tuple[str, str]] = {
    "linux-x86_64": (
        f"ripgrep-{RG_VERSION}-x86_64-unknown-linux-musl.tar.gz",
        "rg",
    ),
    "linux-aarch64": (
        f"ripgrep-{RG_VERSION}-aarch64-unknown-linux-musl.tar.gz",
        "rg",
    ),
    "darwin-x86_64": (
        f"ripgrep-{RG_VERSION}-x86_64-apple-darwin.tar.gz",
        "rg",
    ),
    "darwin-arm64": (
        f"ripgrep-{RG_VERSION}-aarch64-apple-darwin.tar.gz",
        "rg",
    ),
    "windows-x86_64": (
        f"ripgrep-{RG_VERSION}-x86_64-pc-windows-msvc.zip",
        "rg.exe",
    ),
}

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = REPO_ROOT / "openjiuwen_icode" / "vendor" / "rg"


def _download(url: str) -> bytes:
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310
        return resp.read()


def _extract_binary(archive: bytes, archive_name: str, binary_name: str) -> bytes:
    if archive_name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for info in zf.infolist():
                if Path(info.filename).name == binary_name and not info.is_dir():
                    return zf.read(info)
        raise FileNotFoundError(f"{binary_name} not found in {archive_name}")

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tf:
        for member in tf.getmembers():
            if Path(member.name).name == binary_name and member.isfile():
                extracted = tf.extractfile(member)
                if extracted is None:
                    break
                return extracted.read()
    raise FileNotFoundError(f"{binary_name} not found in {archive_name}")


def _parse_sha256_file(text: str) -> str:
    """Accept GNU ``hash  name`` and Windows CertUtil multi-line formats."""
    for token in re.findall(r"\b[a-fA-F0-9]{64}\b", text):
        return token.lower()
    raise ValueError(f"no sha256 digest found in checksum file: {text!r}")


def _verify_sha256(data: bytes, sha_url: str) -> None:
    expected = _parse_sha256_file(_download(sha_url).decode("utf-8"))
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(
            f"sha256 mismatch: expected {expected}, got {actual}"
        )


def fetch_platform(platform: str, *, force: bool = False) -> Path:
    if platform not in PLATFORMS:
        raise KeyError(f"unsupported platform: {platform}")
    archive_name, binary_name = PLATFORMS[platform]
    dest_dir = VENDOR_ROOT / platform
    dest = dest_dir / binary_name
    if dest.is_file() and not force:
        print(f"  skip {platform}: already present at {dest}")
        return dest

    archive = _download(f"{BASE_URL}/{archive_name}")
    _verify_sha256(archive, f"{BASE_URL}/{archive_name}.sha256")
    binary = _extract_binary(archive, archive_name, binary_name)

    dest_dir.mkdir(parents=True, exist_ok=True)
    # Write via temp then rename for atomicity.
    with tempfile.NamedTemporaryFile(dir=dest_dir, delete=False) as tmp:
        tmp.write(binary)
        tmp_path = Path(tmp.name)
    tmp_path.replace(dest)
    if binary_name != "rg.exe":
        dest.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )
    print(f"  wrote {dest} ({dest.stat().st_size} bytes)")
    return dest


def write_version_marker() -> None:
    VENDOR_ROOT.mkdir(parents=True, exist_ok=True)
    (VENDOR_ROOT / "VERSION").write_text(f"{RG_VERSION}\n", encoding="utf-8")
    readme = VENDOR_ROOT / "README.md"
    readme.write_text(
        (
            "# Vendored ripgrep\n\n"
            f"Official BurntSushi/ripgrep **{RG_VERSION}** binaries used by\n"
            "`icode` when the host has no `rg` on `PATH`.\n\n"
            "Refresh with:\n\n"
            "```bash\n"
            "python scripts/fetch_rg.py --force\n"
            "```\n\n"
            "License: ripgrep is dual-licensed MIT / Unlicense "
            "(see upstream release).\n"
        ),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        action="append",
        choices=sorted(PLATFORMS),
        help="Platform key to fetch (repeatable). Default: all.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when the binary already exists.",
    )
    args = parser.parse_args(argv)
    platforms = args.platform or list(PLATFORMS)
    write_version_marker()
    print(f"Vendor root: {VENDOR_ROOT}")
    for platform in platforms:
        print(f"[{platform}]")
        fetch_platform(platform, force=args.force)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
