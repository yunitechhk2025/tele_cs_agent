#!/usr/bin/env bash
# 一键部署 / 更新脚本（在 ECS 上以 root 或 sudo 运行）
#
# 用法：
#   sudo bash deploy/install.sh cs.yuniagent.ai you@yourmail.com
#
# 步骤：
#   1. 校验依赖（docker / docker compose v2 / nginx / certbot），缺则安装
#   2. 启动 / 更新 docker compose 服务（使用 prod override）
#   3. 渲染 nginx 站点配置并 reload
#   4. 用 certbot 申请 / 续签 HTTPS 证书

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
FRONTEND_PORT="${FRONTEND_PORT:-3010}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
  echo "Usage: sudo bash deploy/install.sh <domain> <email>"
  echo "Example: sudo bash deploy/install.sh cs.yuniagent.ai admin@yuniagent.ai"
  exit 1
fi

echo ">>> Project dir: $PROJECT_DIR"
echo ">>> Domain:      $DOMAIN"
echo ">>> Email:       $EMAIL"

# ---------- 1. Docker Compose v2 plugin ----------
if ! docker compose version >/dev/null 2>&1; then
  echo ">>> Installing docker compose v2 plugin..."
  DOCKER_CONFIG="${DOCKER_CONFIG:-/root/.docker}"
  mkdir -p "$DOCKER_CONFIG/cli-plugins"
  curl -SL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
    -o "$DOCKER_CONFIG/cli-plugins/docker-compose"
  chmod +x "$DOCKER_CONFIG/cli-plugins/docker-compose"
fi
docker compose version

# ---------- 2. nginx + certbot ----------
if ! command -v nginx >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y nginx
fi
if ! command -v certbot >/dev/null 2>&1; then
  apt-get install -y certbot python3-certbot-nginx
fi
systemctl enable --now nginx

# ---------- 3. 启动 / 更新容器 ----------
cd "$PROJECT_DIR"
if [[ ! -f backend/.env ]]; then
  echo "ERROR: backend/.env 不存在，请先 cp backend/.env.example backend/.env 并填好密钥" >&2
  exit 1
fi
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose ps

# ---------- 4. nginx 站点配置 ----------
TPL="$PROJECT_DIR/deploy/nginx/site.conf.tpl"
SITE="/etc/nginx/sites-available/$DOMAIN"
sed -e "s/__SERVER_NAME__/$DOMAIN/g" \
    -e "s/__FRONTEND_PORT__/$FRONTEND_PORT/g" \
    "$TPL" > "$SITE"
ln -sf "$SITE" "/etc/nginx/sites-enabled/$DOMAIN"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ---------- 5. HTTPS 证书 ----------
# 已有证书则尝试续签；没有则申请；--keep-until-expiring 避免重复申请触发 LE 限频
certbot --nginx -d "$DOMAIN" \
  --redirect --agree-tos --no-eff-email \
  -m "$EMAIL" \
  --keep-until-expiring \
  --non-interactive

echo ""
echo "===================================================="
echo " 部署完成: https://$DOMAIN"
echo " 健康检查:"
echo "   curl -I https://$DOMAIN"
echo "   docker compose ps"
echo "===================================================="
