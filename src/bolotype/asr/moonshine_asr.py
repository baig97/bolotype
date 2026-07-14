from __future__ import annotations

from typing import Callable

from .base import ASRTranscriber


class MoonshineTranscriber(ASRTranscriber):
    def __init__(self, language: str = "en") -> None:
        self._language = language
        self._listeners: list[Callable[[str], None]] = []
        self._partial_listeners: list[Callable[[str], None]] = []

        print(f"Loading Moonshine model for language={language!r}...")
        from moonshine_voice import MicTranscriber, TranscriptEventListener, get_model_for_language
        model_path, model_arch = get_model_for_language(language, 5)
        self._transcriber = MicTranscriber(model_path=model_path, model_arch=model_arch)

        listeners_ref = self._listeners
        partial_ref = self._partial_listeners

        class _Listener(TranscriptEventListener):
            def on_line_started(self, event) -> None:
                text = event.line.text or ""
                for cb in partial_ref:
                    cb(text)

            def on_line_text_changed(self, event) -> None:
                text = event.line.text or ""
                for cb in partial_ref:
                    cb(text)

            def on_line_completed(self, event) -> None:
                text = (event.line.text or "").strip()
                if text:
                    for cb in listeners_ref:
                        cb(text)

        self._transcriber.add_listener(_Listener())

    def add_listener(self, cb: Callable[[str], None]) -> None:
        self._listeners.append(cb)

    def add_partial_listener(self, cb: Callable[[str], None]) -> None:
        self._partial_listeners.append(cb)

    def start(self) -> None:
        self._transcriber.start()

    def stop(self) -> None:
        self._transcriber.stop()

    def close(self) -> None:
        self._transcriber.close()
