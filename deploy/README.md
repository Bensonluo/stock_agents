# Stock Agents 腾讯云部署指南

## 架构说明

```
┌─────────────────────────────────────────────────────────────┐
│                     Nginx (80/443)                          │
│                    101.43.97.91                            │
├─────────────────────────────────────────────────────────────┤
│  /                    → portfolio-fe (3000)                 │
│  /api                 → rag_chatbot (8000)                  │
│  /stock               → stock_agents 前端 (3002)            │
│  /stock-api           → stock_agents 后端 (8001)            │
└─────────────────────────────────────────────────────────────┘
```

## 端口分配

| 服务 | 内部端口 | 外部访问 | 说明 |
|------|---------|---------|------|
| portfolio-fe | 3000 | / | 个人作品集 |
| rag_chatbot API | 8000 | /api | RAG 聊天机器人 |
| stock_agents 前端 | 3002 | /stock | 股票分析前端 |
| stock_agents 后端 | 8001 | /stock-api | 股票分析 API |

## 部署步骤

### 前提条件

- SSH 密钥: `~/.ssh/ssh_tencent.pem`
- 服务器用户: `ubuntu`
- 服务器 IP: `101.43.97.91`

### 1. 确保 .env 文件存在

```bash
cd /Users/luopeng/Documents/GitHub/stock_agents
cp .env.example .env
# 编辑 .env 填入必要的配置
```

### 2. 部署 stock_agents 到服务器

```bash
cd deploy
./deploy.sh 101.43.97.91
```

这个脚本会：
- 在服务器上创建目录 `/opt/stock_agents`
- 上传所有文件
- 构建 Docker 镜像
- 启动服务（端口 3002 和 8001）

### 3. 配置 Nginx 反向代理

```bash
cd deploy
./install-nginx.sh 101.43.97.91
```

这个脚本会：
- 备份现有 Nginx 配置
- 添加 `/stock` 和 `/stock-api` 路由规则
- 重载 Nginx

### 4. 验证部署

```bash
# 测试前端
curl http://101.43.97.91/stock

# 测试后端
curl http://101.43.97.91/stock-api/api/health

# 访问浏览器
open http://101.43.97.91/stock
```

## 常用命令

```bash
# SSH 连接服务器
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91

# 查看服务状态
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "cd /opt/stock_agents && docker-compose ps"

# 查看日志
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "cd /opt/stock_agents && docker-compose logs -f"

# 重启服务
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "cd /opt/stock_agents && docker-compose restart"

# 停止服务
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "cd /opt/stock_agents && docker-compose down"
```

## 故障排查

### 端口冲突

如果遇到端口冲突，检查：

```bash
# 在服务器上查看端口占用
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "netstat -tlnp | grep -E ':(3000|3002|8000|8001)'"
```

### 容器无法启动

```bash
# 查看详细日志
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "cd /opt/stock_agents && docker-compose logs api"
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "cd /opt/stock_agents && docker-compose logs frontend"
```

### Nginx 配置问题

```bash
# 测试 Nginx 配置
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "sudo nginx -t"

# 查看 Nginx 日志
ssh -i ~/.ssh/ssh_tencent.pem ubuntu@101.43.97.91 "sudo tail -f /var/log/nginx/error.log"
```

## 更新部署

当代码有更新时：

```bash
cd deploy
./deploy.sh 101.43.97.91
```

## 与其他项目的关系

- **portfolio-fe**: 在 `/projects/stock-agents` 添加了项目入口，点击 "Live Demo" 会跳转到 `/stock`
- **rag_chatbot**: 独立运行在 `/api`，与 stock_agents 无冲突

## 环境变量

主要环境变量（在 `.env` 中配置）：

```bash
# LLM API (必需)
OPENAI_API_KEY=sk-xxx
# 或
ANTHROPIC_API_KEY=sk-ant-xxx

# 可选配置
LOG_LEVEL=INFO
MAX_RETRIES=3
TIMEOUT_PER_AGENT=300
```

## 文件说明

```
deploy/
├── deploy.sh              # 部署脚本（上传代码、启动服务）
├── install-nginx.sh       # Nginx 配置脚本
├── nginx-full-config.conf # 完整的 Nginx 配置文件
└── README.md             # 本文档
```
