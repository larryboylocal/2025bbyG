"""Binance runtime. Serves health only and refuses order routes."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .binance_terminal import BinanceTerminal, load_config


def build_handler(terminal: BinanceTerminal) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/health":
                self.send_error(404)
                return
            body = json.dumps(terminal.health()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            self.send_error(403, "Binance live trading is off")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def serve() -> None:
    config = load_config()
    terminal = BinanceTerminal(config)
    server = ThreadingHTTPServer((config["runtime_host"], int(config["runtime_port"])), build_handler(terminal))
    server.serve_forever()


if __name__ == "__main__":
    serve()
