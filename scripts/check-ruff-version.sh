#!/usr/bin/env bash
# Ensure ruff version in uv.lock matches .pre-commit-config.yaml

set -euo pipefail

lock_version=$(tomlq -r '.package[] | select(.name == "ruff") | .version' uv.lock)
precommit_version=$(yq '.repos[] | select(.repo == "*ruff*") | .rev' .pre-commit-config.yaml | sed 's/^v//')

if [ -z "$lock_version" ]; then
    echo "ERROR: Could not find ruff version in uv.lock"
    exit 1
fi

if [ -z "$precommit_version" ]; then
    echo "ERROR: Could not find ruff version in .pre-commit-config.yaml"
    exit 1
fi

if [ "$lock_version" != "$precommit_version" ]; then
    echo "ERROR: ruff version mismatch!"
    echo "  uv.lock:                 $lock_version"
    echo "  .pre-commit-config.yaml: $precommit_version"
    echo ""
    echo "Update .pre-commit-config.yaml rev to v$lock_version"
    exit 1
fi
