#!/bin/bash

# ============================================
# 创建 iot-edge20 数据库
# ============================================
# 在 postgres-server 容器中创建 iot-edge20 数据库（若不存在）
# 使用方法：
#   ./create_iot_edge20_db.sh
# ============================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

CONTAINER_NAME="postgres-server"
DB_USER="postgres"
DB_NAME="iot-edge20"

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

# 检查 Docker 与容器
if ! docker info &> /dev/null; then
    print_error "Docker daemon 未运行或无法访问"
    exit 1
fi

if ! docker ps -a --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    print_error "PostgreSQL 容器 $CONTAINER_NAME 不存在"
    print_info "请先启动 PostgreSQL: docker-compose up -d PostgresSQL 或 docker compose up -d PostgresSQL"
    exit 1
fi

if ! docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    print_warning "容器未运行，正在启动..."
    docker start "$CONTAINER_NAME"
    print_info "等待 PostgreSQL 就绪..."
    for i in {1..30}; do
        if docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" > /dev/null 2>&1; then
            break
        fi
        sleep 2
    done
fi

if ! docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" > /dev/null 2>&1; then
    print_error "PostgreSQL 未就绪，请检查: docker logs $CONTAINER_NAME"
    exit 1
fi

# 检查数据库是否已存在
exists=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME';" 2>/dev/null || echo "")

if [ -n "$exists" ] && [ "$exists" = "1" ]; then
    print_success "数据库 $DB_NAME 已存在，无需创建"
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size FROM pg_database WHERE datname = '$DB_NAME';"
    exit 0
fi

# 创建数据库
print_info "正在创建数据库: $DB_NAME"
if docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "CREATE DATABASE \"$DB_NAME\";"; then
    print_success "数据库 $DB_NAME 创建成功"
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d postgres -c "\l" | grep -E "Name|$DB_NAME" || true
else
    print_error "创建数据库 $DB_NAME 失败"
    exit 1
fi
