# Zerodha MCP — Oracle VM Infrastructure

Production setup for Oracle Cloud VM.Standard.A1.Flex (ARM64, 24 GB RAM, Ubuntu 24.04).

## What lives here

```
infra/
│
├── PostgreSQL setup (run once, on a fresh VM)
│   ├── 01_install_postgres.sh       — PostgreSQL 17 from PGDG
│   ├── 02_configure_postgres.sh     — postgresql.conf + pg_hba.conf
│   ├── 03_create_db.sql             — database, user, schemas, extensions
│   ├── 04_firewall.sh               — ufw (22/80/443 only, no 5432)
│   ├── 05_backup.sh                 — pg_dump script (called by systemd timer)
│   ├── 06_restore.sh                — restore from a backup file
│   ├── 07_setup_systemd_timer.sh    — install daily backup timer
│   ├── 08_healthcheck.sh            — verify everything is healthy
│   └── deploy.sh                    — master runner for all of the above
│
├── Application deployment (run on every deploy)
│   ├── deploy_app.sh                — git pull + uv sync + migrate + restart
│   ├── migrate.sh                   — alembic upgrade head (double-locked)
│   └── rollback.sh                  — alembic downgrade + git reset + restart
│
├── Environment management (run once, before first deploy)
│   └── env/
│       └── setup_env.sh             — creates /etc/zerodha-mcp/.env interactively
│
├── Turso → PostgreSQL data migration (one-time, when ready)
│   └── turso_migration/
│       ├── 01_export_turso.sh       — export trades + rec_log from Turso to JSON
│       ├── 02_stage_to_postgres.sh  — load JSON into migration.* staging tables
│       └── 03_promote_to_production.sh — INSERT staging → live tables, validate
│
└── systemd/
    ├── backup_postgres.service      — runs 05_backup.sh
    ├── backup_postgres.timer        — daily at 02:00 IST
    └── zerodha-mcp.service          — the application service
```

---

## Part 1 — PostgreSQL Setup (one-time)

### Full automated setup

```bash
ssh ubuntu@<your-vm-ip>
git clone <your-repo-url> zerodha-mcp
cd zerodha-mcp/infra
sudo bash deploy.sh
```

Prompts for the `zerodha_app` DB password. Runs all 6 steps and ends with a health check.

### Individual steps (if something fails)

```bash
cd /home/ubuntu/zerodha-mcp/infra

sudo bash 01_install_postgres.sh
sudo bash 02_configure_postgres.sh
sudo -u postgres psql -v db_password='YOUR_PASSWORD' -f 03_create_db.sql
sudo bash 04_firewall.sh
sudo bash 07_setup_systemd_timer.sh
sudo bash 08_healthcheck.sh
```

### OCI Security List (manual — in OCI Console)

Networking → VCN → Security Lists → Ingress:

| Port | Protocol | Source    |
|------|----------|-----------|
| 22   | TCP      | 0.0.0.0/0 |
| 80   | TCP      | 0.0.0.0/0 |
| 443  | TCP      | 0.0.0.0/0 |

**Never add port 5432.**

---

## Part 2 — Environment Setup (one-time, before first deploy)

This creates `/etc/zerodha-mcp/.env` — the file that holds all production secrets.
It is owned `root:ubuntu`, mode `640`, and is **never committed to git**.

```bash
sudo bash /home/ubuntu/zerodha-mcp/infra/env/setup_env.sh
```

The script prompts for:
- DB password (must match the one set in Part 1)
- JWT secret (auto-generated, or paste your own)
- Zerodha credentials (user ID, password, TOTP secret)
- LLM API keys (Gemini, OpenAI)

Verify it loaded correctly:
```bash
sudo cat /etc/zerodha-mcp/.env
```

### Secret rotation

To rotate a secret (e.g., after a JWT leak):

```bash
sudo nano /etc/zerodha-mcp/.env   # update the value
sudo systemctl restart zerodha-mcp
sudo journalctl -u zerodha-mcp -n 20   # verify clean startup
```

The database password requires a PostgreSQL change too:
```bash
sudo -u postgres psql -c "ALTER USER zerodha_app WITH PASSWORD 'NEW_PASSWORD';"
# Then update DATABASE_URL in /etc/zerodha-mcp/.env
sudo systemctl restart zerodha-mcp
```

---

## Part 3 — First Application Deploy (one-time)

Installs the systemd service AND runs the first migration:

```bash
bash /home/ubuntu/zerodha-mcp/infra/deploy_app.sh --setup
```

This will:
1. Pull the latest code
2. `uv sync` — install dependencies
3. `alembic upgrade head` — create all tables in PostgreSQL
4. Install `zerodha-mcp.service` and start it

---

## Part 4 — Routine Deployments

Every subsequent deploy:

```bash
bash /home/ubuntu/zerodha-mcp/infra/deploy_app.sh
```

Flow:
```
git pull
  └── uv sync --frozen
        └── alembic upgrade head   ← if this fails, app is NOT restarted
              └── systemctl restart zerodha-mcp
```

The application **never starts with a stale schema**. If migration fails, the previous version keeps running.

---

## Part 5 — Alembic Migration Workflow

### Check current state

```bash
bash infra/migrate.sh --current
bash infra/migrate.sh --history
```

### Preview SQL without running it

```bash
bash infra/migrate.sh --dry-run
```

### Create a new migration

```bash
# After modifying a model in src/db/models.py:
uv run alembic revision --autogenerate -m "add_user_preferences_table"

# Review the generated file in migrations/versions/
# Then apply:
bash infra/migrate.sh
```

### Rollback one step

```bash
bash infra/rollback.sh --db-only       # rolls back DB schema only
bash infra/rollback.sh                 # rolls back DB + git HEAD~1
```

### Migration file naming

```
migrations/versions/
  0001_initial_schema.py            ← zerodha.trades, journal.recommendation_log,
                                       auth.sessions, auth.api_keys
  0002_migration_staging_tables.py  ← migration.trades, migration.recommendation_log
  0003_...py                        ← future application migrations
```

### Migration locking

`migrate.sh` uses two independent locks:

1. **`flock /var/lock/zerodha-mcp-migrate.lock`** — OS-level. Blocks a second shell invocation of this script before it even opens a DB connection.
2. **`pg_advisory_lock(987654321)`** — PostgreSQL session-level (in `migrations/env.py`). Blocks any process that reaches the DB concurrently — including direct `alembic` CLI calls. Released automatically on connection close, so it is safe against crashes and SIGKILL.

---

## Part 6 — Turso → PostgreSQL Data Migration

**Source of truth on Railway: Turso cloud SQLite**
**Tables to migrate: `trades` + `recommendation_log` only**
**Tables excluded: `sessions`, `api_keys` — ephemeral, regenerate on first login**

### Prerequisites

```bash
# Install Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash
turso auth login

# Verify TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are in /etc/zerodha-mcp/.env
# Verify alembic upgrade head has already been run (0001 + 0002 applied)
bash infra/migrate.sh --current   # should show 0002
```

### Step 1 — Export from Turso

```bash
bash infra/turso_migration/01_export_turso.sh
```

Writes to `infra/turso_migration/export/`:
- `trades.json` — all trade rows
- `recommendation_log.json` — all recommendation rows
- `export_meta.json` — counts and timestamp for validation

Sessions and api_keys are intentionally omitted.

### Step 2 — Stage into PostgreSQL

```bash
bash infra/turso_migration/02_stage_to_postgres.sh
```

Loads JSON into `migration.trades` and `migration.recommendation_log`.
Safe to re-run — truncates and reloads staging on each run.
Does NOT touch `zerodha.*` or `journal.*`.

Inspect staged data before continuing:
```bash
sudo -u postgres psql -d zerodha_mcp -c "SELECT COUNT(*) FROM migration.trades;"
sudo -u postgres psql -d zerodha_mcp -c "SELECT id, symbol, status FROM migration.trades LIMIT 5;"
sudo -u postgres psql -d zerodha_mcp -c "SELECT COUNT(*) FROM migration.recommendation_log;"
```

### Step 3 — Promote to production

```bash
# Dry run first — shows counts, makes no changes
bash infra/turso_migration/03_promote_to_production.sh --dry-run

# Live run — prompts for 'promote' before any INSERT
bash infra/turso_migration/03_promote_to_production.sh
```

Uses `INSERT ... ON CONFLICT (id) DO NOTHING` — safe to re-run.
Prompts to truncate staging tables after successful promotion.

### What survives vs. what starts fresh

| Data | Action |
|---|---|
| `trades` | Migrated from Turso |
| `recommendation_log` | Migrated from Turso |
| `sessions` | Start empty — regenerate on first login |
| `api_keys` | Start empty — regenerate on first login |

### After migration: verify end-to-end

```bash
sudo bash infra/08_healthcheck.sh

# Spot-check a known trade
sudo -u postgres psql -d zerodha_mcp \
  -c "SELECT id, symbol, status, pnl FROM zerodha.trades ORDER BY created_at DESC LIMIT 5;"

# Spot-check recommendation log
sudo -u postgres psql -d zerodha_mcp \
  -c "SELECT id, symbol, recommendation_type FROM journal.recommendation_log ORDER BY created_at DESC LIMIT 5;"
```

### After migration: switch the app off Railway

1. Update `DATABASE_URL` in `/etc/zerodha-mcp/.env` to point to Oracle VM PostgreSQL
2. Update `src/journal/db.py` to prefer `DATABASE_URL` over `TURSO_DATABASE_URL` (future phase)
3. Restart: `sudo systemctl restart zerodha-mcp`
4. Monitor: `sudo journalctl -u zerodha-mcp -f`
5. Decommission Railway service once verified stable

---

## Monitoring

```bash
# Service health
sudo systemctl status zerodha-mcp
sudo systemctl status postgresql
sudo systemctl list-timers backup_postgres.timer

# Live application logs
sudo journalctl -u zerodha-mcp -f

# Last backup log
sudo journalctl -u backup_postgres.service -n 30

# Database health
sudo bash /home/ubuntu/zerodha-mcp/infra/08_healthcheck.sh

# Current migration state
bash /home/ubuntu/zerodha-mcp/infra/migrate.sh --current

# Active DB connections
sudo -u postgres psql -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"

# Slow queries (pg_stat_statements)
sudo -u postgres psql -d zerodha_mcp -c \
  "SELECT left(query,80), calls, round(mean_exec_time::numeric,1) ms \
   FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;"
```

---

## Data persistence guarantee

| Event | Database | Application |
|---|---|---|
| `git pull` | Safe | Restarted by deploy_app.sh |
| `docker compose down` | Safe | N/A (app runs natively) |
| VM reboot | Safe (systemd) | Restarts via systemd |
| Failed migration | Safe (rolled back) | Old version keeps running |
| App crash | Safe | systemd restarts it |

Data lives in `/var/lib/postgresql/17/main/` — completely outside the application directory.

---

## PostgreSQL upgrade path (future)

```bash
sudo apt install -y postgresql-18
sudo pg_upgradecluster 17 main
# verify, then:
sudo pg_dropcluster 17 main --stop
sudo systemctl restart postgresql
```
