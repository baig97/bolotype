from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import socket
import sys
import traceback
import threading
from pathlib import Path

from .accessibility.linux_atspi import AccessibilityError, LinuxAccessibilityTextSurface, PolishSnapshot
from .input.linux import InjectionError, choose_backend
from .editor import (
    PolishCommand, PolishTarget, VoiceEditor,
    current_line_span, current_paragraph_span, selection_span,
)
from .llm import LLMConfig, TranscriptPolisher

DEFAULT_SOCKET = Path(os.environ.get(
    "BOLOTYPE_SOCKET",
    os.environ.get("MOONSHINE_VOICE_SOCKET", str(Path.home() / ".cache" / "bolotype.sock"))
))


class MissingDependencyError(RuntimeError):
    pass


def check_runtime_deps() -> None:
    missing_cmds = []
    for cmd in ("xdotool", "xclip"):
        if not shutil.which(cmd):
            missing_cmds.append(cmd)

    missing_mods = []
    try:
        import pyatspi  # noqa: F401
    except ImportError:
        missing_mods.append("pyatspi")

    if missing_cmds or missing_mods:
        lines = ["BoloType Linux integration is not fully installed.\n"]
        for cmd in missing_cmds:
            lines.append(f"  Missing command: {cmd}")
        for mod in missing_mods:
            lines.append(f"  Missing Python module: {mod}")
        lines.append("\nRun:\n\n    bolotype install\n")
        raise MissingDependencyError("\n".join(lines))



class VoiceTypingDaemon:
    def __init__(
        self,
        *,
        llm_polisher: TranscriptPolisher,
        socket_path: Path,
        language: str = "en",
        asr_engine: str = "moonshine",
        asr_settings=None,
        backend: str = "auto",
        append_space: bool = True,
        command_prefix: str = "",
        start_active: bool = False,
        llm_fail_open: bool = True,
        max_polish_characters: int = 12000,
    ) -> None:
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

        if asr_engine == "nemotron":
            from .asr.nemotron_asr import NemotronTranscriber
            s = asr_settings
            self.transcriber = NemotronTranscriber(
                language=language,
                model_id=s.nemotron_model_id if s else "nvidia/nemotron-3.5-asr-streaming-0.6b",
                lookahead_tokens=s.nemotron_lookahead_tokens if s else 3,
                vad_threshold=s.nemotron_vad_threshold if s else 0.01,
                silence_duration_s=s.nemotron_silence_duration_s if s else 0.8,
            )
            print(f"ASR engine: nemotron ({self.transcriber._model_id})")
        else:
            from .asr.moonshine_asr import MoonshineTranscriber
            self.transcriber = MoonshineTranscriber(language=language)
            print("ASR engine: moonshine")

        events_queue = self.events
        self.transcriber.add_listener(lambda text: events_queue.put(("transcript", text)))
        if hasattr(self.transcriber, "add_partial_listener"):
            self.transcriber.add_partial_listener(self._on_partial)

        print(f"Text backend: {text_backend.name}")
        print("Polish commands: 'polish this line' | 'polish this paragraph' | 'polish everything' | 'polish the selection' | 'polish this'")
        print("Undo command:    'undo that'")
        print(f"Control socket:  {self.socket_path}")
        if start_active:
            self.start_listening()

    def _on_partial(self, text: str) -> None:
        self.latest_partial = text
        self.log_partial()

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
            print("\n[polish produced no change]", flush=True)
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
                    target_str = payload or "all"
                    target_map = {
                        "line": PolishTarget.LINE,
                        "paragraph": PolishTarget.PARAGRAPH,
                        "all": PolishTarget.ALL,
                        "selection": PolishTarget.SELECTION,
                    }
                    self.polish_target(target_map.get(target_str, PolishTarget.ALL))
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
        if action == "start":
            self.start_listening()
        elif action == "stop":
            self.stop_listening()
        elif action == "toggle":
            self.toggle()
        elif action == "polish":
            target = request.get("target", "all")
            self.events.put(("polish", target))
        elif action == "undo":
            self.events.put(("undo", None))
        elif action == "status":
            pass
        elif action == "shutdown":
            self.shutdown_event.set()
        else:
            return {"ok": False, "error": f"Unknown action: {action}"}
        return {
            "ok": True,
            "active": self.active,
            "backend": self.editor.backend.name,
            "partial": self.latest_partial,
            "queued_events": self.events.qsize(),
            "has_polish_snapshot": self.last_polish is not None,
        }

    def control_server(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(5)
        server.settimeout(0.5)
        try:
            while not self.shutdown_event.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    try:
                        response = self.handle_control(json.loads(conn.recv(65536).decode("utf-8")))
                    except Exception as exc:
                        response = {"ok": False, "error": str(exc)}
                    conn.sendall(json.dumps(response).encode("utf-8"))
        finally:
            server.close()
            self.socket_path.unlink(missing_ok=True)

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.control_server, daemon=True),
            threading.Thread(target=self.event_worker, daemon=True),
        ]
        for t in threads:
            t.start()
        signal.signal(signal.SIGINT, lambda *_: self.shutdown_event.set())
        signal.signal(signal.SIGTERM, lambda *_: self.shutdown_event.set())
        print("BoloType ready. Speech inserts immediately. Say 'polish this line/paragraph/everything/the selection' to polish, 'undo that' to undo.")
        while not self.shutdown_event.wait(0.2):
            pass
        self.stop_listening()
        self.transcriber.close()
        self.events.put(("shutdown", None))
        for t in threads:
            t.join(timeout=2)
        print("\n[shutdown complete]")


def run_daemon(settings, *, start_active: bool = False, socket_path: Path | None = None,
               command_prefix: str = "", llm_fail_open: bool = True) -> None:
    check_runtime_deps()

    s = settings
    prompt_text = s.prompt_path.read_text(encoding="utf-8").strip() if s.prompt_path and s.prompt_path.exists() else None

    from .llm import DEFAULT_SYSTEM_PROMPT
    llm_cfg = LLMConfig(
        model=s.llm.model or "",
        base_url=s.llm.base_url,
        api_key=s.llm.api_key or "not-needed",
        timeout_seconds=s.llm.timeout_seconds,
        temperature=s.llm.temperature,
        max_output_tokens=s.llm.max_output_tokens,
        system_prompt=prompt_text or DEFAULT_SYSTEM_PROMPT,
    )
    if not llm_cfg.model:
        raise SystemExit(
            "No LLM model configured.\n"
            "Set VOICE_LLM_MODEL, or add 'llm.model' to ~/.bolotype/settings.json"
        )

    polisher = TranscriptPolisher(llm_cfg)
    sock = socket_path or DEFAULT_SOCKET

    try:
        app = VoiceTypingDaemon(
            llm_polisher=polisher,
            socket_path=sock,
            language=s.asr.language,
            asr_engine=s.asr.engine,
            asr_settings=s.asr,
            backend=s.input.backend,
            append_space=s.input.append_space,
            command_prefix=command_prefix,
            start_active=start_active,
            llm_fail_open=llm_fail_open,
            max_polish_characters=s.accessibility.max_text_characters,
        )
        app.run()
    except (InjectionError, AccessibilityError) as exc:
        raise SystemExit(str(exc)) from exc
