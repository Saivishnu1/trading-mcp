#!/usr/bin/env bash
# Installs PostgreSQL 17 from the official PGDG apt repository.
# Run as: sudo bash 01_install_postgres.sh
set -euo pipefail

echo "==> [1/4] Updating system packages..."
apt update
apt upgrade -y
apt install -y curl ca-certificates gnupg lsb-release

echo "==> [2/4] Adding PostgreSQL 17 PGDG repository..."
install -d /usr/share/postgresql-common/pgdg

curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc

sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
  https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list'

apt update

echo "==> [3/4] Installing PostgreSQL 17..."
apt install -y postgresql-17 postgresql-client-17 postgresql-contrib-17

echo "==> [4/4] Enabling and starting PostgreSQL service..."
systemctl enable postgresql
systemctl start postgresql
systemctl status postgresql --no-pager

echo ""
echo "PostgreSQL 17 installed successfully."
psql --version
