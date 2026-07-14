# BoloType

> Linux voice typing with targeted AT-SPI field polishing, powered by Moonshine.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Behavior:

1. Completed Moonshine speech is inserted immediately at the cursor.
2. Manual typing may be mixed into the same field.
3. Voice polish commands read a span of the focused field via AT-SPI2, send it to the configured OpenAI-compatible model, and replace that span in place.
4. Saying **"undo that"** restores the exact pre-polish span when possible. Otherwise it sends the application its normal `Ctrl+Z` command.

## Voice commands

| Command | What it polishes |
|---|---|
| `polish this line` | The line the caret is on |
| `polish this paragraph` | The paragraph the caret is in (blank-line delimited) |
| `polish everything` | The entire field |
| `polish the selection` | The currently selected text |
| `polish this` | Alias for *polish everything* |
| `undo that` | Restore the last polished span |

Commands only trigger when a completed Moonshine line exactly matches one of the above phrases after punctuation/whitespace normalization, so accidental triggers from mid-sentence speech are prevented.

## Install

```bash
chmod +x install_ubuntu.sh run_daemon.sh voice-toggle.sh voice-undo.sh voice-polish.sh voice-commit.sh voice-clear-buffer.sh
./install_ubuntu.sh
```

The installer recreates `.venv` with `--system-site-packages`; this is required for Ubuntu's `python3-pyatspi` package.

**For xclip (required for browser/Electron field replacement):**

```bash
sudo apt install xclip
```

### Conda environment (optional)

Instead of the venv, create a `.env` file at the project root:

```bash
CONDA_ENV_NAME=your-env-name
```

All shell scripts will activate that conda environment instead of `.venv`.

## Configure the LLM

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
export OPENAI_API_KEY="not-needed"
export VOICE_LLM_MODEL="your-model-name"
```

### Customize the system prompt

Edit `system_prompt.txt` at the project root. The daemon loads it on startup — no code changes needed. If the file is absent or empty, the built-in default prompt is used.

## Run

```bash
./run_daemon.sh --start-active
```

Keyboard controls:

```bash
./voice-toggle.sh       # start/stop listening
./voice-polish.sh       # trigger polish everything from a keybind
./voice-undo.sh         # trigger undo
```

## Replacement strategy

For native GTK fields (gedit, GNOME Text Editor, LibreOffice, terminals): AT-SPI `EditableText` is used to delete and insert the span directly.

For browser/Electron fields (Chrome, Electron apps): AT-SPI `Text.setSelection` selects the target span, the polished text is placed on the clipboard via `xclip`/`wl-copy`, and `Ctrl+V` pastes it. Chrome's ChatGPT and similar contenteditable inputs are supported this way.

Fields that expose neither `EditableText` nor AT-SPI selection (e.g. password fields, some embedded widgets) are unsupported.

## Safety and current scope

- Polish operates only on the resolved span (line, paragraph, selection, or whole field) — not the entire document.
- The default character limit per span is 12,000. Change it with `--max-polish-characters`.
- Undo restores the snapshot only when the same field is still focused and its current text exactly matches what was written. Otherwise the app sends `Ctrl+Z`.
- Replacing a rich-text field through accessibility may lose formatting. This is intended for plain text inputs, chat boxes, simple editors, and forms.
- Chain-of-thought model output (`<reasoning>` / `<thinking>` tags) is stripped automatically before the result is written.
