#!/bin/bash
# Stock Agents 部署脚本 - 腾讯云 ECS
# 用法: ./deploy.sh [服务器IP]
# 示例: ./deploy.sh 124.220.28.49

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 服务器配置
SERVER_IP=${1:-"124.220.28.49"}
SERVER_USER="ubuntu"
SSH_KEY="${HOME}/.ssh/ssh_tencent.pem"
SERVER_DIR="/opt/stock_agents"
PROJECT_NAME="stock_agents"

# SSH 命令前缀
SSH_CMD="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Stock Agents 部署到腾讯云${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "服务器: ${SERVER_IP}"
echo -e "用户: ${SERVER_USER}"
echo -e "部署目录: ${SERVER_DIR}"
echo ""

# 检查密钥文件
if [ ! -f "$SSH_KEY" ]; then
    echo -e "${RED}错误: SSH 密钥文件不存在: $SSH_KEY${NC}"
    exit 1
fi

# 1. 检查必要文件
echo -e "${YELLOW}[1/6] 检查必要文件...${NC}"
# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${RED}错误: .env 文件不存在！${NC}"
    echo "请先创建 $PROJECT_ROOT/.env 文件（参考 .env.example）"
    exit 1
fi
echo -e "${GREEN}✓ 文件检查完成${NC}"

# 2. 本地构建镜像（可选，为了加快部署速度）
echo -e "${YELLOW}[2/6] 构建前端...${NC}"
cd "$PROJECT_ROOT/frontend"
npm run build
cd "$PROJECT_ROOT"
echo -e "${GREEN}✓ 前端构建完成${NC}"

# 3. 在服务器上创建目录
echo -e "${YELLOW}[3/6] 准备服务器环境...${NC}"
${SSH_CMD} "sudo mkdir -p ${SERVER_DIR}/{data,logs} && sudo chown -R ${SERVER_USER}:${SERVER_USER} ${SERVER_DIR}"
echo -e "${GREEN}✓ 服务器目录准备完成${NC}"

# 4. 上传文件到服务器
echo -e "${YELLOW}[4/6] 上传文件到服务器...${NC}"
# 排除不需要的文件
rsync -avz -e "ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no" --delete \
    --exclude 'node_modules' \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude 'frontend/node_modules' \
    --exclude 'frontend/.next' \
    --exclude 'data/*.db' \
    --exclude 'logs/*' \
    --exclude '.idea' \
    --exclude '.DS_Store' \
    "$PROJECT_ROOT"/ ${SERVER_USER}@${SERVER_IP}:${SERVER_DIR}/
echo -e "${GREEN}✓ 文件上传完成${NC}"

# 5. 在服务器上构建和启动
echo -e "${YELLOW}[5/6] 在服务器上构建和启动...${NC}"
${SSH_CMD} << 'ENDSSH'
cd /opt/stock_agents

# 停止旧容器
sudo docker-compose down 2>/dev/null || true

# 构建新镜像
sudo docker-compose build --no-cache

# 启动服务
sudo docker-compose up -d

# 等待服务健康
echo "等待服务启动..."
sleep 10
ENDSSH
echo -e "${GREEN}✓ 服务启动完成${NC}"

# 6. 验证部署
echo -e "${YELLOW}[6/6] 验证部署...${NC}"
sleep 5

# 检查容器状态
${SSH_CMD} "sudo docker ps --filter 'name=stock_agent' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

# 检查健康状态
echo ""
echo "检查服务健康状态:"
${SSH_CMD} "curl -sf http://localhost:8001/api/health || echo '后端健康检查失败'"
${SSH_CMD} "curl -sf http://localhost:3002 || echo '前端健康检查失败'"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}部署完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "服务已启动在:"
echo -e "  前端: localhost:3002"
echo -e "  后端: localhost:8001"
echo ""
echo -e "下一步: 配置 Nginx 反向代理"
echo -e "  运行: ./install-nginx.sh ${SERVER_IP}"
echo -e ""
echo -e "配置 Nginx 后访问:"
echo -e "  http://${SERVER_IP}/stock"
echo -e "  http://${SERVER_IP}/stock-api"
echo ""
