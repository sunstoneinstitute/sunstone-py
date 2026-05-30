#!/usr/bin/env bash
# Ensure tool versions in uv.lock match .pre-commit-config.yaml

set -euo pipefail

status=0

check_version() {
    local name=$1
    local repo_pattern=$2

    local lock_version
    lock_version=$(tomlq -r ".package[] | select(.name == \"$name\") | .version" uv.lock)

    local precommit_version
    precommit_version=$(yq -r ".repos[] | select(.repo | test(\"${repo_pattern}\")) | .rev" .pre-commit-config.yaml | sed 's/^v//')

    if [ -z "$lock_version" ]; then
        echo "ERROR: Could not find $name version in uv.lock"
        status=1
        return
    fi

    if [ -z "$precommit_version" ]; then
        echo "ERROR: Could not find $name version in .pre-commit-config.yaml"
        status=1
        return
    fi

    if [ "$lock_version" != "$precommit_version" ]; then
        echo "ERROR: $name version mismatch!"
        echo "  uv.lock:                 $lock_version"
        echo "  .pre-commit-config.yaml: $precommit_version"
        echo "  Update .pre-commit-config.yaml rev to v$lock_version"
        echo ""
        status=1
    fi
}

check_version "ruff" "ruff-pre-commit"
check_version "mypy" "mirrors-mypy"

exit $status
