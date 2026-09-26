"""Loopback-only rendezvous between wwbs and the SillyTavern browser extension."""

from __future__ import annotations

import json
import queue
import secrets
import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORT = 18765


@dataclass
class _Pending:
    reply: queue.Queue


class SillyTavernBridge:
    def __init__(self, token: str, port: int = PORT) -> None:
        self.token = token
        self.port = port
        self._requests: queue.Queue[dict] = queue.Queue()
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                return secrets.compare_digest(
                    self.headers.get("Authorization", ""), f"Bearer {bridge.token}"
                )

            def do_OPTIONS(self) -> None:
                self._send(204, {})

            def do_GET(self) -> None:
                if not self._authorized():
                    self._send(401, {"error": "invalid bridge key"})
                    return
                if self.path == "/next":
                    item = None
                    while True:
                        try:
                            candidate = bridge._requests.get_nowait()
                        except queue.Empty:
                            break
                        with bridge._lock:
                            if candidate["id"] in bridge._pending:
                                item = candidate
                                break
                    self._send(200, {"request": item})
                elif self.path == "/health":
                    self._send(200, {"ok": True})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                if not self._authorized():
                    self._send(401, {"error": "invalid bridge key"})
                    return
                if self.path != "/reply":
                    self._send(404, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > 16384:
                        raise ValueError()
                    data = json.loads(self.rfile.read(length))
                    request_id = data["id"]
                    if not isinstance(request_id, str):
                        raise ValueError()
                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    self._send(400, {"error": "invalid reply"})
                    return
                with bridge._lock:
                    pending = bridge._pending.get(request_id)
                if pending is None:
                    self._send(404, {"error": "request expired"})
                    return
                pending.reply.put(data)
                self._send(200, {"ok": True})

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.port = self._server.server_port
        threading.Thread(target=self._server.serve_forever, name="st-bridge", daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def ask(self, message: str, character: str, history: list[dict], timeout: float = 180.0) -> str:
        if self._server is None:
            raise RuntimeError("酒馆桥接服务尚未启动。")
        request_id = uuid.uuid4().hex
        pending = _Pending(queue.Queue(maxsize=1))
        with self._lock:
            self._pending[request_id] = pending
        self._requests.put({"id": request_id, "message": message, "character": character, "history": history})
        try:
            try:
                result = pending.reply.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError("等待酒馆回复超时。请保持酒馆网页打开，并启用 wwbs 桥接扩展。") from None
            if result.get("error"):
                raise RuntimeError(str(result["error"]))
            reply = result.get("text")
            if not isinstance(reply, str) or not reply.strip():
                raise RuntimeError("酒馆没有返回有效文字。")
            return reply.strip()
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
