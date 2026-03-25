#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from manga_watch.discord_interactions import build_interaction_service_from_env


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
            response = service.handle_request(
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
