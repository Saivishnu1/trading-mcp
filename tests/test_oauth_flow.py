import base64
import hashlib
import json
import time
import urllib.parse
from unittest.mock import MagicMock

import pytest

from src.server import _app, _oauth_codes, _verify_pkce


# Helper to simulate ASGI calls
async def make_asgi_call(path, method="GET", query_string=b"", headers=None, body=b""):
    if headers is None:
        headers = [(b"host", b"testserver")]

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "headers": headers,
        "scheme": "http"
    }

    # Simulate body reading
    body_chunks = [body]
    async def receive():
        if body_chunks:
            return {"type": "http.request", "body": body_chunks.pop(0), "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    responses = []
    async def send(message):
        responses.append(message)

    await _app(scope, receive, send)

    # Process responses to extract status, headers, and body
    status = None
    resp_headers = {}
    resp_body = b""

    for r in responses:
        if r["type"] == "http.response.start":
            status = r["status"]
            resp_headers = {k.lower(): v for k, v in r.get("headers", [])}
        elif r["type"] == "http.response.body":
            resp_body += r.get("body", b"")

    return status, resp_headers, resp_body


def test_oauth_protected_resource_metadata():
    status, headers, body = pytest.async_run(
        make_asgi_call("/.well-known/oauth-protected-resource")
    ) if hasattr(pytest, "async_run") else None

    # Use standard event loop running for async in sync test if needed, or pytest-anyio/asyncio
    # Since we collect pytest plugins, anyio is installed. Let's make tests async.

@pytest.mark.anyio
async def test_oauth_protected_resource_metadata():
    status, headers, body = await make_asgi_call("/.well-known/oauth-protected-resource")
    assert status == 200
    assert headers[b"content-type"] == b"application/json"
    data = json.loads(body.decode())
    assert data["resource"] == "http://testserver/mcp"
    assert data["authorization_servers"] == ["http://testserver"]


@pytest.mark.anyio
async def test_oauth_authorization_server_metadata():
    status, headers, body = await make_asgi_call("/.well-known/oauth-authorization-server")
    assert status == 200
    assert headers[b"content-type"] == b"application/json"
    data = json.loads(body.decode())
    assert data["issuer"] == "http://testserver"
    assert data["authorization_endpoint"] == "http://testserver/oauth/authorize"
    assert data["token_endpoint"] == "http://testserver/oauth/token"
    assert "S256" in data["code_challenge_methods_supported"]


@pytest.mark.anyio
async def test_oauth_authorize_get():
    query = b"client_id=claude&redirect_uri=https://callback&state=xyz&code_challenge=challenge_val&code_challenge_method=S256"
    status, headers, body = await make_asgi_call("/oauth/authorize", query_string=query)
    assert status == 200
    assert headers[b"content-type"] == b"text/html; charset=utf-8"
    html = body.decode()
    # Verify action URL preserves the query string parameters
    assert 'action="/login?client_id=claude' in html
    assert 'redirect_uri=https://callback' in html
    assert 'state=xyz' in html


@pytest.mark.anyio
async def test_oauth_login_post_success(monkeypatch):
    # Mock broker authentication
    mock_broker = MagicMock()
    mock_broker.login.return_value = None
    mock_broker.get_enctoken.return_value = "fake_enctoken"
    monkeypatch.setattr("src.server.get_broker", lambda: mock_broker)

    # Mock session_store & api_key_store
    monkeypatch.setattr("src.session_store.save", lambda uid, token: None)
    monkeypatch.setattr("src.api_key_store.get_or_create", lambda uid: ("mocked_api_key", True))

    query = b"client_id=claude&redirect_uri=https://callback&state=xyz&code_challenge=challenge_val&code_challenge_method=S256"
    body = b"user_id=ZK1234&password=mypassword&totp_code=123456"

    # Clear codes first
    _oauth_codes.clear()

    status, headers, response_body = await make_asgi_call(
        "/login", method="POST", query_string=query, body=body
    )

    assert status == 302
    location = headers[b"location"].decode()
    assert location.startswith("https://callback?code=auth_")
    assert "&state=xyz" in location

    # Verify the code is stored in server-side map
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    code = qs["code"][0]
    assert code in _oauth_codes
    assert _oauth_codes[code]["user_id"] == "ZK1234"
    assert _oauth_codes[code]["api_key"] == "mocked_api_key"
    assert _oauth_codes[code]["code_challenge"] == "challenge_val"
    assert _oauth_codes[code]["code_challenge_method"] == "S256"


@pytest.mark.anyio
async def test_oauth_token_exchange_success_plain():
    _oauth_codes.clear()
    code = "auth_plain_code"
    _oauth_codes[code] = {
        "user_id": "USER1",
        "api_key": "api_key_123",
        "code_challenge": "my_challenge",
        "code_challenge_method": "plain",
        "expires_at": time.time() + 100
    }

    body = b"grant_type=authorization_code&code=auth_plain_code&code_verifier=my_challenge"
    status, headers, resp_body = await make_asgi_call(
        "/oauth/token", method="POST", body=body
    )

    assert status == 200
    data = json.loads(resp_body.decode())
    assert data["access_token"] == "api_key_123"
    assert data["token_type"] == "bearer"  # lowercase per RFC 6750
    assert code not in _oauth_codes  # Consumed


@pytest.mark.anyio
async def test_oauth_token_exchange_success_s256():
    _oauth_codes.clear()
    code = "auth_s256_code"
    verifier = "my_verifier_string_123"
    hashed = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(hashed).decode("utf-8").rstrip("=")

    _oauth_codes[code] = {
        "user_id": "USER1",
        "api_key": "api_key_456",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "expires_at": time.time() + 100
    }

    body = f"grant_type=authorization_code&code=auth_s256_code&code_verifier={verifier}".encode()
    status, headers, resp_body = await make_asgi_call(
        "/oauth/token", method="POST", body=body
    )

    assert status == 200
    data = json.loads(resp_body.decode())
    assert data["access_token"] == "api_key_456"
    assert code not in _oauth_codes


@pytest.mark.anyio
async def test_oauth_token_exchange_invalid_verifier():
    _oauth_codes.clear()
    code = "auth_s256_code"
    verifier = "my_verifier_string_123"
    hashed = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(hashed).decode("utf-8").rstrip("=")

    _oauth_codes[code] = {
        "user_id": "USER1",
        "api_key": "api_key_456",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "expires_at": time.time() + 100
    }

    body = b"grant_type=authorization_code&code=auth_s256_code&code_verifier=wrong_verifier"
    status, headers, resp_body = await make_asgi_call(
        "/oauth/token", method="POST", body=body
    )

    assert status == 400
    data = json.loads(resp_body.decode())
    assert data["error"] == "invalid_grant"
    assert code in _oauth_codes  # Not consumed on failure


@pytest.mark.anyio
async def test_oauth_token_exchange_expired():
    _oauth_codes.clear()
    code = "auth_expired_code"
    _oauth_codes[code] = {
        "user_id": "USER1",
        "api_key": "api_key_123",
        "expires_at": time.time() - 10  # expired
    }

    body = b"grant_type=authorization_code&code=auth_expired_code"
    status, headers, resp_body = await make_asgi_call(
        "/oauth/token", method="POST", body=body
    )

    assert status == 400
    data = json.loads(resp_body.decode())
    assert data["error"] == "invalid_grant"
    assert code not in _oauth_codes  # Cleared


@pytest.mark.anyio
async def test_oauth_token_exchange_invalid_code():
    _oauth_codes.clear()
    body = b"grant_type=authorization_code&code=auth_invalid_code"
    status, headers, resp_body = await make_asgi_call(
        "/oauth/token", method="POST", body=body
    )
    assert status == 400
    data = json.loads(resp_body.decode())
    assert data["error"] == "invalid_grant"
