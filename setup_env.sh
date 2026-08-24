#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LEROBOT_ROOT="$SCRIPT_DIR"
CONDA_ENV_FILE="$LEROBOT_ROOT/conda_environment.yaml"
SDK_ROOT="${REBOT_SDK_ROOT:-$LEROBOT_ROOT/third_party/reBotArm_control_py}"
XENSE_VENDOR_ROOT="${XENSE_VENDOR_ROOT:-$LEROBOT_ROOT/third_party/XenseVR-PC-Service}"
XENSE_VENDOR_SDK_ROOT="${XENSE_VENDOR_SDK_ROOT:-$XENSE_VENDOR_ROOT/RoboticsService/PXREARobotSDK}"
XENSE_VENDOR_SDK_EXPORT_ROOT="${XENSE_VENDOR_SDK_EXPORT_ROOT:-$XENSE_VENDOR_ROOT/RoboticsService/SDK}"
XENSE_PYBIND_ROOT="${XENSE_PYBIND_ROOT:-$LEROBOT_ROOT/src/lerobot/teleoperators/pico4/xensevr-pc-service-pybind}"
PYTHON_BIN="${PYTHON_BIN:-python}"

usage() {
    cat <<'USAGE'
Usage: ./setup_env.sh <command> [options]
  --conda [env_name]     Create a conda environment (requires Conda/Anaconda)
  --mamba [env_name]     Create a mamba environment (requires Miniforge)
  --install              Install the Rebot LeRobot stack into the active env
  --help, -h             Show this message

Environment variables:
  PYTHON_BIN                Python executable from the active env (default: python)
  REBOT_SDK_ROOT            Path to reBotArm_control_py
                            (default: <lerobot-root>/third_party/reBotArm_control_py)
  XENSE_VENDOR_ROOT         Path to XenseVR-PC-Service
                            (default: <lerobot-root>/third_party/XenseVR-PC-Service)
  XENSE_VENDOR_SDK_ROOT     Path to PXREARobotSDK source tree
                            (default: <XENSE_VENDOR_ROOT>/RoboticsService/PXREARobotSDK)
  XENSE_VENDOR_SDK_EXPORT_ROOT
                            Path to exported SDK payload
                            (default: <XENSE_VENDOR_ROOT>/RoboticsService/SDK)
USAGE
}

source_conda_init() {
    local manager="$1"
    if [[ "$manager" == "mamba" ]]; then
        if [[ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ]]; then
            . "$HOME/miniforge3/etc/profile.d/conda.sh"
        elif [[ -f "$HOME/mambaforge/etc/profile.d/conda.sh" ]]; then
            . "$HOME/mambaforge/etc/profile.d/conda.sh"
        else
            echo "Conda initialization script not found. Please install Miniforge3 or Mambaforge."
            exit 1
        fi
        if [[ -f "$HOME/miniforge3/etc/profile.d/mamba.sh" ]]; then
            . "$HOME/miniforge3/etc/profile.d/mamba.sh"
        elif [[ -f "$HOME/mambaforge/etc/profile.d/mamba.sh" ]]; then
            . "$HOME/mambaforge/etc/profile.d/mamba.sh"
        fi
    else
        if [[ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]]; then
            . "$HOME/miniconda3/etc/profile.d/conda.sh"
        elif [[ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]]; then
            . "$HOME/anaconda3/etc/profile.d/conda.sh"
        else
            echo "Conda initialization script not found. Please install Miniconda3, Anaconda3, or Miniforge3."
            exit 1
        fi
    fi
}

create_environment() {
    local manager="$1"
    local env_name="$2"

    source_conda_init "$manager"

    local conda_cmd="$manager"
    if ! command -v "$conda_cmd" >/dev/null 2>&1; then
        conda_cmd="conda"
    fi
    local env_exists=0
    if "$conda_cmd" env list | awk -v env="$env_name" 'NF >= 2 && $1 == env { found = 1 } END { exit(found ? 0 : 1) }'; then
        env_exists=1
    fi

    if [[ $env_exists -eq 1 ]]; then
        echo "[env] Updating conda environment '$env_name' from $CONDA_ENV_FILE"
        "$conda_cmd" env update -f "$CONDA_ENV_FILE" -n "$env_name"
    else
        echo "[env] Creating conda environment '$env_name' from $CONDA_ENV_FILE"
        "$conda_cmd" env create -f "$CONDA_ENV_FILE" -n "$env_name"
    fi
    echo "[env] Done. Activate it with: $manager activate $env_name"
}

require_python() {
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        echo "ERROR: $PYTHON_BIN is required. Activate the target env first."
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
        "Activate your lerobot-rebot environment before running this script."
    )

if sys.version_info < (3, 12):
    raise SystemExit(
        f"ERROR: Python {sys.version.split()[0]} is active. "
        "lerobot-rebot requires Python 3.12."
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
    if [[ ! -f "$SDK_ROOT/pyproject.toml" ]]; then
        echo "ERROR: reBotArm_control_py not found or not initialized at:"
        echo "  $SDK_ROOT"
        exit 1
    fi

    echo "[rebot] Installing editable reBotArm_control_py from $SDK_ROOT"
    "$PYTHON_BIN" -m pip install -e "$SDK_ROOT" --ignore-requires-python --no-build-isolation
}

detect_xense_arch_dir() {
    case "$(uname -m)" in
        aarch64|arm64) echo "aarch64" ;;
        *) echo "" ;;
    esac
}

find_xense_export_lib() {
    local candidates=(
        "$XENSE_VENDOR_SDK_EXPORT_ROOT/linux/64/libPXREARobotSDK.so"
        "$XENSE_VENDOR_SDK_EXPORT_ROOT/linux_aarch64/64/libPXREARobotSDK.so"
        "$XENSE_VENDOR_ROOT/RoboticsService/Redistributable/linux/SDK/clientso/64/libPXREARobotSDK.so"
        "$XENSE_VENDOR_ROOT/RoboticsService/Redistributable/linux_aarch64/SDK/clientso/64/libPXREARobotSDK.so"
    )
    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

install_xense_sdk() {
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

    echo "[xense] Building vendor PXREARobotSDK from $XENSE_VENDOR_SDK_ROOT"
    bash "$XENSE_VENDOR_SDK_ROOT/build.sh"

    local xense_arch_dir
    xense_arch_dir="$(detect_xense_arch_dir)"
    local staged_include="$XENSE_PYBIND_ROOT/include"
    local staged_lib="$XENSE_PYBIND_ROOT/lib"
    if [[ -n "$xense_arch_dir" ]]; then
        staged_include="$staged_include/$xense_arch_dir"
        staged_lib="$staged_lib/$xense_arch_dir"
    fi
    local export_include="$XENSE_VENDOR_SDK_EXPORT_ROOT/include/PXREARobotSDK.h"
    local export_lib
    export_lib="$(find_xense_export_lib)"
    local nlohmann_src="$XENSE_VENDOR_SDK_ROOT/nlohmann"

    if [[ ! -f "$export_include" ]]; then
        echo "ERROR: PXREARobotSDK header is missing after build:"
        echo "  $export_include"
        exit 1
    fi
    if [[ ! -d "$nlohmann_src" ]]; then
        echo "ERROR: nlohmann headers are missing from:"
        echo "  $nlohmann_src"
        exit 1
    fi
    if [[ -z "${export_lib:-}" ]]; then
        echo "ERROR: PXREARobotSDK shared library is missing after build."
        exit 1
    fi

    if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("pybind11") else 1)
PY
    then
        "$PYTHON_BIN" -m pip install pybind11
    fi

    echo "[xense] Staging SDK payload into $XENSE_PYBIND_ROOT"
    mkdir -p "$staged_include" "$staged_lib"
    cp -f "$export_include" "$staged_include/"
    rm -rf "$staged_include/nlohmann"
    cp -R "$nlohmann_src" "$staged_include/"
    cp -f "$export_lib" "$staged_lib/"

    echo "[xense] Installing xensevr_pc_service_sdk from $XENSE_PYBIND_ROOT"
    (
        cd "$XENSE_PYBIND_ROOT"
        rm -rf build *.egg-info
        "$PYTHON_BIN" -m pip uninstall -y xensevr_pc_service_sdk >/dev/null 2>&1 || true
        "$PYTHON_BIN" -m pip install -e . --no-build-isolation
    )
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
from lerobot.teleoperators import make_teleoperator_from_config
from lerobot.teleoperators.pico4 import Pico4Config

robot = make_robot_from_config(RebotRSFollowerRobotConfig(id="verify_only"))
teleop = make_teleoperator_from_config(Pico4Config(id="verify_only"))

print("lerobot:", lerobot.__file__)
print("motorbridge:", motorbridge.__file__)
print("pinocchio:", pinocchio.__file__)
print("reBotArm_control_py:", reBotArm_control_py.__file__)
print("xensevr_pc_service_sdk:", xensevr_pc_service_sdk.__file__)
print("robot:", type(robot).__name__)
print("teleop:", type(teleop).__name__)
PY
}

main() {
    case "${1:-}" in
        --help|-h|"")
            usage
            exit 0
            ;;
        --conda)
            create_environment "conda" "${2:-lerobot-rebot}"
            exit 0
            ;;
        --mamba)
            create_environment "mamba" "${2:-lerobot-rebot}"
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

    cat <<'EOF'

Done.
Run teleop with:
  lerobot-teleoperate --robot.type=rebot_rs_follower --teleop.type=pico4
EOF
}

main "$@"
