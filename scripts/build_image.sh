#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-aiops-engine:1.0.0}"
BINARY="aiops-healthcheck"
SOURCE="scripts/healthcheck.c"

cleanup() {
    rm -f "$BINARY"
}
trap cleanup EXIT

command -v gcc >/dev/null 2>&1 || {
    echo "ERROR: gcc is required to build the native healthcheck." >&2
    exit 1
}

echo "===== COMPILE HEALTHCHECK ====="
gcc -O2 -Wall -Wextra -o "$BINARY" "$SOURCE"

if command -v strip >/dev/null 2>&1; then
    strip "$BINARY"
fi

file "$BINARY"

echo
echo "===== BUILD IMAGE: $IMAGE ====="
export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-0}"
docker build -t "$IMAGE" .

echo
echo "BUILD PASS: $IMAGE"
