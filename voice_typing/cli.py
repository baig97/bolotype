from __future__ import annotations
import argparse, json, socket
from pathlib import Path
from .daemon import DEFAULT_SOCKET

def send_request(socket_path: Path, action: str) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path)); client.sendall(json.dumps({"action": action}).encode()); response = client.recv(65536)
    finally:
        client.close()
    return json.loads(response.decode())

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "toggle", "undo", "polish", "status", "shutdown"])
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET)
    args = parser.parse_args()
    try: response = send_request(args.socket, args.action)
    except (FileNotFoundError, ConnectionRefusedError) as exc: raise SystemExit(f"Daemon unavailable: {exc}")
    print(json.dumps(response, indent=2))
    if not response.get("ok"): raise SystemExit(1)

if __name__ == "__main__": main()
