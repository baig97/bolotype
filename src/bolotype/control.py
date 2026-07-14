from __future__ import annotations

import json
import socket
from pathlib import Path

from .daemon import DEFAULT_SOCKET

_COMMAND_TO_ACTION: dict[str, dict] = {
    "start":             {"action": "start"},
    "stop":              {"action": "stop"},
    "toggle":            {"action": "toggle"},
    "undo":              {"action": "undo"},
    "status":            {"action": "status"},
    "shutdown":          {"action": "shutdown"},
    "polish":            {"action": "polish", "target": "all"},
    "polish-line":       {"action": "polish", "target": "line"},
    "polish-paragraph":  {"action": "polish", "target": "paragraph"},
    "polish-all":        {"action": "polish", "target": "all"},
    "polish-selection":  {"action": "polish", "target": "selection"},
}


def send_request(socket_path: Path, payload: dict) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
        client.sendall(json.dumps(payload).encode())
        response = client.recv(65536)
    finally:
        client.close()
    return json.loads(response.decode())


def send_action(command: str, socket_path: Path | None = None) -> None:
    sock = socket_path or DEFAULT_SOCKET
    payload = _COMMAND_TO_ACTION.get(command)
    if payload is None:
        raise SystemExit(f"Unknown command: {command}")
    try:
        response = send_request(sock, payload)
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise SystemExit(f"Daemon unavailable: {exc}") from exc
    import json as _json
    print(_json.dumps(response, indent=2))
    if not response.get("ok"):
        raise SystemExit(1)
