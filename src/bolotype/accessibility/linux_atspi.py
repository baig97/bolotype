from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional


class AccessibilityError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Low-level AT-SPI helpers
# ---------------------------------------------------------------------------

def has_state(obj, state) -> bool:
    try:
        return obj.getState().contains(state)
    except Exception:
        try:
            return obj.get_state_set().contains(state)
        except Exception:
            return False


def query_text(obj):
    try:
        return obj.queryText()
    except Exception:
        return None


def query_editable_text(obj):
    try:
        return obj.queryEditableText()
    except Exception:
        return None


def iter_children(obj):
    try:
        count = obj.childCount
    except Exception:
        try:
            count = obj.get_child_count()
        except Exception:
            count = 0

    for index in range(count):
        try:
            yield obj[index]
        except Exception:
            try:
                yield obj.get_child_at_index(index)
            except Exception:
                continue


def _is_fffc_only(text: str) -> bool:
    return bool(text) and not text.replace("￼", "").strip()


def resolve_text_object(root, max_depth: int = 10):
    """
    Find the best text-capable object at or below root.

    Preference order:
    1. Focused + editable + Text
    2. Focused + Text
    3. Editable + Text
    4. Any Text object
    """
    import pyatspi  # type: ignore

    candidates: list[tuple[int, int, object]] = []
    visited: set[int] = set()

    def visit(obj, depth: int) -> None:
        if obj is None or depth > max_depth:
            return

        object_id = id(obj)
        if object_id in visited:
            return
        visited.add(object_id)

        text_iface = query_text(obj)
        editable_iface = query_editable_text(obj)

        if text_iface is not None:
            score = 0

            if has_state(obj, pyatspi.STATE_FOCUSED):
                score += 100

            if has_state(obj, pyatspi.STATE_EDITABLE):
                score += 40

            if editable_iface is not None:
                score += 40

            if has_state(obj, pyatspi.STATE_ACTIVE):
                score += 10

            # Prefer deeper objects — the actual text field is commonly nested
            # under frames, panels, documents, and browser containers.
            candidates.append((score, depth, obj))

        for child in iter_children(obj):
            visit(child, depth + 1)

    visit(root, 0)

    if not candidates:
        return None

    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return candidates[0][2]


def find_real_text_node(root, max_depth: int = 12):
    """
    Like resolve_text_object but explicitly skips nodes whose entire text is
    U+FFFC (AT-SPI object-replacement placeholders used by Chrome/Electron).
    Returns (score, node, text) or None.
    """
    import pyatspi  # type: ignore

    candidates = []

    def visit(node, depth: int) -> None:
        if node is None or depth > max_depth:
            return

        text_iface = query_text(node)
        if text_iface is not None:
            try:
                count = text_iface.characterCount
                value = text_iface.getText(0, count)
            except Exception:
                value = ""

            if value and not _is_fffc_only(value):
                score = depth  # prefer deeper nodes
                if has_state(node, pyatspi.STATE_FOCUSED):
                    score += 100
                if has_state(node, pyatspi.STATE_EDITABLE):
                    score += 50
                candidates.append((score, node, value))

        for child in iter_children(node):
            visit(child, depth + 1)

    visit(root, 0)

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0]


def dump_text_subtree(node, depth: int = 0, max_depth: int = 8) -> None:
    import pyatspi  # type: ignore

    if depth > max_depth:
        return

    text = None
    iface = query_text(node)
    if iface is not None:
        try:
            text = iface.getText(0, iface.characterCount)
        except Exception:
            text = "<read failed>"

    print(
        "  " * depth,
        f"role={safe_role_name(node)!r}",
        f"name={safe_name(node)!r}",
        f"text={text!r}",
        f"focused={has_state(node, pyatspi.STATE_FOCUSED)}",
        f"editable={query_editable_text(node) is not None}",
        flush=True,
    )

    for child in iter_children(node):
        dump_text_subtree(child, depth + 1, max_depth)


def safe_role_name(obj) -> str:
    try:
        return obj.getRoleName()
    except Exception:
        try:
            return obj.get_role_name()
        except Exception:
            return "<unknown>"


def safe_name(obj) -> str:
    try:
        return obj.name or ""
    except Exception:
        return ""


def set_clipboard_text(text: str) -> None:
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        subprocess.run(["wl-copy"], input=text.encode(), check=True)
    else:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)


# ---------------------------------------------------------------------------
# FocusTracker
# ---------------------------------------------------------------------------

class FocusTracker:
    """
    Tracks the most recently focused accessible object via AT-SPI events.
    Much faster than walking the full desktop tree on every operation.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._focused = None
        self._last_updated = 0.0
        self._started = False
        self._registry_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._started:
            return

        import pyatspi  # type: ignore

        pyatspi.Registry.registerEventListener(
            self._on_focus_event,
            "object:state-changed:focused",
        )

        self._registry_thread = threading.Thread(
            target=self._run_registry_loop,
            name="atspi-event-loop",
            daemon=True,
        )
        self._registry_thread.start()

        self._started = True

    def stop(self) -> None:
        if not self._started:
            return

        import pyatspi  # type: ignore

        try:
            pyatspi.Registry.deregisterEventListener(
                self._on_focus_event,
                "object:state-changed:focused",
            )
        except Exception:
            pass

        try:
            pyatspi.Registry.stop()
        except Exception:
            pass

        self._started = False

    def _run_registry_loop(self) -> None:
        try:
            import pyatspi  # type: ignore
            pyatspi.Registry.start()
        except Exception as exc:
            print(f"[AT-SPI event loop stopped] {exc}", flush=True)

    def _on_focus_event(self, event) -> None:
        try:
            gained_focus = bool(event.detail1)
        except Exception:
            gained_focus = True

        if not gained_focus:
            return

        source = getattr(event, "source", None)
        if source is None:
            return

        print(
            "[AT-SPI focus]",
            f"role={safe_role_name(source)!r}",
            f"name={safe_name(source)!r}",
            f"text={query_text(source) is not None}",
            f"editable={query_editable_text(source) is not None}",
            flush=True,
        )

        resolved = resolve_text_object(source)

        if resolved is not None:
            print(
                "[AT-SPI resolved]",
                f"role={safe_role_name(resolved)!r}",
                f"name={safe_name(resolved)!r}",
                f"text={query_text(resolved) is not None}",
                f"editable={query_editable_text(resolved) is not None}",
                flush=True,
            )

        with self._lock:
            self._focused = resolved or source
            self._last_updated = time.monotonic()

    def get_focused_object(self):
        with self._lock:
            obj = self._focused

        if obj is None:
            return None

        return resolve_text_object(obj) or obj


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FocusedTextContext:
    accessible: object
    text_iface: object
    editable_iface: object  # may be None for read-only / Chrome fields
    text: str
    caret: int
    selection_start: int
    selection_end: int
    app_name: str
    role_name: str
    element_name: str

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.app_name, self.role_name, self.element_name)


@dataclass(frozen=True)
class PolishSnapshot:
    identity: tuple[str, str, str]
    start: int
    original: str       # text[start:end] before polish
    replacement: str    # polished text that was written


# ---------------------------------------------------------------------------
# Main surface
# ---------------------------------------------------------------------------

class LinuxAccessibilityTextSurface:
    """Read and edit the focused Linux text control through AT-SPI2."""

    def __init__(self) -> None:
        try:
            import pyatspi  # type: ignore
        except ImportError as exc:
            raise AccessibilityError(
                "python3-pyatspi is unavailable. Install it and create the virtual "
                "environment with --system-site-packages."
            ) from exc
        self.pyatspi = pyatspi
        self.focus_tracker = FocusTracker()
        self.focus_tracker.start()

    def close(self) -> None:
        self.focus_tracker.stop()

    def focused_context(self) -> FocusedTextContext:
        element = self.focus_tracker.get_focused_object()
        if element is None:
            raise AccessibilityError(
                "No focused accessibility object has been observed yet. "
                "Click inside the target text field and try again."
            )

        resolved = resolve_text_object(element)
        if resolved is None:
            raise AccessibilityError(
                "The focused accessibility object does not expose a usable "
                f"Text descendant. role={safe_role_name(element)!r}, "
                f"name={safe_name(element)!r}"
            )
        focused = resolved

        try:
            text_iface = focused.queryText()
        except Exception as exc:
            raise AccessibilityError(
                "The focused element does not expose the AT-SPI Text interface"
            ) from exc

        # EditableText is optional — Chrome/Electron expose Text but not EditableText.
        editable_iface = query_editable_text(focused)

        try:
            character_count = int(text_iface.characterCount)
            text = text_iface.getText(0, character_count)
            caret = int(text_iface.caretOffset)
            print(
                f"[AT-SPI text] characterCount={character_count} "
                f"caret={caret} "
                f"first80={text[:80]!r} "
                f"last80={text[-80:]!r}",
                flush=True,
            )
        except Exception as exc:
            raise AccessibilityError("Could not read focused text or caret") from exc

        # If the resolved node only returns U+FFFC placeholders (Chrome/Electron
        # contenteditable), search its descendants for a node with real text.
        # Each U+FFFC in the parent maps 1:1 to a child by index, so the
        # section-level caret directly encodes which child paragraph is focused.
        if _is_fffc_only(text):
            section_caret = caret  # preserve before overwriting
            print(
                f"[AT-SPI] resolved node returned only U+FFFC "
                f"(role={safe_role_name(focused)!r} section_caret={section_caret}), "
                f"searching descendants...",
                flush=True,
            )
            dump_text_subtree(focused)

            result = None
            if section_caret >= 0:
                children = list(iter_children(focused))
                print(
                    f"[AT-SPI FFFC] section has {len(children)} children, "
                    f"trying child[{section_caret}]",
                    flush=True,
                )
                if section_caret < len(children):
                    result = find_real_text_node(children[section_caret])
                    if result is not None:
                        print(
                            f"[AT-SPI FFFC] child[{section_caret}] resolved to "
                            f"role={safe_role_name(result[1])!r}",
                            flush=True,
                        )

            if result is None:
                print("[AT-SPI FFFC] child navigation failed, falling back to global search", flush=True)
                result = find_real_text_node(focused)

            if result is None:
                raise AccessibilityError(
                    "AT-SPI returned only U+FFFC placeholders and no descendant "
                    "exposes real text. This field cannot be polished via AT-SPI."
                )
            _, focused, text = result
            text_iface = query_text(focused)
            editable_iface = query_editable_text(focused)
            try:
                caret = int(text_iface.caretOffset)
                if caret < 0:
                    caret = len(text)
            except Exception:
                caret = len(text)
            print(
                f"[AT-SPI fallback] found real text in "
                f"role={safe_role_name(focused)!r} "
                f"len={len(text)} "
                f"caret={caret} "
                f"first80={text[:80]!r} "
                f"last80={text[-80:]!r}",
                flush=True,
            )

        selection_start = caret
        selection_end = caret
        try:
            if int(text_iface.getNSelections()) > 0:
                selection_start, selection_end = text_iface.getSelection(0)
                selection_start = int(selection_start)
                selection_end = int(selection_end)
        except Exception:
            pass

        try:
            app = focused.getApplication()
            app_name = str(getattr(app, "name", "") or "")
        except Exception:
            app_name = ""
        try:
            role_name = str(focused.getRoleName() or "")
        except Exception:
            role_name = ""
        try:
            element_name = str(focused.name or "")
        except Exception:
            element_name = ""

        return FocusedTextContext(
            accessible=focused,
            text_iface=text_iface,
            editable_iface=editable_iface,
            text=text,
            caret=caret,
            selection_start=selection_start,
            selection_end=selection_end,
            app_name=app_name,
            role_name=role_name,
            element_name=element_name,
        )

    def replace_range(
        self,
        context: FocusedTextContext,
        start: int,
        end: int,
        replacement: str,
        keyboard_backend=None,
    ) -> None:
        try:
            if context.editable_iface is not None:
                context.editable_iface.deleteText(start, end)
                context.editable_iface.insertText(start, replacement, len(replacement))
                return

            if keyboard_backend is not None:
                selected = False
                try:
                    result = context.text_iface.setSelection(0, start, end)
                    print(f"[replace_range] setSelection(0, {start}, {end}) -> {result!r}", flush=True)
                    selected = bool(result)
                except Exception as e:
                    print(f"[replace_range] setSelection camelCase failed: {e}", flush=True)
                    try:
                        result = context.text_iface.set_selection(0, start, end)
                        print(f"[replace_range] set_selection(0, {start}, {end}) -> {result!r}", flush=True)
                        selected = bool(result)
                    except Exception as e2:
                        print(f"[replace_range] set_selection snake_case failed: {e2}", flush=True)

                print(f"[replace_range] selected={selected}", flush=True)
                if not selected:
                    raise AccessibilityError(
                        "The application exposes text but does not allow "
                        "AT-SPI selection changes."
                    )

                try:
                    set_clipboard_text(replacement)
                    print(f"[replace_range] clipboard set, sending Ctrl+V", flush=True)
                except Exception as e:
                    print(f"[replace_range] set_clipboard_text failed: {e}", flush=True)
                    raise

                keyboard_backend.hotkey("ctrl", "v")
                print(f"[replace_range] Ctrl+V sent", flush=True)
                return

            raise AccessibilityError(
                "Focused field has no EditableText interface and no keyboard backend was provided."
            )
        except AccessibilityError:
            raise
        except Exception as exc:
            import traceback
            traceback.print_exc()
            raise AccessibilityError("AT-SPI failed to replace the focused range") from exc

    def replace_all(self, context: FocusedTextContext, replacement: str) -> None:
        self.replace_range(context, 0, len(context.text), replacement)
        try:
            context.text_iface.setCaretOffset(len(replacement))
        except Exception:
            pass

    def restore_snapshot(self, snapshot: PolishSnapshot) -> bool:
        current = self.focused_context()
        if current.identity != snapshot.identity:
            return False
        end = snapshot.start + len(snapshot.replacement)
        if current.text[snapshot.start:end] != snapshot.replacement:
            return False
        self.replace_range(current, snapshot.start, end, snapshot.original)
        try:
            current.text_iface.setCaretOffset(snapshot.start + len(snapshot.original))
        except Exception:
            pass
        return True
