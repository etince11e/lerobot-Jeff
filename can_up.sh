#!/usr/bin/env bash

set -Eeuo pipefail

interface="can0"
bitrate="1000000"

usage() {
    cat <<'EOF'
用法：
  ./can_up.sh [接口名] [波特率]

示例：
  ./can_up.sh                 # 启动 can0，波特率 1000000
  ./can_up.sh can1            # 启动 can1，波特率 1000000
  ./can_up.sh can0 500000     # 启动 can0，波特率 500000
  ./can_up.sh --help
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if (( $# > 2 )); then
    usage >&2
    exit 2
fi

interface="${1:-$interface}"
bitrate="${2:-$bitrate}"

if [[ ! "$interface" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
    echo "错误：接口名 '$interface' 无效。" >&2
    exit 2
fi

if [[ ! "$bitrate" =~ ^[1-9][0-9]*$ ]]; then
    echo "错误：波特率 '$bitrate' 必须是正整数。" >&2
    exit 2
fi

if ! command -v ip >/dev/null 2>&1; then
    echo "错误：找不到 ip 命令，请先安装 iproute2。" >&2
    exit 1
fi

if ! ip link show dev "$interface" >/dev/null 2>&1; then
    echo "错误：没有找到 CAN 接口 '$interface'。" >&2
    echo "请检查 USB-CAN 设备是否已连接，以及驱动是否已加载。" >&2
    exit 1
fi

echo "正在启动 $interface（bitrate=$bitrate）..."

# 先验证 sudo 权限，避免配置进行到一半时才提示输入密码。
sudo -v
sudo ip link set dev "$interface" down 2>/dev/null || true
sudo ip link set dev "$interface" type can bitrate "$bitrate"
sudo ip link set dev "$interface" up

if ! ip link show dev "$interface" | grep -qE '[<,]UP[,>]'; then
    echo "错误：$interface 未成功进入 UP 状态。" >&2
    exit 1
fi

echo "$interface 已成功启动。"
ip -details link show dev "$interface"
