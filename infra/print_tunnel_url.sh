#!/usr/bin/env bash
# Print the current Cloudflare Quick Tunnel URL, re-readable anytime after
# infra/11_setup_cloudflare_tunnel.sh has run. The URL changes on every
# cloudflared restart -- use this instead of remembering/hardcoding a URL.
# Run as: bash infra/print_tunnel_url.sh   (no sudo needed, only reads logs)
set -euo pipefail

URL=$(journalctl -u cloudflared-tunnel --no-pager -n 500 2>/dev/null \
  | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)

if [ -z "${URL}" ]; then
  echo "No tunnel URL found in recent logs. Is the service running?"
  echo "  systemctl status cloudflared-tunnel"
  echo "  journalctl -u cloudflared-tunnel -f"
  exit 1
fi

echo "Current tunnel URL: ${URL}"
echo ""
echo "  MCP URL  : ${URL}/mcp"
echo "  SSE URL  : ${URL}/sse"
echo "  Health   : ${URL}/health"
