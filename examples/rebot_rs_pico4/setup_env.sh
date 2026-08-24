#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEROBOT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SDK_ROOT="${REBOT_SDK_ROOT:-$LEROBOT_ROOT/third_party/reBotArm_control_py}"
XENSE_VENDOR_ROOT="${XENSE_VENDOR_ROOT:-$LEROBOT_ROOT/third_party/XenseVR-PC-Service}"
XENSE_VENDOR_SDK_ROOT="${XENSE_VENDOR_SDK_ROOT:-$XENSE_VENDOR_ROOT/RoboticsService/PXREARobotSDK}"
XENSE_VENDOR_SDK_EXPORT_ROOT="${XENSE_VENDOR_SDK_EXPORT_ROOT:-$XENSE_VENDOR_ROOT/RoboticsService/SDK}"
XENSE_PYBIND_ROOT="${XENSE_PYBIND_ROOT:-$LEROBOT_ROOT/src/lerobot/teleoperators/pico4/xensevr-pc-service-pybind}"
PYTHON_BIN="${PYTHON_BIN:-python}"

usage() {
    cat <<'USAGE'
Usage: ./setup_env.sh --install

Run this script inside your existing lerobot-xense environment. It installs the
current LeRobot checkout and the reBot RS third-party SDKs into the active
Python environment.

Environment variables:
  PYTHON_BIN        Python executable from the active env (default: python)
  REBOT_SDK_ROOT    Path to reBotArm_control_py (default: <lerobot-root>/third_party/reBotArm_control_py)
  XENSE_VENDOR_ROOT  Path to XenseVR-PC-Service (default: <lerobot-root>/third_party/XenseVR-PC-Service)
  XENSE_VENDOR_SDK_ROOT
                    Path to PXREARobotSDK source tree
                    (default: <XENSE_VENDOR_ROOT>/RoboticsService/PXREARobotSDK)
  XENSE_VENDOR_SDK_EXPORT_ROOT
                    Path to exported SDK payload
                    (default: <XENSE_VENDOR_ROOT>/RoboticsService/SDK)
  XENSE_PYBIND_ROOT Path to xensevr_pc_service_sdk source tree
                    (default: <lerobot-root>/src/lerobot/teleoperators/pico4/xensevr-pc-service-pybind)

Examples:
  source /path/to/lerobot-xense/bin/activate
  bash ./setup_env.sh --install
  REBOT_SDK_ROOT=../../third_party/reBotArm_control_py bash ./setup_env.sh --install
USAGE
}

require_python() {
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        echo "ERROR: $PYTHON_BIN is required. Activate your lerobot-xense env first."
        exit 1
    fi
}

require_active_env() {
    "$PYTHON_BIN" - <<'PY'
import os
import sys

if not (os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_PREFIX")):
    raise SystemExit(
        "ERROR: no active virtual environment detected. "
        "Activate your lerobot-xense environment before running this script."
    )

if sys.version_info < (3, 12):
    raise SystemExit(
        f"ERROR: Python {sys.version.split()[0]} is active. "
        "lerobot requires Python 3.12; activate your lerobot-xense environment."
    )

print(f"[env] active interpreter: {sys.executable}")
PY
}

install_lerobot() {
    echo "[lerobot] Installing editable LeRobot from $LEROBOT_ROOT"
    (
        cd "$LEROBOT_ROOT"
        "$PYTHON_BIN" -m pip install -e ".[core_scripts]" --no-build-isolation
    )
}

install_rebot_sdk() {
    if [[ ! -d "$SDK_ROOT" ]]; then
        echo "ERROR: reBotArm_control_py not found at: $SDK_ROOT"
        echo "Set REBOT_SDK_ROOT to <lerobot-root>/third_party/reBotArm_control_py and re-run."
        exit 1
    fi

    echo "[rebot] Installing editable reBotArm_control_py from $SDK_ROOT"
    "$PYTHON_BIN" -m pip install -e "$SDK_ROOT" --ignore-requires-python --no-build-isolation
}

install_xense_sdk() {
    if [[ ! -d "$XENSE_PYBIND_ROOT" ]]; then
        echo "ERROR: xensevr_pc_service_sdk is missing and XENSE_PYBIND_ROOT does not exist:"
        echo "  $XENSE_PYBIND_ROOT"
        exit 1
    fi

    if [[ ! -d "$XENSE_VENDOR_ROOT" ]]; then
        echo "ERROR: XenseVR-PC-Service not found at:"
        echo "  $XENSE_VENDOR_ROOT"
        exit 1
    fi

    if [[ ! -d "$XENSE_VENDOR_SDK_ROOT" ]]; then
        echo "ERROR: PXREARobotSDK source tree not found at:"
        echo "  $XENSE_VENDOR_SDK_ROOT"
        exit 1
    fi

    if [[ ! -f "$XENSE_VENDOR_SDK_ROOT/build.sh" ]]; then
        echo "ERROR: PXREARobotSDK build.sh is missing:"
        echo "  $XENSE_VENDOR_SDK_ROOT/build.sh"
        exit 1
    fi

    if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("pybind11") else 1)
PY
    then
        "$PYTHON_BIN" -m pip install pybind11
    fi

    echo "[xense] Building vendor PXREARobotSDK from $XENSE_VENDOR_SDK_ROOT"
    bash "$XENSE_VENDOR_SDK_ROOT/build.sh"

    local staged_include="$XENSE_PYBIND_ROOT/include"
    local staged_lib="$XENSE_PYBIND_ROOT/lib"
    local export_include="$XENSE_VENDOR_SDK_EXPORT_ROOT/include"
    local export_lib="$XENSE_VENDOR_SDK_EXPORT_ROOT/linux/64"

    if [[ ! -f "$export_include/PXREARobotSDK.h" ]]; then
        echo "ERROR: PXREARobotSDK header is missing after build:"
        echo "  $export_include/PXREARobotSDK.h"
        exit 1
    fi
    if [[ ! -d "$XENSE_VENDOR_SDK_ROOT/nlohmann" ]]; then
        echo "ERROR: nlohmann headers are missing from:"
        echo "  $XENSE_VENDOR_SDK_ROOT/nlohmann"
        exit 1
    fi
    if [[ ! -f "$export_lib/libPXREARobotSDK.so" ]]; then
        echo "ERROR: PXREARobotSDK shared library is missing after build:"
        echo "  $export_lib/libPXREARobotSDK.so"
        exit 1
    fi

    echo "[xense] Staging SDK payload into $XENSE_PYBIND_ROOT"
    mkdir -p "$staged_include" "$staged_lib"
    cp -f "$export_include/PXREARobotSDK.h" "$staged_include/"
    rm -rf "$staged_include/nlohmann"
    cp -R "$XENSE_VENDOR_SDK_ROOT/nlohmann" "$staged_include/"
    cp -f "$export_lib/libPXREARobotSDK.so" "$staged_lib/"

    echo "[xense] Installing xensevr_pc_service_sdk from $XENSE_PYBIND_ROOT"
    "$PYTHON_BIN" -m pip uninstall -y xensevr_pc_service_sdk >/dev/null 2>&1 || true
    "$PYTHON_BIN" -m pip install -e "$XENSE_PYBIND_ROOT" --no-build-isolation
}

verify_install() {
    echo "[check] Verifying imports"
    "$PYTHON_BIN" - <<'PY'
import lerobot
import motorbridge
import pinocchio
import reBotArm_control_py
import xensevr_pc_service_sdk
from lerobot.robots import make_robot_from_config
from lerobot.robots.rebot_rs_follower import RebotRSFollowerRobotConfig

cfg = RebotRSFollowerRobotConfig(id="verify_only")
print("lerobot:", lerobot.__file__)
print("motorbridge:", motorbridge.__file__)
print("pinocchio:", pinocchio.__file__)
print("reBotArm_control_py:", reBotArm_control_py.__file__)
print("xensevr_pc_service_sdk:", xensevr_pc_service_sdk.__file__)
print("robot:", type(make_robot_from_config(cfg)).__name__)
PY
}

main() {
    case "${1:-}" in
        --help|-h|"")
            usage
            exit 0
            ;;
        --install)
            ;;
        *)
            usage
            exit 1
            ;;
    esac

    require_python
    require_active_env
    install_lerobot
    install_rebot_sdk
    install_xense_sdk
    verify_install

    cat <<EOF

Done.
Run teleop with:
  lerobot-teleoperate --robot.type=rebot_rs_follower --teleop.type=pico4
EOF
}

main "$@"
