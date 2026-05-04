import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

APP_SERVER_URL = os.getenv("APP_SERVER_URL", "https://developers.openai.com/codex/app-server")
OAUTH_AUTHORIZE_URL = os.getenv("OAUTH_AUTHORIZE_URL", "")
OAUTH_TOKEN_URL = os.getenv("OAUTH_TOKEN_URL", "")
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "")
SCOPES = os.getenv("OAUTH_SCOPES", "openid profile")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
STATE_TTL_SECONDS = int(os.getenv("STATE_TTL_SECONDS", "600"))
SESSION_FILE = Path(os.getenv("SESSION_FILE", "/data/session.enc"))
FERNET_KEY_PATH = Path(os.getenv("FERNET_KEY_PATH", "/data/fernet.key"))

app = FastAPI(title="Codex App Server WS Client")


class CallbackUrlPayload(BaseModel):
    callback_url: str = Field(..., description="Browser redirect URL")


class WsRequest(BaseModel):
    payload: dict[str, Any]


def _require_admin(token: str | None) -> None:
    if not ADMIN_TOKEN:
        return
    if token != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _get_fernet() -> Fernet:
    FERNET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not FERNET_KEY_PATH.exists():
        key = Fernet.generate_key()
        FERNET_KEY_PATH.write_bytes(key)
        os.chmod(FERNET_KEY_PATH, 0o600)
    return Fernet(FERNET_KEY_PATH.read_bytes())


def _load_session() -> dict[str, Any] | None:
    if not SESSION_FILE.exists():
        return None
    token = SESSION_FILE.read_bytes()
    data = _get_fernet().decrypt(token)
    return json.loads(data)


def _save_session(data: dict[str, Any]) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = _get_fernet().encrypt(json.dumps(data).encode())
    SESSION_FILE.write_bytes(token)
    os.chmod(SESSION_FILE, 0o600)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@app.get("/auth/url")
def get_auth_url(authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    if not (OAUTH_AUTHORIZE_URL and CLIENT_ID):
        raise HTTPException(status_code=400, detail="OAuth env vars are not configured")

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = _pkce_challenge(verifier)

    _save_session({
        "state": state,
        "code_verifier": verifier,
        "created_at": int(time.time()),
    })

    query = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": SCOPES,
    }
    q = "&".join([f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in query.items()])
    return {"authorization_url": f"{OAUTH_AUTHORIZE_URL}?{q}"}


@app.post("/auth/callback-url")
async def receive_callback_url(payload: CallbackUrlPayload, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    if not OAUTH_TOKEN_URL:
        raise HTTPException(status_code=400, detail="OAUTH_TOKEN_URL is not configured")

    session = _load_session() or {}
    created = session.get("created_at", 0)
    if int(time.time()) - created > STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="Auth session expired")

    parsed = urlparse(payload.callback_url)
    params = parse_qs(parsed.query)
    code = (params.get("code") or [None])[0]
    state = (params.get("state") or [None])[0]

    if not code or not state:
        raise HTTPException(status_code=400, detail="callback_url missing code/state")
    if state != session.get("state"):
        raise HTTPException(status_code=400, detail="State mismatch")

    form = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "code_verifier": session.get("code_verifier", ""),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(OAUTH_TOKEN_URL, data=form)
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Token exchange failed: {res.status_code}")
        token_data = res.json()

    session.update({"tokens": token_data, "authenticated_at": int(time.time())})
    _save_session(session)
    return {"ok": True}


@app.post("/ws/proxy")
async def ws_proxy(request: WsRequest, authorization: str | None = Header(default=None)):
    _require_admin(authorization)
    session = _load_session() or {}
    tokens = session.get("tokens")
    if not tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "app_server_url": APP_SERVER_URL,
        "note": "Implement downstream WebSocket message flow for your AI client here.",
        "payload": request.payload,
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
