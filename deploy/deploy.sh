#!/bin/bash
# Stock Agents 部署脚本 - 腾讯云 ECS
# 用法: ./deploy.sh [服务器IP]
# 示例: ./deploy.sh 124.220.28.49

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 服务器配置
SERVER_IP=${1:-"101.43.97.91"}
SERVER_USER="ubuntu"
SSH_KEY="${HOME}/.ssh/ssh_tencent.pem"
SERVER_DIR="/opt/stock_agents"
PROJECT_NAME="stock_agents"
DEPLOY_ID="$(date +%Y%m%d-%H%M%S)"

# SSH 命令前缀
SSH_CMD="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Stock Agents 部署到腾讯云${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "服务器: ${SERVER_IP}"
echo -e "用户: ${SERVER_USER}"
echo -e "部署目录: ${SERVER_DIR}"
echo -e "发布编号: ${DEPLOY_ID}"
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

# 3. 在服务器上创建目录和回滚点
echo -e "${YELLOW}[3/6] 准备服务器环境和回滚点...${NC}"
${SSH_CMD} "DEPLOY_ID=${DEPLOY_ID} bash -s" << 'ENDSSH'
set -euo pipefail
SERVER_DIR=/opt/stock_agents
RELEASE_DIR="/opt/stock_agents_releases/${DEPLOY_ID}"

sudo mkdir -p "${SERVER_DIR}"/{data,logs} "${RELEASE_DIR}"
sudo chown -R ubuntu:ubuntu "${SERVER_DIR}"

if [ -f "${SERVER_DIR}/.env" ]; then
    sudo tar -C "${SERVER_DIR}" \
        --exclude=.env --exclude=data --exclude=logs --exclude=.worktrees \
        -czf "${RELEASE_DIR}/source-before.tar.gz" .
fi

if sudo docker inspect stock_agent_api >/dev/null 2>&1; then
    api_image=$(sudo docker inspect stock_agent_api --format '{{.Image}}')
    sudo docker tag "${api_image}" "stock_agents-api:rollback-${DEPLOY_ID}"
fi
if sudo docker inspect stock_agent_frontend >/dev/null 2>&1; then
    frontend_image=$(sudo docker inspect stock_agent_frontend --format '{{.Image}}')
    sudo docker tag "${frontend_image}" "stock_agents-frontend:rollback-${DEPLOY_ID}"
fi

test -f "${SERVER_DIR}/.env"
ENDSSH
echo -e "${GREEN}✓ 服务器目录准备完成${NC}"

# 4. 上传文件到服务器
echo -e "${YELLOW}[4/6] 上传文件到服务器...${NC}"
# 排除不需要的文件(注意:.venv/.omc/.worktrees 等本地环境绝不进服务器)
rsync -avz -e "ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'node_modules' \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude '.venv' \
    --exclude '.omc' \
    --exclude '.claude' \
    --exclude '.sisyphus' \
    --exclude '.worktrees' \
    --exclude '.coverage' \
    --exclude 'htmlcov' \
    --exclude 'tests' \
    --exclude 'docs' \
    --exclude 'frontend/node_modules' \
    --exclude 'frontend/.next' \
    --exclude 'frontend/.omc' \
    --exclude 'data/*.db' \
    --exclude 'logs/*' \
    --exclude '.idea' \
    --exclude '.DS_Store' \
    "$PROJECT_ROOT"/ ${SERVER_USER}@${SERVER_IP}:${SERVER_DIR}/
echo -e "${GREEN}✓ 文件上传完成${NC}"

# 5. 在服务器上构建和启动
echo -e "${YELLOW}[5/6] 在服务器上构建和启动...${NC}"
${SSH_CMD} "DEPLOY_ID=${DEPLOY_ID} bash -s" << 'ENDSSH'
set -euo pipefail
cd /opt/stock_agents

# 旧容器在镜像构建期间继续服务
sudo docker compose build

if sudo docker compose up -d --no-build --wait --wait-timeout 180; then
    echo "新版本健康检查通过"
else
    echo "新版本健康检查失败，开始回滚" >&2
    sudo docker tag "stock_agents-api:rollback-${DEPLOY_ID}" stock_agents-api:latest
    sudo docker tag "stock_agents-frontend:rollback-${DEPLOY_ID}" stock_agents-frontend:latest
    sudo docker compose up -d --no-build --force-recreate --wait --wait-timeout 180
    echo "已恢复上一版本" >&2
    exit 1
fi
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
${SSH_CMD} "curl -fsS http://localhost:8001/api/health && echo"
${SSH_CMD} "curl -fsS http://localhost:8001/api/health/ready && echo"
${SSH_CMD} "curl -fsSI http://localhost:3002/stock | head"

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
