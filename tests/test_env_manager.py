from pathlib import Path

import pytest

from src.telegram_admin.env_manager import EnvVerificationError, read_env, update_variable


def test_read_env_parsing(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KEY1=value1\n"
        "  KEY2 = \"value2\"  \n"
        "KEY3 = 'value3'\n"
        "# This is a comment\n"
        "\n"
        "KEY4=value=with=equals\n",
        encoding="utf-8"
    )

    parsed = read_env(env_file)
    assert parsed == {
        "KEY1": "value1",
        "KEY2": "value2",
        "KEY3": "value3",
        "KEY4": "value=with=equals",
    }

def test_update_non_existent(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("src.telegram_admin.env_manager.ALLOWED_VARIABLES", ["KEY1"])

    update_variable(env_file, "KEY1", "new_value")

    parsed = read_env(env_file)
    assert parsed.get("KEY1") == "new_value"

    content = env_file.read_text(encoding="utf-8")
    assert content.endswith("KEY1=new_value\n")

def test_update_existing_and_preserve_spacing(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KEY1   =   old_value\n"
        "KEY2=value2\n",
        encoding="utf-8"
    )

    monkeypatch.setattr("src.telegram_admin.env_manager.ALLOWED_VARIABLES", ["KEY1", "KEY2"])

    update_variable(env_file, "KEY1", "new_value")

    parsed = read_env(env_file)
    assert parsed.get("KEY1") == "new_value"
    assert parsed.get("KEY2") == "value2"

    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "KEY1   =   new_value"
    assert lines[1] == "KEY2=value2"

def test_update_not_allowed_throws_value_error(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("src.telegram_admin.env_manager.ALLOWED_VARIABLES", ["KEY1"])

    with pytest.raises(ValueError, match="is not whitelisted for modification"):
        update_variable(env_file, "DISALLOWED_KEY", "value")

def test_update_duplicate_keys_throws_error(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "KEY1=value1\n"
        "KEY1=value2\n",
        encoding="utf-8"
    )

    monkeypatch.setattr("src.telegram_admin.env_manager.ALLOWED_VARIABLES", ["KEY1"])

    with pytest.raises(EnvVerificationError, match="Duplicate variable 'KEY1' found"):
        update_variable(env_file, "KEY1", "new_value")

def test_atomic_restore_on_failed_verification(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    original_content = "KEY1=value1\nKEY2=value2\n"
    env_file.write_text(original_content, encoding="utf-8")

    monkeypatch.setattr("src.telegram_admin.env_manager.ALLOWED_VARIABLES", ["KEY1", "KEY2"])

    original_read_env = read_env
    calls = []
    def mock_read_env(path):
        res = original_read_env(path)
        calls.append(res)
        if len(calls) == 2:
            return {"KEY1": "wrong_value", "KEY2": "value2"}
        return res

    monkeypatch.setattr("src.telegram_admin.env_manager.read_env", mock_read_env)

    with pytest.raises(EnvVerificationError, match="Verification failed"):
        update_variable(env_file, "KEY1", "new_value")

    assert env_file.read_text(encoding="utf-8") == original_content
    bak_path = env_file.with_suffix(".env.bak")
    assert not bak_path.exists()
