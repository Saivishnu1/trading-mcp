import logging
import subprocess

from src.telegram_admin.config import RESTART_SERVICES, SERVICE_NAME

logger = logging.getLogger(__name__)

def restart_service() -> None:
    """Restarts every service in RESTART_SERVICES (zerodha-mcp and
    zerodha-monitor) — both read the same /etc/zerodha-mcp/.env file, so an
    env var update (e.g. INDSTOCKS_TOKEN) must reach both processes or the
    monitor silently keeps running on the stale value indefinitely.

    Uses sudo to execute systemctl restart. Raises on the first failure —
    if zerodha-mcp restarts but zerodha-monitor's restart command fails,
    the exception surfaces so the caller doesn't report a false success.
    """
    for service in RESTART_SERVICES:
        logger.info("Restarting service: %s", service)
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", service],
                check=True,
                text=True,
                capture_output=True
            )
            logger.info("Restart command executed successfully for %s", service)
        except subprocess.CalledProcessError as exc:
            logger.error("Failed to restart service %s: %s", service, exc.stderr)
            raise

def _is_active(service: str) -> bool:
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "is-active", service],
            check=True,
            text=True,
            capture_output=True
        )
        return result.stdout.strip() == "active"
    except subprocess.CalledProcessError as exc:
        # systemctl is-active returns non-zero exit codes if the service is not active
        if exc.stdout and exc.stdout.strip() == "active":
            return True
        logger.info("Service %s is inactive. Exit code: %d", service, exc.returncode)
        return False

def is_service_active() -> bool:
    """Checks if the primary service (SERVICE_NAME) is currently active.

    Uses sudo systemctl is-active.
    """
    return _is_active(SERVICE_NAME)

def are_restart_services_active() -> dict[str, bool]:
    """Checks active status for every service touched by restart_service()
    (zerodha-mcp and zerodha-monitor) — used after a restart so a caller
    doesn't report success when only one of the two came back up."""
    return {service: _is_active(service) for service in RESTART_SERVICES}

def get_service_status() -> dict[str, str]:
    """Retrieves service status and parses key fields.

    Returns a dict with:
    - active: Active state string
    - pid: Process ID
    - uptime: Service uptime
    - memory: Memory usage
    - last_log: The latest log line shown in systemctl status
    """
    res = {
        "active": "inactive",
        "pid": "N/A",
        "uptime": "N/A",
        "memory": "N/A",
        "last_log": "N/A"
    }

    try:
        # systemctl status might return non-zero exit code if inactive/failed,
        # so we handle CalledProcessError as a normal source of stdout.
        result = subprocess.run(
            ["sudo", "systemctl", "status", SERVICE_NAME, "--no-pager"],
            check=True,
            text=True,
            capture_output=True
        )
        stdout = result.stdout
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout or exc.stderr or ""

    lines = stdout.splitlines()
    log_lines = []

    # Header prefixes to identify non-log metadata lines in systemctl status
    header_prefixes = (
        "Loaded:", "Active:", "Main PID:", "Tasks:", "Memory:", "CPU:",
        "CGroup:", "Docs:", "Drop-In:", "Status:", "Process:", "●"
    )

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        if "Active:" in line_stripped:
            res["active"] = line_stripped.split("Active:", 1)[1].strip()
            # Extract uptime (the part after the semicolon, e.g. "since Mon...; 10h ago")
            if ";" in res["active"]:
                parts = res["active"].split(";", 1)
                res["uptime"] = parts[1].strip()
        elif "Main PID:" in line_stripped:
            res["pid"] = line_stripped.split("Main PID:", 1)[1].strip()
        elif "Memory:" in line_stripped:
            res["memory"] = line_stripped.split("Memory:", 1)[1].strip()
        elif not any(line_stripped.startswith(p) for p in header_prefixes):
            log_lines.append(line_stripped)

    if log_lines:
        res["last_log"] = log_lines[-1]

    return res

def get_service_logs(n: int = 20) -> str:
    """Fetches the last n journal logs for the service.

    Uses sudo journalctl.
    """
    try:
        result = subprocess.run(
            ["sudo", "journalctl", "-u", SERVICE_NAME, "-n", str(n), "--no-pager"],
            check=True,
            text=True,
            capture_output=True
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to fetch logs for %s: %s", SERVICE_NAME, exc.stderr)
        raise
