import base64
import os

import pytest

from src.server import _resolve_user


def test_resolve_user_no_auth_header():
    scope = {"headers": []}
    assert _resolve_user(scope) is None

def test_resolve_user_invalid_header_format():
    # Header exists but is not bearer or basic
    scope = {"headers": [(b"authorization", b"CustomToken 12345")]}
    assert _resolve_user(scope) is None

def test_resolve_user_bearer_single_user_success(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret_key")
    monkeypatch.setattr("src.session_store.get_active_user_id", lambda: "USER123")

    scope = {"headers": [(b"authorization", b"Bearer secret_key")]}
    assert _resolve_user(scope) == "USER123"

def test_resolve_user_bearer_single_user_fallback_env(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret_key")
    monkeypatch.setenv("ZERODHA_USER_ID", "ENV_USER")
    monkeypatch.setattr("src.session_store.get_active_user_id", lambda: None)

    scope = {"headers": [(b"authorization", b"Bearer secret_key")]}
    assert _resolve_user(scope) == "ENV_USER"

def test_resolve_user_bearer_single_user_fallback_default(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret_key")
    if "ZERODHA_USER_ID" in os.environ:
        monkeypatch.delenv("ZERODHA_USER_ID")
    monkeypatch.setattr("src.session_store.get_active_user_id", lambda: None)

    scope = {"headers": [(b"authorization", b"Bearer secret_key")]}
    assert _resolve_user(scope) == "default"

def test_resolve_user_bearer_multi_user_success(monkeypatch):
    if "MCP_API_KEY" in os.environ:
        monkeypatch.delenv("MCP_API_KEY")

    def mock_lookup(key):
        if key == "user_token_abc":
            return "USER456"
        return None

    monkeypatch.setattr("src.api_key_store.lookup", mock_lookup)

    scope = {"headers": [(b"authorization", b"Bearer user_token_abc")]}
    assert _resolve_user(scope) == "USER456"

def test_resolve_user_bearer_multi_user_fail(monkeypatch):
    if "MCP_API_KEY" in os.environ:
        monkeypatch.delenv("MCP_API_KEY")

    monkeypatch.setattr("src.api_key_store.lookup", lambda key: None)

    scope = {"headers": [(b"authorization", b"Bearer invalid_token")]}
    assert _resolve_user(scope) is None

def test_resolve_user_basic_single_user_success(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret_key")
    monkeypatch.setattr("src.session_store.get_active_user_id", lambda: "USER123")

    # Header format: Basic base64(user_id:token) -> USER123:secret_key
    creds = base64.b64encode(b"USER123:secret_key").decode("utf-8")
    scope = {"headers": [(b"authorization", f"Basic {creds}".encode("utf-8"))]}
    assert _resolve_user(scope) == "USER123"

def test_resolve_user_basic_single_user_username_mismatch(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "secret_key")
    monkeypatch.setattr("src.session_store.get_active_user_id", lambda: "USER123")

    # WRONGUSER:secret_key
    creds = base64.b64encode(b"WRONGUSER:secret_key").decode("utf-8")
    scope = {"headers": [(b"authorization", f"Basic {creds}".encode("utf-8"))]}
    assert _resolve_user(scope) is None

def test_resolve_user_basic_multi_user_success(monkeypatch):
    if "MCP_API_KEY" in os.environ:
        monkeypatch.delenv("MCP_API_KEY")

    def mock_lookup(key):
        if key == "user_token_abc":
            return "USER456"
        return None

    monkeypatch.setattr("src.api_key_store.lookup", mock_lookup)

    # USER456:user_token_abc
    creds = base64.b64encode(b"USER456:user_token_abc").decode("utf-8")
    scope = {"headers": [(b"authorization", f"Basic {creds}".encode("utf-8"))]}
    assert _resolve_user(scope) == "USER456"

def test_resolve_user_basic_multi_user_username_mismatch(monkeypatch):
    if "MCP_API_KEY" in os.environ:
        monkeypatch.delenv("MCP_API_KEY")

    def mock_lookup(key):
        if key == "user_token_abc":
            return "USER456"
        return None

    monkeypatch.setattr("src.api_key_store.lookup", mock_lookup)

    # WRONGUSER:user_token_abc
    creds = base64.b64encode(b"WRONGUSER:user_token_abc").decode("utf-8")
    scope = {"headers": [(b"authorization", f"Basic {creds}".encode("utf-8"))]}
    assert _resolve_user(scope) is None

def test_resolve_user_basic_invalid_base64():
    scope = {"headers": [(b"authorization", b"Basic invalid_base64_chars!@#$")]}
    assert _resolve_user(scope) is None

def test_resolve_user_basic_missing_colon():
    creds = base64.b64encode(b"username_no_colon").decode("utf-8")
    scope = {"headers": [(b"authorization", f"Basic {creds}".encode("utf-8"))]}
    assert _resolve_user(scope) is None
