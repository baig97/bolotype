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

# ---------------------------------------------------------------------------
# Voice command matching (pure, testable — no editor/backend needed)
# ---------------------------------------------------------------------------

# Polite filler stripped from the ends of an utterance before matching, so
# "please polish this paragraph" and "polish the line please" are recognised.
_LEAD_FILLERS = ["please", "hey", "ok", "okay", "um", "uh",
                 "can you", "could you", "would you", "will you"]
_TRAIL_FILLERS = ["please", "now", "for me", "thanks", "thank you"]

_KEYWORD_TARGETS: dict[str, PolishTarget] = {
    "line": PolishTarget.LINE,
    "paragraph": PolishTarget.PARAGRAPH,
    "selection": PolishTarget.SELECTION,
    "everything": PolishTarget.ALL,
    "all": PolishTarget.ALL,
}

# ^...$ anchors are the precision guard: the whole utterance must BE the
# command. An embedded phrase ("...polish this paragraph until it shines")
# cannot match, so real dictation is never mistaken for a command.
_POLISH_RE = re.compile(r"^polish(?: (?:this|the|my))? (line|paragraph|selection|everything|all)$")
_POLISH_THIS_RE = re.compile(r"^polish this$")
_UNDO_RE = re.compile(r"^undo (that|this|it)$")


def _normalize_command(text: str) -> str:
    text = re.sub(r"[.!?]+$", "", text.strip().lower())
    return re.sub(r"\s+", " ", text)


def _strip_filler(s: str) -> str:
    """Peel polite filler off both ends, repeatedly ("okay ... please")."""
    changed = True
    while changed:
        changed = False
        for f in _LEAD_FILLERS:
            if s == f:
                return ""
            if s.startswith(f + " "):
                s = s[len(f):].strip()
                changed = True
        for f in _TRAIL_FILLERS:
            if s == f:
                return ""
            if s.endswith(" " + f):
                s = s[:-len(f)].strip()
                changed = True
    return s


def match_command(transcript: str, command_prefix: str = ""):
    """Return ("polish", PolishCommand) | ("undo", ()) | None for a transcript."""
    prefix = command_prefix.strip().lower()
    text = transcript.strip()
    if prefix:
        if text.lower().startswith(prefix + " "):
            text = text[len(prefix):].strip()
        else:
            return None
    s = _strip_filler(_normalize_command(text))
    m = _POLISH_RE.match(s)
    if m:
        return ("polish", PolishCommand(_KEYWORD_TARGETS[m.group(1)]))
    if _POLISH_THIS_RE.match(s):
        return ("polish", PolishCommand(PolishTarget.ALL))
    if _UNDO_RE.match(s):
        return ("undo", ())
    return None

class VoiceEditor:

    def __init__(self, backend: TextBackend, *, append_space: bool = True, command_prefix: str = "") -> None:
        self.backend = backend
        self.append_space = append_space
        self.command_prefix = command_prefix.strip().lower()
        self.history: list[InsertRecord] = []
        self._lock = threading.RLock()

    @staticmethod

    def parse_voice_command(self, transcript: str):
        return match_command(transcript, self.command_prefix)

    def insert(self, text: str) -> None:
        with self._lock:
            rendered = text
            if self.append_space and not rendered.endswith((" ", "\n", "\t")):
                rendered += " "
            self.backend.type_text(rendered)
            self.history.append(InsertRecord(rendered, time.time()))

    def system_undo(self) -> None:
        self.backend.undo()
