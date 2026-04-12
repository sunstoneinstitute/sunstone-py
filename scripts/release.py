#!/usr/bin/env python3
"""Release automation for sunstone-py.

Reads a changelog entry from stdin, bumps the version in pyproject.toml,
prepends the entry to CHANGELOG.md, syncs uv.lock, commits, and tags.

Usage:
    echo "changelog text" | uv run python scripts/release.py --bump minor
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"


def current_version() -> str:
    text = PYPROJECT.read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        sys.exit("Could not find version in pyproject.toml")
    return m.group(1)


def bump_version(version: str, bump: str) -> str:
    parts = [int(p) for p in version.split(".")]
    if len(parts) != 3:
        sys.exit(f"Expected semver x.y.z, got {version}")
    major, minor, patch = parts
    if bump == "major":
        return f"{major + 1}.0.0"
    elif bump == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def update_pyproject(old: str, new: str) -> None:
    text = PYPROJECT.read_text()
    text = text.replace(f'version = "{old}"', f'version = "{new}"', 1)
    PYPROJECT.write_text(text)


def update_changelog(new_version: str, entry: str) -> None:
    today = date.today().isoformat()
    header = f"## [{new_version}] - {today}"

    if CHANGELOG.exists():
        text = CHANGELOG.read_text()
        # Insert after ## [Unreleased] if present, otherwise after the title
        unreleased_pattern = r"(## \[Unreleased\]\n)"
        if re.search(unreleased_pattern, text):
            text = re.sub(
                unreleased_pattern,
                f"\\1\n{header}\n\n{entry.strip()}\n\n",
                text,
                count=1,
            )
        else:
            # Insert after the first heading
            text = re.sub(
                r"(# Changelog\n)",
                f"\\1\n{header}\n\n{entry.strip()}\n\n",
                text,
                count=1,
            )
    else:
        text = (
            "# Changelog\n\n"
            "All notable changes to this project will be documented in this file.\n\n"
            "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),\n"
            "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n\n"
            "## [Unreleased]\n\n"
            f"{header}\n\n{entry.strip()}\n"
        )
    CHANGELOG.write_text(text)


def sync_uv_lock() -> None:
    result = subprocess.run(["uv", "sync"], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: uv sync failed\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def git_commit_and_tag(version: str) -> None:
    tag = f"v{version}"
    subprocess.run(
        ["git", "add", "pyproject.toml", "CHANGELOG.md", "uv.lock"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"release: {tag}"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
        cwd=ROOT,
        check=True,
    )
    print(f"Created commit and tag {tag}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Release sunstone-py")
    parser.add_argument(
        "--bump",
        choices=["major", "minor", "patch"],
        required=True,
        help="Version bump type",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    args = parser.parse_args()

    changelog_entry = sys.stdin.read().strip()
    if not changelog_entry:
        sys.exit("No changelog entry provided on stdin")

    old = current_version()
    new = bump_version(old, args.bump)

    print(f"Version: {old} -> {new}")
    print(f"Changelog:\n{changelog_entry}\n")

    if args.dry_run:
        print("(dry run — no changes made)")
        return

    update_pyproject(old, new)
    sync_uv_lock()
    update_changelog(new, changelog_entry)
    git_commit_and_tag(new)


if __name__ == "__main__":
    main()
