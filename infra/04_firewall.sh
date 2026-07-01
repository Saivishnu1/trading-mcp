#!/usr/bin/env bash
# Configures ufw firewall: SSH + HTTP + HTTPS only. Port 5432 is never opened.
# Run as: sudo bash 04_firewall.sh
#
# After this script, also configure OCI Security List in the console:
#   Networking > Virtual Cloud Networks > your VCN > Security Lists
#   Ingress rules: 22/tcp, 80/tcp, 443/tcp  (source 0.0.0.0/0)
#   Do NOT add 5432.
set -euo pipefail

echo "==> Enabling ufw..."
ufw --force enable

echo "==> Allowing SSH (critical — do not skip)..."
ufw allow OpenSSH

echo "==> Allowing HTTP and HTTPS..."
ufw allow 80/tcp
ufw allow 443/tcp

echo ""
echo "==> Current firewall status:"
ufw status verbose

echo ""
echo "Port 5432 is intentionally NOT open."
echo "PostgreSQL is accessible only from localhost (127.0.0.1) and Unix sockets."
echo ""
echo "Next step: configure OCI Security List in the OCI Console to match."
