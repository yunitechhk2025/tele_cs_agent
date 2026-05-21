# 部署 / 上线指南

把客服系统部署到一台 Linux 服务器（已验证：阿里云 ECS Ubuntu 24.04，香港地域），通过子域名 + HTTPS 对外提供服务。

## 一次性准备

1. **服务器**：Ubuntu 22.04 / 24.04，2C4G+，已开放安全组：`22 / 80 / 443`。
2. **域名**：在你的注册商处加一条 A 记录，把 `cs.example.com` 指到服务器公网 IP。
3. **环境变量**：

   ```bash
   cd /opt && git clone https://github.com/yunitechhk2025/tele_cs_agent.git cs-agent
   cd cs-agent
   cp backend/.env.example backend/.env
   vi backend/.env   # 至少填 TELEGRAM_BOT_TOKEN / ADMIN_CHAT_ID / OPENAI_API_KEY / 强密码 / JWT_SECRET
   ```

   生产建议覆写：

   ```env
   ADMIN_PASSWORD=<强密码>
   JWT_SECRET=<openssl rand -hex 32>
   BACKEND_URL=https://cs.example.com
   FRONTEND_URL=https://cs.example.com
   ```

## 部署 / 更新（一条命令）

```bash
cd /opt/cs-agent
git pull
sudo bash deploy/install.sh cs.example.com you@yourmail.com
```

脚本会自动：

- 装/校验 docker compose v2 / nginx / certbot
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
- 渲染 nginx 站点配置（模板在 `deploy/nginx/site.conf.tpl`）
- 用 certbot 申请 / 续签 Let's Encrypt 证书（带 80→443 跳转）

## 常用运维命令

```bash
# 查看运行状态
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# 看日志
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend

# 备份数据库
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec db pg_dump -U postgres cs_agent > backup_$(date +%F).sql

# 重启某个服务
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart backend
```

## 端口规划

| 端口 | 监听位置 | 对外 | 说明 |
|---|---|---|---|
| 80 / 443 | 宿主 nginx | ✅ | 公网访问入口（HTTPS 由 certbot 接管） |
| 3010 | docker frontend | ❌ 仅 127.0.0.1 | 由 prod override 限制为 loopback，宿主 nginx 反代 |
| 8000 (容器内) | docker backend | ❌ | 仅容器内网；前端容器内走 `http://backend:8000` |
| 5432 (容器内) | docker db | ❌ | 仅容器内网 |
| 6379 (容器内) | docker redis | ❌ | 仅容器内网 |

> `docker-compose.prod.yml` 用 `!reset` / `!override` 把开发态对外暴露的 5433/6380/8001/3010 全部收回，仅保留 `127.0.0.1:3010` 给宿主 nginx。

## 证书续签

`certbot.timer` 已自动启用，每天检查、过期前 30 天自动续签。手动验证：

```bash
sudo certbot renew --dry-run
systemctl list-timers | grep certbot
```

## 回滚 / 紧急停服

```bash
cd /opt/cs-agent
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
# 恢复某次提交
git checkout <commit-sha>
sudo bash deploy/install.sh cs.example.com you@yourmail.com
```
