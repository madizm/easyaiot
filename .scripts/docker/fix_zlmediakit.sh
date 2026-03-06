#!/bin/bash

# ============================================
# ZLMediaKit 容器修复脚本
# ============================================
# 用于修复电脑重启后 ZLMediaKit 容器端口未暴露的问题（如 6080、4443 等）
# 执行：停止并删除容器 -> 确保数据目录与配置 -> 按 docker-compose 重新创建并启动
# 使用方法：
#   ./fix_zlmediakit.sh
# ============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_section() {
    echo ""
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  $1${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
}

# 检查 Docker 是否运行
check_docker() {
    if ! docker info &> /dev/null; then
        print_error "Docker daemon 未运行或无法访问"
        exit 1
    fi
}

# 获取 docker compose 命令
get_compose_cmd() {
    if command -v docker-compose &> /dev/null; then
        echo "docker-compose"
    else
        echo "docker compose"
    fi
}

# 显示当前容器端口映射（用于诊断）
show_current_ports() {
    if docker ps -a --filter "name=zlmediakit-server" --format "{{.Names}}" | grep -q "zlmediakit-server"; then
        print_info "当前 zlmediakit-server 端口映射："
        docker port zlmediakit-server 2>/dev/null || print_warning "无法获取端口映射（可能未暴露）"
    else
        print_info "当前未发现 zlmediakit-server 容器"
    fi
}

# 停止并移除 ZLMediaKit 容器
stop_zlmediakit() {
    print_section "停止并移除 ZLMediaKit 容器"

    local compose_cmd
    compose_cmd=$(get_compose_cmd)

    # 1. 强制终止
    print_info "步骤 1: 强制终止 zlmediakit-server 容器..."
    if docker ps --filter "name=zlmediakit-server" --format "{{.Names}}" | grep -q "zlmediakit-server"; then
        docker kill zlmediakit-server 2>/dev/null && print_success "容器已强制终止" || print_info "容器未运行，跳过 kill"
    else
        print_info "容器未运行，跳过 kill"
    fi

    # 2. 优雅停止
    print_info "步骤 2: 优雅停止 zlmediakit-server 容器..."
    if docker ps -a --filter "name=zlmediakit-server" --format "{{.Names}}" | grep -q "zlmediakit-server"; then
        docker stop zlmediakit-server 2>/dev/null && print_success "容器已停止" || print_info "容器已停止"
    else
        print_info "容器不存在，跳过 stop"
    fi

    # 3. 使用 compose 清理
    print_info "步骤 3: 使用 docker compose 清理 ZLMediaKit 服务..."
    cd "$SCRIPT_DIR"
    $compose_cmd stop ZLMediaKit 2>/dev/null || true
    $compose_cmd rm -f ZLMediaKit 2>/dev/null || true
    print_success "ZLMediaKit 容器已清理"

    # 4. 确保容器完全移除
    print_info "步骤 4: 确保容器完全移除..."
    if docker ps -a --filter "name=zlmediakit-server" --format "{{.Names}}" | grep -q "zlmediakit-server"; then
        docker rm -f zlmediakit-server 2>/dev/null && print_success "残留容器已移除" || print_warning "无法移除残留容器"
    else
        print_success "容器已完全移除"
    fi

    sleep 2
}

# 确保 ZLMediaKit 数据目录与配置存在
prepare_zlmediakit_dirs_and_config() {
    print_section "检查 ZLMediaKit 数据目录与配置"

    local zlm_base="${SCRIPT_DIR}/../zlmediakit"
    local zlm_www="${zlm_base}/www"
    local zlm_log="${zlm_base}/log"
    local zlm_conf="${zlm_base}/conf"
    local zlm_config_file="${zlm_conf}/config.ini"
    local zlm_default_secret="035c73f7-bb6b-4889-a715-d9eb2d1925cc"

    print_info "数据目录根路径: $zlm_base"

    mkdir -p "$zlm_www" "$zlm_log" "$zlm_conf"
    print_success "目录已就绪: www, log, conf"

    # 方案 A：无论原来是否存在，都强制重置为项目默认配置（包含固定 secret）
    print_warning "重置 ZLMediaKit 配置文件为项目默认配置（包含固定 secret）: $zlm_config_file"
    cat > "$zlm_config_file" << ZLMEOF
[api]
apiDebug=1
defaultSnap=./www/logo.png
downloadRoot=./www;
secret=${zlm_default_secret}
snapRoot=./www/snap/

[general]
enableVhost=0
listen_ip=::
mediaServerId=zlmediakit

[http]
allow_cross_domains=1
port=80
rootPath=./www
sslport=443

[protocol]
enable_rtmp=1
enable_rtsp=1

[rtmp]
port=10001

[rtsp]
port=10002

[rtp_proxy]
port=10003
port_range=30000-30500
ZLMEOF
    print_success "已创建默认配置文件: $zlm_config_file"
}

# 启动 ZLMediaKit 容器（按 docker-compose 暴露所有端口）
start_zlmediakit() {
    print_section "启动 ZLMediaKit 容器"

    local compose_cmd
    compose_cmd=$(get_compose_cmd)

    print_info "使用命令: $compose_cmd"
    cd "$SCRIPT_DIR"

    print_info "重新创建并启动 ZLMediaKit 容器（将重新绑定所有端口）..."
    if $compose_cmd up -d --force-recreate --no-deps ZLMediaKit 2>&1; then
        print_success "ZLMediaKit 容器启动命令已执行"
    else
        print_error "启动 ZLMediaKit 容器失败"
        return 1
    fi
}

# 等待并验证服务
# 从 ZLM 配置文件中读取 api.secret（调用 ZLM HTTP API 必须带 secret，否则会报 Required parameter missed: "secret"）
get_zlm_api_secret() {
    local conf="$SCRIPT_DIR/../zlmediakit/conf/config.ini"
    if [ -f "$conf" ]; then
        awk -F= '/^\[api\]/ { in_api=1; next } /^\[/ { in_api=0 } in_api && $1=="secret" { gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2; exit }' "$conf"
    fi
}

wait_and_verify_zlmediakit() {
    print_section "等待并验证 ZLMediaKit 服务"

    local max_attempts=60
    local attempt=0
    local zlm_secret
    zlm_secret=$(get_zlm_api_secret)

    print_info "等待 HTTP 接口就绪 (http://localhost:6080)..."
    while [ $attempt -lt $max_attempts ]; do
        if [ -n "$zlm_secret" ]; then
            if curl -s --connect-timeout 2 "http://localhost:6080/index/api/getServerConfig?secret=$zlm_secret" > /dev/null 2>&1; then
                print_success "ZLMediaKit 服务已就绪，端口 6080 可访问"
                return 0
            fi
        else
            if curl -s --connect-timeout 2 "http://localhost:6080/index/api/getServerConfig" > /dev/null 2>&1; then
                print_success "ZLMediaKit 服务已就绪，端口 6080 可访问"
                return 0
            fi
        fi
        attempt=$((attempt + 1))
        sleep 2
    done

    print_warning "ZLMediaKit 未在预期时间内响应，请检查: docker logs zlmediakit-server"
    return 1
}

# 支持 -y 跳过确认
if [[ "${1:-}" == "-y" ]] || [[ "${1:-}" == "--yes" ]]; then
    SKIP_CONFIRM=1
fi

# 主流程（可被调用时不读入）
run_fix() {
    check_docker
    show_current_ports
    echo ""
    stop_zlmediakit
    prepare_zlmediakit_dirs_and_config
    start_zlmediakit
    wait_and_verify_zlmediakit
    print_section "修复完成"
    print_success "ZLMediaKit 修复脚本执行完成"
    echo ""
    show_current_ports
    echo ""
    print_info "常用端口："
    print_info "  HTTP 播流: 6080, HTTPS: 4443, RTSP: 5540, RTMP: 10935, RTP: 10000, WebRTC: 8001, SRT: 9002"
    print_info "若仍有问题，请查看: docker logs zlmediakit-server"
}

# 主函数（交互式）
main() {
    print_section "ZLMediaKit 容器修复脚本"

    print_info "此脚本将："
    print_info "  1. 停止并移除现有 zlmediakit-server 容器"
    print_info "  2. 确保数据目录与配置存在"
    print_info "  3. 按 docker-compose 重新创建并启动容器（暴露 6080 等所有端口）"
    print_info "  4. 验证 HTTP 接口 (6080) 可访问"
    echo ""

    show_current_ports
    echo ""

    if [[ -z "${SKIP_CONFIRM:-}" ]]; then
        read -p "是否继续？(y/N): " -r response
        if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
            print_info "已取消操作"
            exit 0
        fi
    fi

    run_fix
}

# 入口：-y/--yes 为非交互模式
case "${1:-}" in
    -y|--yes) SKIP_CONFIRM=1 ;;
esac
main "$@"
