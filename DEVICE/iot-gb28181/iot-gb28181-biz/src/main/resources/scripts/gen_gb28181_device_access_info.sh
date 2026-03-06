#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# GB28181 设备接入信息批量生成脚本
# 默认生成 10 组设备接入信息，可通过参数指定 1～100 组
# 使用前请根据实际部署的 SIP 服务修改下方「可配置项」
# ---------------------------------------------------------------------------

set -e

# ========== 可配置项（请根据实际 iot-gb28181 的 sip 配置修改） ==========
# 对应 application.yaml / application-*.yaml 中的 sip 节点
SIP_SERVER_ID="${SIP_SERVER_ID:-41010500002000000001}"
SIP_SERVER_DOMAIN="${SIP_SERVER_DOMAIN:-4101050000}"
SIP_SERVER_PORT="${SIP_SERVER_PORT:-8116}"
# 主备 SIP 服务器地址（多机时填写，逗号分隔；脚本会按顺序输出为「SIP服务器一」「SIP服务器二」）
SIP_SERVER_ADDRS="${SIP_SERVER_ADDRS:-192.168.240.200,192.168.240.201}"
# 设备国标 ID 前缀（20 位中的前 14 位，后 6 位由脚本按序号填充，如 000001～000100）
DEVICE_ID_PREFIX="${DEVICE_ID_PREFIX:-34020000001320}"
# 本地 SIP 端口（设备端本机端口，仅用于输出参考）
LOCAL_SIP_PORT="${LOCAL_SIP_PORT:-5060}"
# 传输协议与协议版本（仅用于输出）
TRANSPORT="${TRANSPORT:-UDP}"
PROTOCOL_VERSION="${PROTOCOL_VERSION:-GB/T28181-2022}"

# 默认生成组数
DEFAULT_COUNT=10
MIN_COUNT=1
MAX_COUNT=100

# 生成指定长度的随机字符串（字母数字），用于设备认证密码（不依赖 openssl，避免 libssl 缺失）
rand_str() {
  local len="${1:-32}"
  tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c "$len"
}

# 生成指定长度的随机数字串（0-9），用于设备国标 ID 后缀，保证每次运行随机
rand_digits() {
  local len="${1:-6}"
  tr -dc '0-9' </dev/urandom 2>/dev/null | head -c "$len"
}

# 解析 SIP 服务器地址列表
parse_sip_addrs() {
  IFS=',' read -ra ADDRS <<< "$SIP_SERVER_ADDRS"
  for a in "${ADDRS[@]}"; do
    echo "$a"
  done
}

# 生成单组设备接入信息（文本块）
# 参数：组号、设备国标ID、认证密码、SIP服务器地址（主）、SIP服务器地址（备，可选）
print_one_group() {
  local group_num="$1"
  local device_id="$2"
  local password="$3"
  local sip_addr_1="$4"
  local sip_addr_2="${5:-}"

  echo "========== 设备组 #${group_num} =========="
  echo "传输协议：${TRANSPORT}"
  echo "协议版本：${PROTOCOL_VERSION}"
  echo "SIP服务器ID：${SIP_SERVER_ID}"
  echo "SIP服务器域：${SIP_SERVER_DOMAIN}"
  echo "SIP服务器地址：${sip_addr_1}"
  echo "SIP服务器端口：${SIP_SERVER_PORT}"
  echo "SIP用户名：${device_id}"
  echo "SIP用户认证ID：${device_id}"
  echo "SIP用户认证密码：${password}"
  echo "本地SIP端口：${LOCAL_SIP_PORT}"
  if [[ -n "$sip_addr_2" ]]; then
    echo "--- 备用SIP服务器地址：${sip_addr_2}（其余参数同上）"
  fi
  echo ""
}

main() {
  local count="$DEFAULT_COUNT"
  if [[ -n "${1:-}" ]]; then
    if [[ ! "$1" =~ ^[0-9]+$ ]]; then
      echo "用法: $0 [组数]" >&2
      echo "  组数: 1～${MAX_COUNT}，默认 ${DEFAULT_COUNT}" >&2
      exit 1
    fi
    count="$1"
    if (( count < MIN_COUNT || count > MAX_COUNT )); then
      echo "错误: 组数须在 ${MIN_COUNT}～${MAX_COUNT} 之间" >&2
      exit 1
    fi
  fi

  # 解析主备地址
  mapfile -t SIP_ADDR_ARR < <(parse_sip_addrs)
  sip_addr_1="${SIP_ADDR_ARR[0]:-$SIP_SERVER_ADDRS}"
  sip_addr_2="${SIP_ADDR_ARR[1]:-}"

  echo "生成 GB28181 设备接入信息，共 ${count} 组（SIP 服务器: ${sip_addr_1}${sip_addr_2:+, ${sip_addr_2}} :${SIP_SERVER_PORT}）"
  echo ""

  for i in $(seq 1 "$count"); do
    # 设备国标 ID：前缀（14 位）+ 6 位随机数字，每次运行随机
    rand_suffix=$(rand_digits 6)
    device_id="${DEVICE_ID_PREFIX}${rand_suffix}"
    password=$(rand_str 32)
    print_one_group "$i" "$device_id" "$password" "$sip_addr_1" "$sip_addr_2"
  done

  echo "========== 生成完成，共 ${count} 组 =========="
}

main "$@"
