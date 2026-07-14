from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import sys
import traceback
import threading
from pathlib import Path

from moonshine_voice import MicTranscriber, TranscriptEventListener, get_model_for_language

from .accessibility import AccessibilityError, LinuxAccessibilityTextSurface, PolishSnapshot
from .backends import InjectionError, choose_backend
from .editor import (
    PolishCommand, PolishTarget, VoiceEditor,
    current_line_span, current_paragraph_span, selection_span,
)
from .llm import LLMConfig, TranscriptPolisher

DEFAULT_SOCKET = Path(os.environ.get("MOONSHINE_VOICE_SOCKET", str(Path.home() / ".cache" / "moonshine-voice-typing.sock")))


class AppListener(TranscriptEventListener):
    def __init__(self, app: "VoiceTypingDaemon") -> None:
        self.app = app

    def on_line_started(self, event) -> None:
        self.app.latest_partial = event.line.text or ""
        self.app.log_partial()

    def on_line_text_changed(self, event) -> None:
        self.app.latest_partial = event.line.text or ""
        self.app.log_partial()

    def on_line_completed(self, event) -> None:
        text = (event.line.text or "").strip()
        self.app.latest_partial = ""
        if text:
            self.app.events.put(("transcript", text))


class VoiceTypingDaemon:
    def __init__(self, *, language: str, backend: str, socket_path: Path, append_space: bool,
                 command_prefix: str, start_active: bool, llm_polisher: TranscriptPolisher,
                 llm_fail_open: bool, max_polish_characters: int) -> None:
        self.socket_path = socket_path
        self.latest_partial = ""
        self.active = False
        self.shutdown_event = threading.Event()
        self.state_lock = threading.RLock()
        self.events: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.llm_polisher = llm_polisher
        self.llm_fail_open = llm_fail_open
        self.max_polish_characters = max_polish_characters
        self.last_polish: PolishSnapshot | None = None

        text_backend = choose_backend(backend)
        self.editor = VoiceEditor(text_backend, append_space=append_space, command_prefix=command_prefix)
        self.surface = LinuxAccessibilityTextSurface()

        print(f"Loading Moonshine model for language={language!r}...")
        model_path, model_arch = get_model_for_language(language)
        self.transcriber = MicTranscriber(model_path=model_path, model_arch=model_arch)
        self.transcriber.add_listener(AppListener(self))

        print(f"Text backend: {text_backend.name}")
        print("Polish commands: 'polish this line' | 'polish this paragraph' | 'polish everything' | 'polish the selection' | 'polish this'")
        print("Undo command: 'undo that'")
        print(f"Control socket: {self.socket_path}")
        if start_active:
            self.start_listening()

    def log_partial(self) -> None:
        if self.latest_partial:
            print(f"\r[partial] {self.latest_partial[:140]:<140}", end="", flush=True)

    def polish_target(self, target: PolishTarget) -> str:
        context = self.surface.focused_context()
        text, caret = context.text, context.caret

        if target is PolishTarget.LINE:
            start, end = current_line_span(text, caret)
        elif target is PolishTarget.PARAGRAPH:
            start, end = current_paragraph_span(text, caret)
        elif target is PolishTarget.ALL:
            start, end = 0, len(text)
        elif target is PolishTarget.SELECTION:
            span = selection_span(context.selection_start, context.selection_end)
            if span is None:
                raise AccessibilityError("No selected text to polish.")
            start, end = span
        else:
            raise AccessibilityError(f"Unsupported polish target: {target}")

        original = text[start:end]
        print(
            f"\n[polish target={target.value}] span=({start},{end}) "
            f"full_text={text!r} original={original!r} "
            f"caret={caret} sel=({context.selection_start},{context.selection_end})",
            flush=True,
        )
        if not original.strip():
            print(f"\n[polish ignored: {target.value} is empty]", flush=True)
            return "ignored"
        if len(original) > self.max_polish_characters:
            raise AccessibilityError(
                f"Selected span has {len(original)} characters; safety limit is {self.max_polish_characters}"
            )

        try:
            polished = self.llm_polisher.polish(original)
        except Exception as exc:
            print(f"\n[LLM error] {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
            if self.llm_fail_open:
                return "llm_failed_no_change"
            raise

        if polished == original:
            print(f"\n[polish produced no change]", flush=True)
            return "unchanged"

        snapshot = PolishSnapshot(
            identity=context.identity,
            start=start,
            original=original,
            replacement=polished,
        )
        self.surface.replace_range(context, start, end, polished,
                                   keyboard_backend=self.editor.backend)
        self.last_polish = snapshot
        print(f"\n[polished {target.value}]\nraw:   {original}\nfinal: {polished}", flush=True)
        return "polished"

    def undo(self) -> str:
        if self.last_polish is not None:
            try:
                if self.surface.restore_snapshot(self.last_polish):
                    self.last_polish = None
                    print("\n[restored pre-polish text]", flush=True)
                    return "polish_undone"
            except AccessibilityError as exc:
                print(f"\n[polish snapshot unavailable: {exc}]", file=sys.stderr, flush=True)

        self.editor.system_undo()
        print("\n[application undo sent]", flush=True)
        return "system_undo"

    def process_transcript(self, text: str) -> None:
        command = self.editor.parse_voice_command(text)
        if command is None:
            self.editor.insert(text)
            print(f"\n[inserted] {text}", flush=True)
            return
        action, payload = command
        if action == "polish":
            assert isinstance(payload, PolishCommand)
            self.polish_target(payload.target)
        elif action == "undo":
            self.undo()

    def event_worker(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                event_type, payload = self.events.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if event_type == "shutdown":
                    break
                if event_type == "transcript" and payload is not None:
                    self.process_transcript(payload)
                elif event_type == "polish":
                    self.polish_target(PolishTarget.ALL)
                elif event_type == "undo":
                    self.undo()
            except Exception as exc:
                print(f"\n[text processing failed] {exc}", file=sys.stderr, flush=True)
            finally:
                self.events.task_done()

    def start_listening(self) -> None:
        with self.state_lock:
            if not self.active:
                self.transcriber.start()
                self.active = True
                print("\n[listening started]", flush=True)

    def stop_listening(self) -> None:
        with self.state_lock:
            if self.active:
                self.transcriber.stop()
                self.active = False
                print("\n[listening stopped]", flush=True)

    def toggle(self) -> bool:
        self.stop_listening() if self.active else self.start_listening()
        return self.active

    def handle_control(self, request: dict) -> dict:
        action = request.get("action")
        if action == "start": self.start_listening()
        elif action == "stop": self.stop_listening()
        elif action == "toggle": self.toggle()
        elif action == "polish": self.events.put(("polish", None))
        elif action == "undo": self.events.put(("undo", None))
        elif action == "status": pass
        elif action == "shutdown": self.shutdown_event.set()
        else: return {"ok": False, "error": f"Unknown action: {action}"}
        return {"ok": True, "active": self.active, "backend": self.editor.backend.name,
                "partial": self.latest_partial, "queued_events": self.events.qsize(),
                "has_polish_snapshot": self.last_polish is not None}

    def control_server(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path)); os.chmod(self.socket_path, 0o600); server.listen(5); server.settimeout(0.5)
        try:
            while not self.shutdown_event.is_set():
                try: conn, _ = server.accept()
                except socket.timeout: continue
                with conn:
                    try:
                        response = self.handle_control(json.loads(conn.recv(65536).decode("utf-8")))
                    except Exception as exc:
                        response = {"ok": False, "error": str(exc)}
                    conn.sendall(json.dumps(response).encode("utf-8"))
        finally:
            server.close(); self.socket_path.unlink(missing_ok=True)

    def run(self) -> None:
        threads = [threading.Thread(target=self.control_server, daemon=True), threading.Thread(target=self.event_worker, daemon=True)]
        for thread in threads: thread.start()
        signal.signal(signal.SIGINT, lambda *_: self.shutdown_event.set())
        signal.signal(signal.SIGTERM, lambda *_: self.shutdown_event.set())
        print("BoloType ready. Speech inserts immediately. Say 'polish this line/paragraph/everything/the selection' to polish, 'undo that' to undo.")
        while not self.shutdown_event.wait(0.2): pass
        self.stop_listening(); self.transcriber.close(); self.events.put(("shutdown", None))
        for thread in threads: thread.join(timeout=2)
        print("\n[shutdown complete]")


def _load_prompt(path: Path | None) -> str | None:
    return path.read_text(encoding="utf-8") if path else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Moonshine Linux voice typing with AT-SPI field polishing")
    parser.add_argument("--language", default="en")
    parser.add_argument("--backend", choices=["auto", "xdotool", "ydotool", "wtype"], default="auto")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET)
    parser.add_argument("--no-append-space", action="store_true")
    parser.add_argument("--command-prefix", default="")
    parser.add_argument("--start-active", action="store_true")
    parser.add_argument("--llm-model", default=os.environ.get("VOICE_LLM_MODEL"))
    parser.add_argument("--llm-base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--llm-timeout", type=float, default=float(os.environ.get("VOICE_LLM_TIMEOUT", "20")))
    parser.add_argument("--llm-temperature", type=float, default=float(os.environ.get("VOICE_LLM_TEMPERATURE", "0")))
    parser.add_argument("--llm-max-tokens", type=int, default=int(os.environ.get("VOICE_LLM_MAX_TOKENS", "1200")))
    parser.add_argument("--llm-prompt-file", type=Path)
    parser.add_argument("--llm-fail-closed", action="store_true")
    parser.add_argument("--max-polish-characters", type=int, default=int(os.environ.get("VOICE_MAX_POLISH_CHARACTERS", "12000")))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.llm_model:
        raise SystemExit("Set --llm-model or VOICE_LLM_MODEL")
    kwargs = dict(model=args.llm_model, base_url=args.llm_base_url, api_key=os.environ.get("OPENAI_API_KEY"),
                  timeout_seconds=args.llm_timeout, temperature=args.llm_temperature, max_output_tokens=args.llm_max_tokens)
    prompt = _load_prompt(args.llm_prompt_file)
    if prompt is not None: kwargs["system_prompt"] = prompt
    polisher = TranscriptPolisher(LLMConfig(**kwargs))
    try:
        app = VoiceTypingDaemon(language=args.language, backend=args.backend, socket_path=args.socket,
            append_space=not args.no_append_space, command_prefix=args.command_prefix,
            start_active=args.start_active, llm_polisher=polisher,
            llm_fail_open=not args.llm_fail_closed, max_polish_characters=max(1, args.max_polish_characters))
        app.run()
    except (InjectionError, AccessibilityError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
