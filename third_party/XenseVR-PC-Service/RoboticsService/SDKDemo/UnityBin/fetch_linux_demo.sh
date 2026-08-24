#!/bin/bash
#
# Fetch the Linux Unity demo (RobotLinuxDemo).
#
# The demo is 107 MiB unpacked and changes only when someone rebuilds it in
# Unity, so it is published as a release asset rather than tracked in git —
# carrying it in every clone cost more than half the repository's download.
# This script restores it on demand, so the packaging step below works from a
# fresh clone exactly as it did when the demo was checked in.
#
# Usage:
#   fetch_linux_demo.sh              # just populate ./RobotLinuxDemo
#   fetch_linux_demo.sh <destdir>    # populate, then copy the tree to <destdir>
#
# Overrides: ROBOT_LINUX_DEMO_VER / _URL / _SHA256 for a patched or offline
# build (point _URL at a file:// path to skip the network entirely).

set -euo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEMO_DIR="$DIR/RobotLinuxDemo"

ASSET_VER="${ROBOT_LINUX_DEMO_VER:-0.2.0}"
ASSET="RobotLinuxDemo_${ASSET_VER}_linux_x86_64.tar.gz"
ASSET_URL="${ROBOT_LINUX_DEMO_URL:-https://github.com/Vertax42/XenseVR-PC-Service/releases/download/v${ASSET_VER}/${ASSET}}"
ASSET_SHA256="${ROBOT_LINUX_DEMO_SHA256:-a8eaa5ed4d051ea84320c35df32d19f3acfe9f4e64acaf76b95b4ca6abd2a098}"

# Test -f, not -x: the demo binary is mode 644 in the archive, which is why the
# packaging step chmod +x's it afterwards. Testing -x would re-download forever.
if [ ! -f "$DEMO_DIR/RobotLinuxDemo.x86_64" ]; then
    echo "Linux Unity demo not present, fetching $ASSET ..."
    TMP="${TMPDIR:-/tmp}/$ASSET"

    if [ ! -f "$TMP" ]; then
        # 38 MiB over whatever link the build host has. Retry and resume rather
        # than failing the whole build on one dropped connection — plain
        # `curl -fL` loses the entire transfer, which is how this was first
        # written and how it first broke.
        RETRY=(--retry 5 --retry-delay 2)
        if curl --help all 2>/dev/null | grep -q -- '--retry-all-errors'; then
            # curl >= 7.71. Without it, a mid-transfer drop (error 18) is not
            # one of the errors --retry considers worth retrying.
            RETRY+=(--retry-all-errors)
        fi

        if ! curl -fL --progress-bar "${RETRY[@]}" -C - -o "$TMP.part" "$ASSET_URL"; then
            echo "ERROR: could not download $ASSET_URL" >&2
            echo "  The partial file is kept at $TMP.part — re-run to resume it." >&2
            echo "  Or grab $ASSET from" >&2
            echo "  https://github.com/Vertax42/XenseVR-PC-Service/releases" >&2
            echo "  and extract it into $DIR/, or set ROBOT_LINUX_DEMO_URL." >&2
            exit 1
        fi
        mv "$TMP.part" "$TMP"
    fi

    # Verify before extracting — a truncated or substituted archive would
    # otherwise be packaged into the .deb and shipped.
    if ! echo "$ASSET_SHA256  $TMP" | sha256sum -c - >/dev/null 2>&1; then
        echo "ERROR: checksum mismatch for $TMP" >&2
        echo "  expected $ASSET_SHA256" >&2
        echo "  got      $(sha256sum "$TMP" | cut -d' ' -f1)" >&2
        echo "  Removing it; re-run to download again." >&2
        rm -f "$TMP"
        exit 1
    fi

    rm -rf "$DEMO_DIR"
    tar -xzf "$TMP" -C "$DIR"
    echo "Extracted to $DEMO_DIR"
fi

if [ $# -ge 1 ]; then
    mkdir -p "$1"
    cp -a "$DEMO_DIR/." "$1/"
fi
