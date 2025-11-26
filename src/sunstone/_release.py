#!/usr/bin/env python3
"""Release script for sunstone-py.

Handles version bumping, CHANGELOG updates, git tagging, and pushing.
"""

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


def get_lib_dir() -> Path:
    """Get the lib directory (where pyproject.toml lives)."""
    # Navigate from src/sunstone/_release.py up to lib/
    return Path(__file__).parent.parent.parent


def run_git(*args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    result = subprocess.run(
        ["git", *args],
        capture_output=capture,
        text=True,
        cwd=get_lib_dir(),
    )
    return result


def check_git_clean() -> None:
    """Fail if the git workspace is not clean."""
    result = run_git("status", "--porcelain")
    if result.returncode != 0:
        print("Error: Failed to check git status", file=sys.stderr)
        sys.exit(1)
    if result.stdout.strip():
        print("Error: Git workspace is not clean. Commit or stash changes first.", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        sys.exit(1)


def check_on_main_branch() -> None:
    """Fail if HEAD is not on the main branch."""
    result = run_git("rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        print("Error: Failed to get current branch", file=sys.stderr)
        sys.exit(1)
    branch = result.stdout.strip()
    if branch != "main":
        print(f"Error: Not on main branch (currently on '{branch}')", file=sys.stderr)
        sys.exit(1)


def check_up_to_date_with_origin() -> None:
    """Fail if main is not up to date with origin/main."""
    # Fetch latest from origin
    result = run_git("fetch", "origin", "main")
    if result.returncode != 0:
        print("Error: Failed to fetch from origin", file=sys.stderr)
        sys.exit(1)

    # Get local and remote commit hashes
    local = run_git("rev-parse", "HEAD")
    remote = run_git("rev-parse", "origin/main")

    if local.returncode != 0 or remote.returncode != 0:
        print("Error: Failed to get commit hashes", file=sys.stderr)
        sys.exit(1)

    local_hash = local.stdout.strip()
    remote_hash = remote.stdout.strip()

    if local_hash != remote_hash:
        # Check if local is behind
        merge_base = run_git("merge-base", "HEAD", "origin/main")
        if merge_base.returncode != 0:
            print("Error: Failed to find merge base", file=sys.stderr)
            sys.exit(1)

        base_hash = merge_base.stdout.strip()
        if base_hash == local_hash:
            print("Error: Local main is behind origin/main. Pull first.", file=sys.stderr)
        elif base_hash == remote_hash:
            print("Error: Local main is ahead of origin/main. Push first.", file=sys.stderr)
        else:
            print("Error: Local main has diverged from origin/main.", file=sys.stderr)
        sys.exit(1)


def get_current_version() -> str:
    """Get the current version from pyproject.toml."""
    pyproject_path = get_lib_dir() / "pyproject.toml"
    content = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        print("Error: Could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def bump_version(version: str, bump: str) -> str:
    """Bump the version according to semver."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    if not match:
        print(f"Error: Invalid version format: {version}", file=sys.stderr)
        sys.exit(1)

    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))

    if bump == "major":
        return f"{major + 1}.0.0"
    elif bump == "minor":
        return f"{major}.{minor + 1}.0"
    else:  # patch
        return f"{major}.{minor}.{patch + 1}"


def update_pyproject_version(new_version: str) -> None:
    """Update the version in pyproject.toml."""
    pyproject_path = get_lib_dir() / "pyproject.toml"
    content = pyproject_path.read_text()
    new_content = re.sub(
        r'^(version\s*=\s*)"[^"]+"',
        f'\\1"{new_version}"',
        content,
        flags=re.MULTILINE,
    )
    pyproject_path.write_text(new_content)


def update_changelog(new_version: str) -> None:
    """Update CHANGELOG.md to move Unreleased to the new version."""
    changelog_path = get_lib_dir() / "CHANGELOG.md"
    content = changelog_path.read_text()

    today = date.today().isoformat()

    # Replace [Unreleased] section header with new version
    # Keep [Unreleased] but add new version section after it
    new_unreleased = "## [Unreleased]\n"
    version_header = f"## [{new_version}] - {today}\n"

    # Find the Unreleased section and the content until next version
    pattern = r"(## \[Unreleased\]\n)(.*?)(## \[\d)"
    match = re.search(pattern, content, re.DOTALL)

    if match:
        unreleased_content = match.group(2)
        if unreleased_content.strip():
            # There's content in Unreleased, move it to new version
            new_content = content.replace(
                match.group(0),
                f"{new_unreleased}\n{version_header}{unreleased_content}{match.group(3)}",
            )
        else:
            # No content in Unreleased, just add version header
            new_content = content.replace(
                match.group(0),
                f"{new_unreleased}\n{version_header}\n{match.group(3)}",
            )
    else:
        # Unreleased is at the end or there's no previous version
        pattern = r"(## \[Unreleased\]\n)(.*?)$"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            unreleased_content = match.group(2)
            new_content = content.replace(
                match.group(0),
                f"{new_unreleased}\n{version_header}{unreleased_content}",
            )
        else:
            print("Error: Could not find [Unreleased] section in CHANGELOG.md", file=sys.stderr)
            sys.exit(1)

    changelog_path.write_text(new_content)


def git_commit_and_tag(new_version: str) -> None:
    """Commit changes and create version tag."""
    lib_dir = get_lib_dir()

    # Stage changed files
    result = run_git("add", str(lib_dir / "pyproject.toml"), str(lib_dir / "CHANGELOG.md"))
    if result.returncode != 0:
        print("Error: Failed to stage files", file=sys.stderr)
        sys.exit(1)

    # Commit
    commit_msg = f"Release v{new_version}"
    result = run_git("commit", "-m", commit_msg)
    if result.returncode != 0:
        print("Error: Failed to commit", file=sys.stderr)
        sys.exit(1)

    # Tag
    tag = f"v{new_version}"
    result = run_git("tag", "-a", tag, "-m", f"Release {tag}")
    if result.returncode != 0:
        print("Error: Failed to create tag", file=sys.stderr)
        sys.exit(1)

    print(f"Created commit and tag {tag}")


def git_push() -> None:
    """Push commits and tags to origin."""
    result = run_git("push", "origin", "main", "--follow-tags", capture=False)
    if result.returncode != 0:
        print("Error: Failed to push to origin", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Release a new version of sunstone-py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run release              # Bump patch version (0.1.0 -> 0.1.1)
  uv run release --bump=patch # Bump patch version (0.1.0 -> 0.1.1)
  uv run release --bump=minor # Bump minor version (0.1.0 -> 0.2.0)
  uv run release --bump-minor # Bump minor version (0.1.0 -> 0.2.0)
  uv run release --bump=major # Bump major version (0.1.0 -> 1.0.0)
  uv run release --bump-major # Bump major version (0.1.0 -> 1.0.0)
""",
    )
    parser.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default=None,
        help="Version component to bump (default: patch)",
    )
    parser.add_argument(
        "--bump-minor",
        action="store_true",
        help="Bump minor version (shorthand for --bump=minor)",
    )
    parser.add_argument(
        "--bump-major",
        action="store_true",
        help="Bump major version (shorthand for --bump=major)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    # Resolve bump level from flags
    if args.bump_major:
        bump = "major"
    elif args.bump_minor:
        bump = "minor"
    elif args.bump:
        bump = args.bump
    else:
        bump = "patch"

    print("Checking git status...")
    check_git_clean()
    check_on_main_branch()
    check_up_to_date_with_origin()
    print("Git checks passed.")

    current_version = get_current_version()
    new_version = bump_version(current_version, bump)

    print(f"Version: {current_version} -> {new_version}")

    if args.dry_run:
        print("Dry run - no changes made.")
        return

    print("Updating pyproject.toml...")
    update_pyproject_version(new_version)

    print("Updating CHANGELOG.md...")
    update_changelog(new_version)

    print("Committing and tagging...")
    git_commit_and_tag(new_version)

    print("Pushing to origin...")
    git_push()

    print(f"\nSuccessfully released v{new_version}!")


if __name__ == "__main__":
    main()
