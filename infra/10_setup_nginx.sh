#!/usr/bin/env bash
# Install Nginx + Certbot and configure HTTPS reverse proxy for Zerodha MCP.
# Run as: sudo bash infra/10_setup_nginx.sh
#
# Uses sslip.io for a free wildcard-friendly domain:
#   https://140-245-202-88.sslip.io
set -euo pipefail

PUBLIC_IP="${1:-}"
if [ -z "${PUBLIC_IP}" ]; then
  # Auto-detect public IP
  PUBLIC_IP=$(curl -sf https://api.ipify.org || curl -sf https://ifconfig.me || echo "")
fi
if [ -z "${PUBLIC_IP}" ]; then
  echo "ERROR: Could not detect public IP. Pass it as argument:"
  echo "  sudo bash infra/10_setup_nginx.sh 140.245.202.88"
  exit 1
fi

# sslip.io domain: dots become dashes
DOMAIN="${PUBLIC_IP//./-}.sslip.io"
APP_PORT=8000
EMAIL="saivishnu1652@gmail.com"

echo "============================================================"
echo " Nginx + HTTPS setup for Zerodha MCP"
echo " Domain : ${DOMAIN}"
echo " Proxies: http://127.0.0.1:${APP_PORT}"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# 1. Install Nginx + Certbot
# ---------------------------------------------------------------------------
echo "==> Installing Nginx and Certbot..."
apt update -q
apt install -y nginx certbot python3-certbot-nginx

# ---------------------------------------------------------------------------
# 2. Open firewall ports 80 + 443
# OCI ARM instances block ports via iptables even when Security List allows them.
# ---------------------------------------------------------------------------
echo "==> Opening ports 80 and 443 in iptables..."
iptables -I INPUT -p tcp --dport 80  -j ACCEPT
iptables -I INPUT -p tcp --dport 443 -j ACCEPT

# Persist rules across reboots
if ! dpkg -l iptables-persistent &>/dev/null; then
  # Pre-answer the save prompt so it's non-interactive
  echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
  echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
  apt install -y iptables-persistent
fi
netfilter-persistent save
echo "  iptables rules saved."

if command -v ufw &>/dev/null; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

# ---------------------------------------------------------------------------
# 3. Write Nginx config (HTTP first — certbot will upgrade to HTTPS)
# ---------------------------------------------------------------------------
echo "==> Writing Nginx config..."
cat > /etc/nginx/sites-available/zerodha-mcp << NGINXEOF
server {
    listen 80;
    server_name ${DOMAIN};

    # SSE and streaming HTTP need long timeouts
    proxy_read_timeout 3600;
    proxy_send_timeout 3600;
    proxy_connect_timeout 10;

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;

        # Required for SSE (Server-Sent Events)
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/zerodha-mcp /etc/nginx/sites-enabled/zerodha-mcp
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx
echo "  Nginx configured."

# ---------------------------------------------------------------------------
# 4. Get SSL cert from Let's Encrypt
# ---------------------------------------------------------------------------
echo ""
echo "==> Obtaining SSL certificate for ${DOMAIN}..."
certbot --nginx \
  --non-interactive \
  --agree-tos \
  --email "${EMAIL}" \
  --domains "${DOMAIN}" \
  --redirect

# ---------------------------------------------------------------------------
# 5. Enable certbot auto-renewal timer
# ---------------------------------------------------------------------------
systemctl enable certbot.timer 2>/dev/null || true
systemctl start certbot.timer 2>/dev/null || true

# ---------------------------------------------------------------------------
# 6. Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " HTTPS setup complete."
echo ""
echo " MCP URL  : https://${DOMAIN}/mcp"
echo " SSE URL  : https://${DOMAIN}/sse"
echo " Health   : https://${DOMAIN}/health"
echo ""
echo " Add to Claude Desktop (~/.claude/claude_desktop_config.json):"
echo ' {'
echo '   "mcpServers": {'
echo '     "zerodha": {'
echo '       "type": "http",'
echo "       \"url\": \"https://${DOMAIN}/mcp\""
echo '     }'
echo '   }'
echo ' }'
echo ""
echo " Cert renewal: sudo certbot renew --dry-run"
echo "============================================================"
