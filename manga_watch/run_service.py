#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from manga_watch.discord_command_registration import ensure_commands_registered_from_env
from manga_watch.discord_interactions import build_interaction_service_from_env, text_response

HEALTH_CHECK_PATH = "/healthz"
HEALTH_CHECK_BODY = "ok"


def build_http_response(service, *, method, path, headers, body):
    if urlsplit(path).path == HEALTH_CHECK_PATH:
        if method not in {"GET", "HEAD"}:
            return text_response(405, "method not allowed")
        return text_response(200, HEALTH_CHECK_BODY)
    return service.handle_request(
        method=method,
        path=path,
        headers=headers,
        body=body,
    )


def build_request_handler(service):
    class DiscordInteractionRequestHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle()

        def _handle(self) -> None:
            content_length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(content_length)
            response = build_http_response(
                service,
                method=self.command,
                path=self.path,
                headers={key: value for key, value in self.headers.items()},
                body=body,
            )
            self.send_response(response.status_code)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

    return DiscordInteractionRequestHandler


def main() -> int:
    try:
        ensure_commands_registered_from_env()
        service = build_interaction_service_from_env()
    except Exception as exc:
        print(f"[run_service] configuration error: {exc}", file=sys.stderr)
        return 2

    port = int(os.environ.get("PORT", "8080"))
    handler = build_request_handler(service)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(
        f"[run_service] listening on 0.0.0.0:{port} path={service.interaction_path} "
        f"verification_disabled={service.verification_disabled}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
