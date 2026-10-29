"""Anonymous workspace leases, bounded request bodies and scheduled deletion."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import threading
import time

from starlette.requests import Request
from starlette.responses import JSONResponse

from backend import config, store

COOKIE = "zoneminer_session"


def size(root: str | Path) -> int:
    total = 0
    for directory, _, filenames in os.walk(root):
        for filename in filenames:
            try:
                total += os.stat(os.path.join(directory, filename)).st_size
            except FileNotFoundError:
                pass  # another expired workspace was removed during the scan
    return total


def check_storage():
    if config.data_dir() == config.DATA_DIR:
        return
    from fastapi import HTTPException
    workspace_mb = config.optional_limit("WORKSPACE_MB")
    total_mb = config.optional_limit("TOTAL_STORAGE_MB")
    if workspace_mb is not None and size(config.data_dir()) > workspace_mb * 1024 * 1024:
        raise HTTPException(507, "Temporary workspace is full. Delete this session or use a smaller dataset.")
    if total_mb is not None and size(Path(config.DATA_DIR) / "sessions") > total_mb * 1024 * 1024:
        raise HTTPException(507, "Temporary storage is full. Please try again later.")
    if shutil.disk_usage(config.data_dir()).free < config.limit("DISK_RESERVE_MB", 512) * 1024 * 1024:
        raise HTTPException(507, "The server is running low on disk space. Please try later or use the local version.")


@dataclass
class Lease:
    root: str
    expires: float
    active: int = 0


class Sessions:
    def __init__(self):
        self.root = Path(config.DATA_DIR) / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.leases: dict[str, Lease] = {}
        for path in self.root.glob("*/session.json"):
            if re.fullmatch(r"[A-Za-z0-9_-]{43}", path.parent.name):
                try:
                    self.leases[path.parent.name] = Lease(str(path.parent), float(json.loads(path.read_text())["expires"]))
                except (ValueError, KeyError):
                    shutil.rmtree(path.parent)

    def cleanup(self, now=None):
        from backend.jobs import manager
        now = time.time() if now is None else now
        with self.lock:
            for token, lease in list(self.leases.items()):
                if lease.expires <= now and not lease.active and not manager.has_pending(lease.root):
                    store.close_workspace(lease.root)
                    shutil.rmtree(lease.root)
                    del self.leases[token]
                    manager.forget_workspace(lease.root)

    def acquire(self, token):
        from fastapi import HTTPException
        with self.lock:
            lease = self.leases.get(token or "")
            if lease and lease.expires <= time.time():
                raise HTTPException(410, "This temporary session has expired. Start a new session.")
            fresh = lease is None
            if fresh:
                total_mb = config.optional_limit("TOTAL_STORAGE_MB")
                if len(self.leases) >= config.limit("MAX_SESSIONS", 100) or (total_mb is not None and size(self.root) >= total_mb * 1024 * 1024):
                    raise HTTPException(503, "Temporary workspaces are at capacity. Please try again later.")
                token = secrets.token_urlsafe(32)
                root = self.root / token
                root.mkdir(mode=0o700)
                lease = Lease(str(root), time.time() + config.limit("SESSION_TTL_SECONDS", 86400))
                (root / "session.json").write_text(json.dumps({"expires": lease.expires}))
                self.leases[token] = lease
            if lease.active >= config.limit("SESSION_REQUESTS", 8):
                raise HTTPException(429, "Too many requests in this session. Please try again shortly.", headers={"Retry-After": "1"})
            lease.active += 1
            return token, lease, fresh


class AnonymousMiddleware:
    def __init__(self, app, sessions):
        self.app = app
        self.sessions = sessions
        self.public_origin = config.public_origin()
        self.slots = threading.BoundedSemaphore(config.limit("MAX_REQUESTS", 16))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["path"] == "/api/health":
            return await self.app(scope, receive, send)
        from fastapi import HTTPException
        request = Request(scope)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            # Cookies authenticate the workspace. Reject cross-origin mutations,
            # including simple multipart POSTs that bypass CORS preflight.
            origin = request.headers.get("origin")
            allowed = ({self.public_origin} if self.public_origin else
                       {str(request.base_url).rstrip("/"), "http://localhost:5173", "http://127.0.0.1:5173"})
            if origin and origin not in allowed:
                return await JSONResponse({"detail": "Cross-origin requests are not allowed."}, 403)(scope, receive, send)
        if not self.slots.acquire(blocking=False):
            return await JSONResponse({"detail": "Server is busy. Please try again shortly."}, 429, headers={"Retry-After": "1"})(scope, receive, send)
        lease = None
        context = None
        try:
            if request.method == "DELETE" and scope["path"] == "/api/session":
                with self.sessions.lock:
                    previous = self.sessions.leases.get(request.cookies.get(COOKIE, ""))
                    if previous:
                        previous.expires = 0
                        marker = Path(previous.root) / "session.tmp"
                        marker.write_text(json.dumps({"expires": 0}))
                        os.replace(marker, Path(previous.root) / "session.json")
                response = JSONResponse(None, status_code=200, headers={"Cache-Control": "no-store"})
                response.delete_cookie(COOKIE, path="/")
                return await response(scope, receive, send)
            token, lease, fresh = self.sessions.acquire(request.cookies.get(COOKIE))
            context = config.WORKSPACE.set(lease.root)
            scope["state"] = {**scope.get("state", {}), "session_expires": lease.expires}
            if fresh:
                # Only bundled, synthetic inputs are registered; never copy the
                # local database, which can contain a developer's private logs.
                from backend.main import register_demo_dataset, register_example_datasets
                register_demo_dataset()
                register_example_datasets()
            check_storage()
            multipart = request.headers.get("content-type", "").startswith("multipart/")
            request_mb = config.optional_limit("REQUEST_MB") if multipart else config.optional_limit("JSON_REQUEST_MB", 1)
            maximum = request_mb * 1024 * 1024 if request_mb is not None else None
            try:
                declared = int(request.headers.get("content-length", "0"))
            except ValueError:
                raise HTTPException(400, "Invalid content length")
            if declared < 0 or (maximum is not None and declared > maximum):
                raise HTTPException(413, "Request exceeds the upload limit.")
            # Count actual bytes before the multipart parser receives them. A
            # missing or dishonest Content-Length cannot bypass this boundary.
            with tempfile.TemporaryFile(dir=lease.root) as body:
                count = 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    count += len(chunk)
                    if maximum is not None and count > maximum:
                        raise HTTPException(413, "Request exceeds the upload limit.")
                    body.write(chunk)
                    if count // (4 * 1024 * 1024) != (count - len(chunk)) // (4 * 1024 * 1024):
                        check_storage()
                    if not message.get("more_body", False):
                        break
                body.seek(0)
                complete = False

                async def replay():
                    nonlocal complete
                    if complete:
                        return await receive()
                    chunk = body.read(64 * 1024)
                    complete = body.tell() == count
                    return {"type": "http.request", "body": chunk, "more_body": not complete}

                async def respond(message):
                    if message["type"] == "http.response.start":
                        headers = list(message.get("headers", []))
                        headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")])
                        if fresh:
                            cookie = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={config.limit('SESSION_TTL_SECONDS', 86400)}"
                            if os.environ.get("ZONE_ANALYTICS_COOKIE_SECURE", "1") == "1":
                                cookie += "; Secure"
                            headers.append((b"set-cookie", cookie.encode()))
                        message = {**message, "headers": headers}
                    await send(message)
                await self.app(scope, replay, respond)
        except HTTPException as error:
            await JSONResponse({"detail": error.detail}, error.status_code,
                               headers={"Cache-Control": "no-store", **(error.headers or {})})(scope, receive, send)
        finally:
            if context is not None:
                config.WORKSPACE.reset(context)
            if lease:
                with self.sessions.lock:
                    lease.active -= 1
            self.slots.release()
