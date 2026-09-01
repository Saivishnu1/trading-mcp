import contextlib
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from src.telegram_admin.config import ALLOWED_VARIABLES

logger = logging.getLogger(__name__)

class EnvVerificationError(Exception):
    """Exception raised when dotenv update verification fails."""
    pass

def read_env(file_path: Path) -> dict[str, str]:
    """Reads a dotenv file and returns a dictionary of keys and values.

    Removes surrounding single/double quotes from values if present.
    """
    if not file_path.exists():
        logger.warning("Dotenv file does not exist at %s", file_path)
        return {}

    variables = {}
    try:
        content = file_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, val = stripped.split("=", 1)
            key_clean = key.strip()
            val_clean = val.strip()

            # Strip quotes if they enclose the value
            if len(val_clean) >= 2 and (
                (val_clean.startswith('"') and val_clean.endswith('"')) or
                (val_clean.startswith("'") and val_clean.endswith("'"))
            ):
                val_clean = val_clean[1:-1]

            variables[key_clean] = val_clean
    except Exception as exc:
        logger.error("Error reading dotenv file %s: %s", file_path, exc, exc_info=True)

    return variables

@contextlib.contextmanager
def dotenv_lock(file_path: Path):
    """Acquires an exclusive lock on a separate lock file to prevent race conditions."""
    if os.name == 'nt':
        lock_path = Path(tempfile.gettempdir()) / "zerodha-mcp-env.lock"
    else:
        lock_path = Path("/var/tmp/zerodha-mcp-env.lock")

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback to system temp directory if /var/tmp is unavailable or not writable
        lock_path = Path(tempfile.gettempdir()) / "zerodha-mcp-env.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Open the lock file in append mode (standard practice for locks)
    f = open(lock_path, "a", encoding="utf-8")
    fd = f.fileno()
    locked = False
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        except ImportError:
            try:
                import msvcrt
                # Seek to start
                os.lseek(fd, 0, os.SEEK_SET)
                # LK_LOCK locks the file. Retries automatically for up to 10 seconds.
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                locked = True
            except (ImportError, OSError):
                # Fallback: if locking is not supported, log warning and continue
                logger.warning("File locking not supported on this platform/configuration.")

        yield

    finally:
        if locked:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            except ImportError:
                try:
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except (ImportError, OSError):
                    pass
        f.close()

def update_variable(file_path: Path, key: str, value: str) -> None:
    """Updates a single variable in the dotenv file atomically and verifies correctness.

    Enforces that the key is whitelisted in ALLOWED_VARIABLES.
    Locks the file during updates.
    Detects duplicate variable definitions and raises EnvVerificationError.
    Preserves formatting (spaces around =).
    Creates a backup copy of the file at .env.bak before modifying it.
    Verifies that only the requested variable was updated to the new value.
    If verification fails, restores the backup.
    """
    if key not in ALLOWED_VARIABLES:
        raise ValueError(f"Variable '{key}' is not whitelisted for modification.")

    bak_path = file_path.with_suffix(".env.bak")

    with dotenv_lock(file_path):
        # 1. Read values of all allowed variables before modification to check for corruption later
        before_vars = read_env(file_path)

        try:
            # Create directories if they do not exist
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # 2. Create backup copy (.env.bak) if the file exists
            if file_path.exists():
                try:
                    shutil.copy2(file_path, bak_path)
                    logger.info("Created backup of dotenv file at %s", bak_path)
                except Exception as backup_exc:
                    logger.warning("Could not create backup file at %s: %s", bak_path, backup_exc)

            # Read existing lines if file exists
            if file_path.exists():
                lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
            else:
                lines = []

            # Detect duplicates of the target key
            matches = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in line:
                    continue

                parts = line.split("=", 1)
                line_key = parts[0].strip()
                if line_key == key:
                    matches.append(i)

            if len(matches) > 1:
                raise EnvVerificationError(f"Duplicate variable '{key}' found in dotenv file.")

            updated = False

            if len(matches) == 1:
                i = matches[0]
                line = lines[i]
                parts = line.split("=", 1)
                left = parts[0]
                right = parts[1]

                # Extract spaces/tabs immediately after '='
                space_match = re.match(r"^([ \t]*)", right)
                space_after = space_match.group(1) if space_match else ""

                # Determine original line ending
                ending = "\n"
                if line.endswith("\r\n"):
                    ending = "\r\n"
                elif line.endswith("\r"):
                    ending = "\r"

                # Replace the value while keeping LHS formatting and spacing after =
                lines[i] = f"{left}={space_after}{value}{ending}"
                updated = True
                logger.info("Updated existing variable %s in %s", key, file_path)

            if not updated:
                # Append new variable to the end
                # Ensure there is a trailing newline in the file before we append
                if lines and not lines[-1].endswith(("\n", "\r")):
                    lines[-1] = lines[-1] + "\n"
                lines.append(f"{key}={value}\n")
                logger.info("Appended new variable %s to %s", key, file_path)

            # 3. Write atomically using a temporary file in the same directory
            temp_dir = file_path.parent
            with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write("".join(lines))
                temp_file.flush()
                os.fsync(temp_file.fileno())

            # Atomically replace target file
            try:
                temp_path.replace(file_path)
            except Exception:
                # Cleanup temp file on failure
                if temp_path.exists():
                    temp_path.unlink()
                raise

            # 4. Verification Check
            # Re-read the file to check modifications
            after_vars = read_env(file_path)

            # Verify the requested variable has the new value
            # Strip quotes from target value if any, to match read_env behavior
            target_value_clean = value.strip()
            if len(target_value_clean) >= 2 and (
                (target_value_clean.startswith('"') and target_value_clean.endswith('"')) or
                (target_value_clean.startswith("'") and target_value_clean.endswith("'"))
            ):
                target_value_clean = target_value_clean[1:-1]

            if after_vars.get(key) != target_value_clean:
                raise EnvVerificationError(
                    f"Verification failed: expected {key} to be '{target_value_clean}', but got '{after_vars.get(key)}'"
                )

            # Verify that no other whitelisted variable changed
            for var in ALLOWED_VARIABLES:
                if var == key:
                    continue
                if before_vars.get(var) != after_vars.get(var):
                    raise EnvVerificationError(
                        f"Verification failed: variable '{var}' was mutated from '{before_vars.get(var)}' to '{after_vars.get(var)}' during save."
                    )

            logger.info("Atomic update verified successfully for key: %s", key)

        except Exception as exc:
            logger.error("Error updating dotenv file %s for key %s: %s", file_path, key, exc, exc_info=True)

            # 5. Restore backup if modification failed or verification failed
            if bak_path.exists():
                try:
                    bak_path.replace(file_path)
                    logger.warning("Restored dotenv file from backup %s due to update error/failed verification", bak_path)
                except Exception as restore_exc:
                    logger.critical("Failed to restore dotenv file from backup %s: %s", bak_path, restore_exc)

            raise
