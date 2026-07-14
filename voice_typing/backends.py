from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod


class InjectionError(RuntimeError):
    pass


class TextBackend(ABC):
    name: str

    @abstractmethod
    def type_text(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def backspace(self, count: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def undo(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def hotkey(self, *keys: str) -> None:
        raise NotImplementedError


def _run(args: list[str], *, stdin: str | None = None) -> None:
    try:
        subprocess.run(
            args,
            input=stdin,
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise InjectionError(f"Missing executable: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else str(exc)
        raise InjectionError(f"{' '.join(args)} failed: {detail}") from exc


class XdotoolBackend(TextBackend):
    name = "xdotool"

    def type_text(self, text: str) -> None:
        if text:
            _run(["xdotool", "type", "--clearmodifiers", "--delay", "1", "--", text])

    def backspace(self, count: int) -> None:
        if count > 0:
            _run(["xdotool", "key", "--clearmodifiers", "--delay", "2", "--repeat", str(count), "BackSpace"])

    def undo(self) -> None:
        _run(["xdotool", "key", "--clearmodifiers", "ctrl+z"])

    def hotkey(self, *keys: str) -> None:
        if keys:
            _run(["xdotool", "key", "--clearmodifiers", "+".join(keys)])


class WtypeBackend(TextBackend):
    name = "wtype"

    def type_text(self, text: str) -> None:
        if text:
            _run(["wtype", "-d", "1", text])

    def backspace(self, count: int) -> None:
        for _ in range(max(0, count)):
            _run(["wtype", "-P", "BackSpace", "-p", "BackSpace"])

    def undo(self) -> None:
        _run(["wtype", "-M", "ctrl", "-P", "z", "-p", "z", "-m", "ctrl"])

    def hotkey(self, *keys: str) -> None:
        if not keys:
            return
        for key in keys[:-1]:
            _run(["wtype", "-M", key])
        _run(["wtype", "-P", keys[-1], "-p", keys[-1]])
        for key in reversed(keys[:-1]):
            _run(["wtype", "-m", key])


class YdotoolBackend(TextBackend):
    name = "ydotool"

    def type_text(self, text: str) -> None:
        if text:
            _run(["ydotool", "type", "--key-delay", "1", text])

    def backspace(self, count: int) -> None:
        pair = ["14:1", "14:0"]
        remaining = max(0, count)
        while remaining:
            n = min(remaining, 100)
            _run(["ydotool", "key", *(pair * n)])
            remaining -= n

    def undo(self) -> None:
        # Linux input key codes: left Ctrl=29, Z=44.
        _run(["ydotool", "key", "29:1", "44:1", "44:0", "29:0"])

    def hotkey(self, *keys: str) -> None:
        raise InjectionError("hotkey() is not implemented for ydotool yet.")


def choose_backend(preferred: str = "auto") -> TextBackend:
    available = {
        "xdotool": shutil.which("xdotool") is not None,
        "wtype": shutil.which("wtype") is not None,
        "ydotool": shutil.which("ydotool") is not None,
    }
    constructors = {
        "xdotool": XdotoolBackend,
        "wtype": WtypeBackend,
        "ydotool": YdotoolBackend,
    }
    if preferred != "auto":
        if preferred not in constructors:
            raise InjectionError(f"Unknown backend: {preferred}")
        if not available[preferred]:
            raise InjectionError(f"{preferred} is not installed")
        return constructors[preferred]()

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    order = ["xdotool", "ydotool", "wtype"] if session == "x11" else ["ydotool", "wtype", "xdotool"]
    for name in order:
        if available[name]:
            return constructors[name]()
    raise InjectionError("Install xdotool for X11 or ydotool/wtype for Wayland")
