#!/bin/bash
# Stock Agents Nginx 配置安装脚本
# 用法: ./install-nginx.sh [服务器IP]
# 示例: ./install-nginx.sh 124.220.28.49

set -e

SERVER_IP=${1:-"124.220.28.49"}
SERVER_USER="ubuntu"
SSH_KEY="${HOME}/.ssh/ssh_tencent.pem"

echo "=========================================="
echo "安装 Stock Agents Nginx 配置"
echo "服务器: $SERVER_IP"
echo "用户: $SERVER_USER"
echo "=========================================="

# 1. 备份现有配置
echo "[1/4] 备份现有 Nginx 配置..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} \
    "sudo cp /etc/nginx/sites-available/default /etc/nginx/sites-available/default.backup.\$(date +%Y%m%d_%H%M%S)"

# 2. 上传新配置
echo "[2/4] 上传新的 Nginx 配置..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    nginx-full-config.conf \
    ${SERVER_USER}@${SERVER_IP}:/tmp/nginx-default-new

# 3. 安装新配置
echo "[3/4] 安装新配置..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
# 移动配置文件
sudo mv /tmp/nginx-default-new /etc/nginx/sites-available/default

# 测试配置
sudo nginx -t

if [ $? -eq 0 ]; then
    echo "配置测试通过，重载 Nginx..."
    sudo systemctl reload nginx
    echo "Nginx 配置完成！"
else
    echo "配置测试失败！"
    exit 1
fi
ENDSSH

echo "[4/4] 验证配置..."
sleep 2
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} \
    "sudo systemctl status nginx | head -5"

echo ""
echo "=========================================="
echo "Nginx 配置安装完成！"
echo "=========================================="
echo ""
echo "访问地址:"
echo "  Portfolio:     http://$SERVER_IP/"
echo "  RAG API:       http://$SERVER_IP/api"
echo "  Stock Agents:  http://$SERVER_IP/stock"
echo "  Stock API:     http://$SERVER_IP/stock-api"
echo ""
echo "验证命令:"
echo "  curl http://$SERVER_IP/stock"
echo "  curl http://$SERVER_IP/stock-api/api/health"
echo ""
