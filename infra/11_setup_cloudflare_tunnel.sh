#!/usr/bin/env bash
# Cloudflare Quick Tunnel — free, no domain, no Cloudflare account needed.
# Run as: sudo bash infra/11_setup_cloudflare_tunnel.sh
#
# Gives the app a real HTTPS URL (https://<random-words>.trycloudflare.com)
# with a valid cert, proxied through Cloudflare, WITHOUT exposing the VM's
# public IP or opening inbound ports 80/443 -- cloudflared makes an
# OUTBOUND connection to Cloudflare's edge and Cloudflare routes traffic
# back over that tunnel, so nothing needs to accept inbound connections at
# all (this can safely coexist with the existing nginx+certbot setup from
# 10_setup_nginx.sh; neither depends on the other, and you can point MCP
# clients at either URL).
#
# TRADE-OFF, stated up front: a Quick Tunnel's URL is regenerated every
# time cloudflared restarts -- it is NOT a stable URL for a README link or
# a saved MCP client config. If you need a stable URL, that requires a
# named tunnel + a real domain added to a Cloudflare account (DNS
# propagation alone can take hours) -- out of scope for "fast," see
# infra/README.md for that path when you have a domain ready.
set -euo pipefail

APP_PORT=8000
CLOUDFLARED_BIN=/usr/local/bin/cloudflared
LOG_FILE=/var/log/cloudflared.log

echo "============================================================"
echo " Cloudflare Quick Tunnel setup for Zerodha MCP"
echo " Proxies: http://127.0.0.1:${APP_PORT}"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# 1. Install cloudflared (ARM64 binary -- Oracle VM.Standard.A1.Flex, matching
#    every other infra/ script's target per infra/README.md)
# ---------------------------------------------------------------------------
if [ -x "${CLOUDFLARED_BIN}" ]; then
  echo "==> cloudflared already installed: $(${CLOUDFLARED_BIN} --version)"
else
  echo "==> Installing cloudflared (arm64)..."
  ARCH="$(uname -m)"
  case "${ARCH}" in
    aarch64|arm64) CF_ARCH="arm64" ;;
    x86_64)        CF_ARCH="amd64" ;;
    *) echo "ERROR: unrecognized architecture ${ARCH}"; exit 1 ;;
  esac
  curl -sfL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
    -o "${CLOUDFLARED_BIN}"
  chmod +x "${CLOUDFLARED_BIN}"
  echo "  Installed: $(${CLOUDFLARED_BIN} --version)"
fi

# ---------------------------------------------------------------------------
# 2. Install the systemd unit (infra/systemd/cloudflared-tunnel.service)
# ---------------------------------------------------------------------------
echo ""
echo "==> Installing systemd unit..."
cp "$(dirname "$0")/systemd/cloudflared-tunnel.service" /etc/systemd/system/cloudflared-tunnel.service
systemctl daemon-reload
systemctl enable cloudflared-tunnel
systemctl restart cloudflared-tunnel

# ---------------------------------------------------------------------------
# 3. Wait for the assigned *.trycloudflare.com URL to appear in the log,
#    then print it -- cloudflared logs it to stderr on startup, which
#    systemd captures to journald; also mirrored to LOG_FILE for
#    infra/print_tunnel_url.sh to re-read after this script exits.
# ---------------------------------------------------------------------------
echo ""
echo "==> Waiting for tunnel URL (up to 30s)..."
TUNNEL_URL=""
for _ in $(seq 1 30); do
  TUNNEL_URL=$(journalctl -u cloudflared-tunnel --no-pager -n 200 2>/dev/null \
    | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)
  if [ -n "${TUNNEL_URL}" ]; then break; fi
  sleep 1
done

echo ""
echo "============================================================"
if [ -n "${TUNNEL_URL}" ]; then
  echo " Tunnel is live."
  echo ""
  echo " MCP URL  : ${TUNNEL_URL}/mcp"
  echo " SSE URL  : ${TUNNEL_URL}/sse"
  echo " Health   : ${TUNNEL_URL}/health"
  echo ""
  echo " Add to Claude Desktop (~/.claude/claude_desktop_config.json):"
  echo ' {'
  echo '   "mcpServers": {'
  echo '     "zerodha": {'
  echo '       "type": "http",'
  echo "       \"url\": \"${TUNNEL_URL}/mcp\""
  echo '     }'
  echo '   }'
  echo ' }'
else
  echo " Could not read the URL automatically -- check manually:"
  echo "   journalctl -u cloudflared-tunnel -f"
fi
echo ""
echo " REMINDER: this URL changes every time the tunnel restarts (VM"
echo " reboot, service restart, network blip triggering reconnect wtih a"
echo " new URL). Re-run infra/print_tunnel_url.sh anytime to get the"
echo " current one -- do not hardcode it anywhere long-lived."
echo "============================================================"
