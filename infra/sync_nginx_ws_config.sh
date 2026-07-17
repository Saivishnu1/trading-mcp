#!/usr/bin/env bash
# Idempotently ensure the /ws/prices WebSocket location block exists in the
# nginx config — safe to run on EVERY deploy, unlike 10_setup_nginx.sh.
#
# Why this exists (2026-07-17): the original nginx config's only location
# block hardcodes `proxy_set_header Connection '';` (needed for SSE at
# /sse), which silently strips the Upgrade/Connection headers for every
# proxied path — including /ws/prices, the browser-facing live-price
# WebSocket. Every connection attempt arrived at uvicorn as a plain GET
# instead of a WS upgrade, which the app correctly 404s (only a
# websocket-scope handler exists for that path, no HTTP route).
#
# Why this is a SEPARATE, targeted script rather than just re-running
# 10_setup_nginx.sh on every deploy: certbot's --nginx plugin edits this
# same config file in place (adds the `listen 443 ssl` server block and its
# own managed-by-Certbot markers) the first time it runs. Blindly
# regenerating the whole file from scratch on every deploy — as
# 10_setup_nginx.sh does — would silently destroy certbot's SSL block and
# take HTTPS down. This script only ever inserts the missing location
# block; every other line, including anything certbot has added, is left
# completely untouched. No-op (exits 0 immediately) once the block exists.
#
# Usage: sudo bash infra/sync_nginx_ws_config.sh
set -euo pipefail

NGINX_CONF="/etc/nginx/sites-available/zerodha-mcp"
APP_PORT="${APP_PORT:-8000}"

if [ ! -f "${NGINX_CONF}" ]; then
  echo "  nginx config not found at ${NGINX_CONF} — skipping "
  echo "  (run infra/10_setup_nginx.sh first for a fresh provision)."
  exit 0
fi

if grep -q "location /ws/prices" "${NGINX_CONF}"; then
  echo "  /ws/prices location block already present in ${NGINX_CONF} — nothing to do."
  exit 0
fi

echo "==> Adding missing /ws/prices WebSocket location block to nginx config..."

APP_PORT="${APP_PORT}" python3 - "${NGINX_CONF}" << 'PYEOF'
import os
import re
import sys

path = sys.argv[1]
app_port = os.environ["APP_PORT"]

with open(path) as f:
    content = f.read()

if "location /ws/prices" in content:
    sys.exit(0)

def make_block(indent: str) -> str:
    return (
        f"{indent}location /ws/prices {{\n"
        f"{indent}    proxy_pass http://127.0.0.1:{app_port};\n"
        f"{indent}    proxy_http_version 1.1;\n"
        f"{indent}    proxy_set_header Upgrade $http_upgrade;\n"
        f'{indent}    proxy_set_header Connection "upgrade";\n'
        f"{indent}\n"
        f"{indent}    proxy_set_header Host $host;\n"
        f"{indent}    proxy_set_header X-Real-IP $remote_addr;\n"
        f"{indent}    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        f"{indent}    proxy_set_header X-Forwarded-Proto $scheme;\n"
        f"{indent}}}\n\n"
    )

# Insert directly before EVERY "location / {" line (matching its own
# indentation) — certbot's --nginx plugin typically adds a second server
# block for `listen 443 ssl` with its own location / {, so there can be
# more than one to cover. nginx picks the longest matching prefix location
# automatically, so each new block takes precedence for /ws/prices within
# its own server block without touching the generic one.
matches = list(re.finditer(r"^( *)location / \{", content, re.MULTILINE))
if not matches:
    print("Could not find any 'location / {' to anchor the insert — leaving file untouched.", file=sys.stderr)
    sys.exit(1)

# Insert from the last match backwards so earlier offsets stay valid.
for match in reversed(matches):
    indent = match.group(1)
    insert_at = match.start()
    content = content[:insert_at] + make_block(indent) + content[insert_at:]

with open(path, "w") as f:
    f.write(content)
PYEOF

nginx -t
systemctl reload nginx
echo "  /ws/prices location block added and nginx reloaded."
