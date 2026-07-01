#!/usr/bin/env bash
# Creates or updates /etc/zerodha-mcp/.env interactively.
# Idempotent — re-running pre-fills all prompts from the existing file.
# Press Enter at any prompt to keep the current value.
#
# Run as: sudo bash infra/env/setup_env.sh
set -euo pipefail

ENV_DIR="/etc/zerodha-mcp"
ENV_FILE="${ENV_DIR}/.env"

echo "============================================================"
echo " Zerodha MCP — Environment Setup"
echo " File: ${ENV_FILE}"
echo "============================================================"
echo ""

mkdir -p "${ENV_DIR}"

# ---------------------------------------------------------------------------
# Load existing values as defaults (idempotent re-runs)
# ---------------------------------------------------------------------------
load_existing() {
  local key="$1"
  if [ -f "${ENV_FILE}" ]; then
    grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || true
  fi
}

# ---------------------------------------------------------------------------
# Prompt helpers — show current value, Enter keeps it
# ---------------------------------------------------------------------------
prompt_plain() {
  local var_name="$1"
  local prompt_text="$2"
  local current="$3"
  local value=""

  if [ -n "${current}" ]; then
    read -rp "${prompt_text} [${current}]: " value
    value="${value:-${current}}"
  else
    read -rp "${prompt_text}: " value
  fi
  printf -v "${var_name}" '%s' "${value}"
}

prompt_secret() {
  local var_name="$1"
  local prompt_text="$2"
  local current="$3"
  local value=""

  if [ -n "${current}" ]; then
    read -rsp "${prompt_text} [keep current — Enter to keep]: " value
    echo ""
    value="${value:-${current}}"
  else
    while [ -z "${value}" ]; do
      read -rsp "${prompt_text}: " value
      echo ""
      if [ -z "${value}" ]; then
        echo "  (cannot be empty — try again)"
      fi
    done
  fi
  printf -v "${var_name}" '%s' "${value}"
}

# ---------------------------------------------------------------------------
# Read existing values
# ---------------------------------------------------------------------------
CUR_DB_USER=$(load_existing "DATABASE_URL" | sed 's|.*//\([^:]*\):.*|\1|')
CUR_DB_NAME=$(load_existing "DATABASE_URL" | sed 's|.*/\([^?]*\).*|\1|')
CUR_DB_PASS=$(load_existing "DATABASE_URL" | sed 's|.*://[^:]*:\([^@]*\)@.*|\1|')
CUR_JWT=$(load_existing "JWT_SECRET")
CUR_ZID=$(load_existing "ZERODHA_USER_ID")
CUR_ZPASS=$(load_existing "ZERODHA_PASSWORD")
CUR_TOTP=$(load_existing "ZERODHA_TOTP_SECRET")
CUR_GEMINI=$(load_existing "GEMINI_API_KEY")
CUR_OPENAI=$(load_existing "OPENAI_API_KEY")
CUR_TURSO_URL=$(load_existing "TURSO_DATABASE_URL")
CUR_TURSO_TOKEN=$(load_existing "TURSO_AUTH_TOKEN")
CUR_REDIS=$(load_existing "REDIS_URL")
CUR_BROKER=$(load_existing "BROKER_BACKEND")
CUR_BROKER="${CUR_BROKER:-zerodha_web}"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
echo "--- PostgreSQL (from DATABASE_URL) ---"
prompt_plain   DB_USER      "DB username"   "${CUR_DB_USER:-zerodha}"
prompt_plain   DB_NAME      "DB name"       "${CUR_DB_NAME:-zerodha_mcp}"
prompt_secret  DB_PASSWORD  "DB password"   "${CUR_DB_PASS}"
echo ""

echo "--- Security ---"
if [ -z "${CUR_JWT}" ]; then
  JWT_GENERATED=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  echo "  Generated JWT_SECRET: ${JWT_GENERATED}"
  read -rp "  Use generated? (yes/no) [yes]: " USE_GEN
  if [ "${USE_GEN:-yes}" = "no" ]; then
    prompt_secret JWT_SECRET "Enter JWT_SECRET" ""
  else
    JWT_SECRET="${JWT_GENERATED}"
  fi
else
  prompt_secret JWT_SECRET "JWT_SECRET" "${CUR_JWT}"
fi
echo ""

echo "--- Zerodha Credentials ---"
prompt_plain   ZERODHA_USER_ID     "Zerodha client ID"    "${CUR_ZID}"
prompt_secret  ZERODHA_PASSWORD    "Zerodha password"     "${CUR_ZPASS}"
prompt_plain   ZERODHA_TOTP_SECRET "TOTP secret"          "${CUR_TOTP}"
echo ""

echo "--- Broker Backend ---"
prompt_plain   BROKER_BACKEND "Backend (zerodha_web / jugaad)" "${CUR_BROKER}"
echo ""

echo "--- LLM API Keys ---"
prompt_plain   GEMINI_API_KEY  "Gemini API key"  "${CUR_GEMINI}"
prompt_plain   OPENAI_API_KEY  "OpenAI API key"  "${CUR_OPENAI}"
echo ""

echo "--- Turso ---"
prompt_plain   TURSO_DATABASE_URL  "TURSO_DATABASE_URL"  "${CUR_TURSO_URL}"
prompt_secret  TURSO_AUTH_TOKEN    "TURSO_AUTH_TOKEN"    "${CUR_TURSO_TOKEN}"
echo ""

echo "--- Optional ---"
prompt_plain   REDIS_URL  "Redis URL (blank to skip)"  "${CUR_REDIS}"
echo ""

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
[ -f "${ENV_FILE}" ] && cp "${ENV_FILE}" "${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"

DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"

cat > "${ENV_FILE}" << ENVEOF
# =============================================================================
# Zerodha MCP — Production Environment
# Oracle VM.Standard.A1.Flex
# Updated: $(date '+%Y-%m-%d %H:%M:%S IST')
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
BROKER_BACKEND=${BROKER_BACKEND}
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

chmod 640 "${ENV_FILE}"
chown root:ubuntu "${ENV_FILE}"

echo "Written: ${ENV_FILE}  (backup saved)"
echo "Verify:  sudo cat ${ENV_FILE}"
