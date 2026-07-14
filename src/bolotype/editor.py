from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from enum import Enum

from .input.linux import TextBackend


# ---------------------------------------------------------------------------
# Polish targets and span helpers
# ---------------------------------------------------------------------------

class PolishTarget(Enum):
    LINE = "line"
    PARAGRAPH = "paragraph"
    ALL = "all"
    SELECTION = "selection"


@dataclass(frozen=True)
class PolishCommand:
    target: PolishTarget


def current_line_span(text: str, caret: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, caret) + 1
    end = text.find("\n", caret)
    if end == -1:
        end = len(text)
    return start, end


def current_paragraph_span(text: str, caret: int) -> tuple[int, int]:
    before = text[:caret]
    after = text[caret:]

    previous_boundaries = list(re.finditer(r"\n[ \t]*\n", before))
    start = previous_boundaries[-1].end() if previous_boundaries else 0

    next_boundary = re.search(r"\n[ \t]*\n", after)
    end = caret + next_boundary.start() if next_boundary else len(text)

    return start, end


def selection_span(selection_start: int, selection_end: int) -> tuple[int, int] | None:
    if selection_start == selection_end:
        return None
    return min(selection_start, selection_end), max(selection_start, selection_end)


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------

@dataclass
class InsertRecord:
    text: str
    created_at: float


class VoiceEditor:
    _UNDO_PATTERNS = {"undo that", "undo this"}
    _POLISH_COMMANDS: dict[str, PolishTarget] = {
        "polish this line": PolishTarget.LINE,
        "polish the line": PolishTarget.LINE,
        "polish this paragraph": PolishTarget.PARAGRAPH,
        "polish the paragraph": PolishTarget.PARAGRAPH,
        "polish everything": PolishTarget.ALL,
        "polish all": PolishTarget.ALL,
        "polish the selection": PolishTarget.SELECTION,
        "polish this selection": PolishTarget.SELECTION,
        "polish this": PolishTarget.ALL,
    }

    def __init__(self, backend: TextBackend, *, append_space: bool = True, command_prefix: str = "") -> None:
        self.backend = backend
        self.append_space = append_space
        self.command_prefix = command_prefix.strip().lower()
        self.history: list[InsertRecord] = []
        self._lock = threading.RLock()

    @staticmethod
    def _normalized_command(text: str) -> str:
        text = re.sub(r"[.!?]+$", "", text.strip().lower())
        return re.sub(r"\s+", " ", text)

    def _strip_command_prefix(self, text: str) -> tuple[bool, str]:
        if not self.command_prefix:
            return True, text.strip()
        normalized = text.strip()
        prefix = self.command_prefix
        if normalized.lower().startswith(prefix + " "):
            return True, normalized[len(prefix):].strip()
        return False, normalized

    def parse_voice_command(self, transcript: str) -> tuple[str, PolishCommand | tuple] | None:
        may_be_command, command_text = self._strip_command_prefix(transcript)
        if not may_be_command:
            return None
        normalized = self._normalized_command(command_text)
        target = self._POLISH_COMMANDS.get(normalized)
        if target is not None:
            return ("polish", PolishCommand(target))
        if normalized in self._UNDO_PATTERNS:
            return ("undo", ())
        return None

    def insert(self, text: str) -> None:
        with self._lock:
            rendered = text
            if self.append_space and not rendered.endswith((" ", "\n", "\t")):
                rendered += " "
            self.backend.type_text(rendered)
            self.history.append(InsertRecord(rendered, time.time()))

    def system_undo(self) -> None:
        self.backend.undo()
