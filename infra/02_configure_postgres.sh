#!/usr/bin/env bash
# Writes tuned postgresql.conf and pg_hba.conf for the Oracle VM (24 GB RAM, 4 OCPU).
# Run as: sudo bash 02_configure_postgres.sh
set -euo pipefail

PG_CONF="/etc/postgresql/17/main/postgresql.conf"
PG_HBA="/etc/postgresql/17/main/pg_hba.conf"

echo "==> Backing up original config files..."
cp "${PG_CONF}" "${PG_CONF}.bak.$(date +%Y%m%d_%H%M%S)"
cp "${PG_HBA}"  "${PG_HBA}.bak.$(date +%Y%m%d_%H%M%S)"

echo "==> Writing postgresql.conf..."
cat > "${PG_CONF}" << 'EOF'
# -----------------------------------------------------------------------------
# PostgreSQL 17 — Oracle VM.Standard.A1.Flex (4 OCPU, 24 GB RAM, ARM64)
# Mixed workload: PostgreSQL + FastAPI + Docker + Nginx on the same host.
# -----------------------------------------------------------------------------

# --- Connections ---
listen_addresses = 'localhost'
port = 5432
max_connections = 100

# --- Memory (leaves ~16 GB for application stack) ---
shared_buffers = 2GB
effective_cache_size = 8GB
work_mem = 16MB
maintenance_work_mem = 512MB
wal_buffers = 32MB

# --- Write Performance ---
checkpoint_completion_target = 0.9
wal_level = replica

# --- Extensions ---
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all

# --- Parallelism (4 OCPUs) ---
max_worker_processes = 4
max_parallel_workers_per_gather = 2
max_parallel_workers = 4

# --- Logging ---
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_rotation_age = 1d
log_rotation_size = 100MB
log_min_duration_statement = 1000
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '

# --- Autovacuum ---
autovacuum = on

# --- Timezone ---
timezone = 'Asia/Kolkata'
log_timezone = 'Asia/Kolkata'
EOF

echo "==> Writing pg_hba.conf..."
cat > "${PG_HBA}" << 'EOF'
# PostgreSQL Client Authentication Configuration
# Localhost and Unix socket only — port 5432 is never exposed to the internet.

# TYPE  DATABASE        USER            ADDRESS                 METHOD

# Unix socket — postgres superuser via peer auth (no password needed locally)
local   all             postgres                                peer

# Unix socket — all other users via md5
local   all             all                                     md5

# TCP localhost — FastAPI and Docker (--network=host) connections
host    all             all             127.0.0.1/32            scram-sha-256

# TCP IPv6 localhost
host    all             all             ::1/128                 scram-sha-256
EOF

echo "==> Restarting PostgreSQL to apply configuration..."
systemctl restart postgresql
systemctl status postgresql --no-pager

echo ""
echo "Configuration applied. Verify with:"
echo "  sudo -u postgres psql -c 'SHOW shared_buffers;'"
echo "  sudo -u postgres psql -c 'SHOW listen_addresses;'"
