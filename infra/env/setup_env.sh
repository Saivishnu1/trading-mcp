#!/usr/bin/env bash
# Creates /etc/zerodha-mcp/.env interactively on the Oracle VM.
# Run ONCE after cloning the repo: sudo bash infra/env/setup_env.sh
#
# What it does:
#   1. Creates /etc/zerodha-mcp/ directory
#   2. Copies .env.example as the template
#   3. Prompts for every secret value
#   4. Writes the completed file with correct permissions (640, root:ubuntu)
set -euo pipefail

ENV_DIR="/etc/zerodha-mcp"
ENV_FILE="${ENV_DIR}/.env"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "============================================================"
echo " Zerodha MCP — Production Environment Setup"
echo " Writing to: ${ENV_FILE}"
echo "============================================================"
echo ""

if [ -f "${ENV_FILE}" ]; then
  echo "WARNING: ${ENV_FILE} already exists."
  read -rp "Overwrite? (yes/no): " OVERWRITE
  if [ "${OVERWRITE}" != "yes" ]; then
    echo "Aborted. Existing file unchanged."
    exit 0
  fi
  cp "${ENV_FILE}" "${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
  echo "Backed up existing file."
fi

mkdir -p "${ENV_DIR}"

# ---------------------------------------------------------------------------
# Collect secrets interactively
# ---------------------------------------------------------------------------

prompt_secret() {
  local var_name="$1"
  local prompt_text="$2"
  local default="${3:-}"
  local value=""

  while [ -z "${value}" ]; do
    read -rsp "${prompt_text}: " value
    echo ""
    if [ -z "${value}" ] && [ -n "${default}" ]; then
      value="${default}"
    fi
    if [ -z "${value}" ]; then
      echo "  (cannot be empty — try again)"
    fi
  done
  printf -v "${var_name}" '%s' "${value}"
}

prompt_plain() {
  local var_name="$1"
  local prompt_text="$2"
  local default="${3:-}"
  local value=""

  read -rp "${prompt_text} [${default}]: " value
  if [ -z "${value}" ]; then
    value="${default}"
  fi
  printf -v "${var_name}" '%s' "${value}"
}

echo "--- PostgreSQL ---"
prompt_plain   DB_USER         "DB username"                  "zerodha"
prompt_plain   DB_NAME         "DB name"                      "zerodha_mcp"
prompt_secret  DB_PASSWORD     "DB password"
echo ""

echo "--- Security ---"
JWT_SECRET_GENERATED=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo "  Generated JWT_SECRET: ${JWT_SECRET_GENERATED}"
read -rp "  Use generated secret? (yes/no) [yes]: " USE_GENERATED
if [ "${USE_GENERATED}" != "no" ]; then
  JWT_SECRET="${JWT_SECRET_GENERATED}"
else
  prompt_secret JWT_SECRET "Enter JWT_SECRET (min 32 chars hex)"
fi
echo ""

echo "--- Zerodha Credentials ---"
prompt_plain   ZERODHA_USER_ID     "Zerodha client ID"    ""
prompt_secret  ZERODHA_PASSWORD    "Zerodha password"
prompt_plain   ZERODHA_TOTP_SECRET "TOTP secret (leave blank if manual)" ""
echo ""

echo "--- LLM API Keys ---"
prompt_plain   GEMINI_API_KEY  "Gemini API key (or Enter to skip)"  ""
prompt_plain   OPENAI_API_KEY  "OpenAI API key (or Enter to skip)"  ""
echo ""

echo "--- Turso (source-of-truth SQLite on Railway — needed for data migration) ---"
prompt_plain   TURSO_DATABASE_URL  "TURSO_DATABASE_URL (libsql://...)" ""
prompt_secret  TURSO_AUTH_TOKEN    "TURSO_AUTH_TOKEN (JWT from turso db tokens create)"
echo ""

echo "--- Optional ---"
prompt_plain   REDIS_URL  "Redis URL (or Enter to skip)" ""
echo ""

# ---------------------------------------------------------------------------
# Write the file
# ---------------------------------------------------------------------------
DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"

cat > "${ENV_FILE}" << ENVEOF
# =============================================================================
# Zerodha MCP — Production Environment
# Oracle VM.Standard.A1.Flex
# Generated: $(date '+%Y-%m-%d %H:%M:%S IST')
# DO NOT COMMIT THIS FILE TO GIT.
# =============================================================================

ENVIRONMENT=production
DATABASE_URL=${DATABASE_URL}
DB_ECHO=0
JWT_SECRET=${JWT_SECRET}
GEMINI_API_KEY=${GEMINI_API_KEY}
OPENAI_API_KEY=${OPENAI_API_KEY}
ZERODHA_USER_ID=${ZERODHA_USER_ID}
ZERODHA_PASSWORD=${ZERODHA_PASSWORD}
ZERODHA_TOTP_SECRET=${ZERODHA_TOTP_SECRET}
BROKER_BACKEND=zerodha_web
SESSION_FILE=/var/lib/zerodha-mcp/.session.json
JOURNAL_DB=/var/lib/zerodha-mcp/journal.db
TURSO_DATABASE_URL=${TURSO_DATABASE_URL}
TURSO_AUTH_TOKEN=${TURSO_AUTH_TOKEN}
REDIS_URL=${REDIS_URL}
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=INFO
DEV_BYPASS_AUTH=false
JUGAAD_USE_ENV_CREDENTIALS=false
ENVEOF

# Secure permissions: readable only by root and the ubuntu service user
chmod 640 "${ENV_FILE}"
chown root:ubuntu "${ENV_FILE}"

echo ""
echo "Written: ${ENV_FILE}"
echo "Permissions: 640 (root:ubuntu)"
echo ""
echo "Verify with: sudo cat ${ENV_FILE}"
echo "Load test:   sudo systemctl show zerodha-mcp | grep -i env"
