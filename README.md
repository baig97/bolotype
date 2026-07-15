# BoloType — Type at the speed of sound. Refine with LLMs of your choice.

> System-wide voice typing with instant dictation and AI-powered editing.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Platform support:** Linux only. Windows and macOS support is coming soon.

---

## Features

- **Instant dictation** — speech inserts at the cursor as soon as a phrase completes. No push-to-talk, no button to hold.
- **Bring your own LLM** — connect any OpenAI-compatible endpoint: llama.cpp, LMDeploy, vLLM, Ollama, OpenAI, Groq, and more. One setting to change.
- **Fully local by default** — audio never leaves your machine. LLM calls go only to the endpoint you configure. Nothing is sent anywhere unless you choose a cloud endpoint.
- **Private and safe** — no cloud account required, no telemetry, no data collection of any kind.
- **Voice polish commands** — say *"polish this paragraph"* and the LLM rewrites that span in place. Works on a line, paragraph, selection, or the entire field.
- **Precise undo** — *"undo that"* restores the exact pre-polish text, not a generic Ctrl+Z that may affect unrelated changes.
- **Two ASR engines** — [Moonshine](https://github.com/usefulsensors/moonshine) is fast, low-latency, and works on CPU. [Nemotron 3.5](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) offers higher accuracy and requires a CUDA GPU.
- **System-wide** — works in any text field reachable via AT-SPI2: GTK apps, browsers, Electron apps, terminals, and more.

---

## Quickstart

> Requires Ubuntu/Debian with a CUDA or CPU setup. Moonshine engine used below.

```bash
git clone https://github.com/baig97/bolotype.git
cd bolotype

python3 -m venv --system-site-packages .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install -e .
bolotype install moonshine
```

Edit `~/.bolotype/settings.json` and set your LLM endpoint and model name (see [Configure](#configure)), then:

```bash
bolotype run --start-active
```

Say *"hello world"* — it appears at the cursor. Say *"polish this paragraph"* — the LLM rewrites it in place.

---

## Install

> BoloType is not yet published on PyPI. Install from source.

```bash
git clone https://github.com/baig97/bolotype.git
cd bolotype

python3 -m venv --system-site-packages .venv
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

This installs only the lightweight core (CLI, LLM client, config). Then install your ASR engine:

```bash
bolotype install moonshine    # Moonshine — CPU-friendly, low latency (recommended)
bolotype install nemotron     # Nemotron 3.5 — higher accuracy, requires CUDA GPU
bolotype install              # both engines
```

`bolotype install` also installs Linux system packages (`python3-pyatspi`, `xdotool`, `xclip`, etc.) via apt and creates `~/.bolotype/` with default config files.

> **Nemotron note:** Nemotron 3.5 has not been tested on CPU. A CUDA-capable GPU is strongly recommended. If you do not have a GPU, use Moonshine.

To switch engines, set `asr.engine` in `~/.bolotype/settings.json` or use the `--asr-engine` flag:

```bash
bolotype run --asr-engine nemotron --start-active
```

---

## Voice commands

| Command | What it polishes |
|---|---|
| `polish this line` | The line the caret is on |
| `polish this paragraph` | The paragraph the caret is in (blank-line delimited) |
| `polish everything` | The entire field |
| `polish the selection` | The currently selected text |
| `polish this` | Alias for *polish everything* |
| `undo that` | Restore the last polished span |

Commands trigger when a completed phrase exactly matches one of the above after punctuation and whitespace normalization.

---

## Configure

All settings live in `~/.bolotype/settings.json`. Only set the keys you want to override — everything else uses the defaults shown below.

### LLM

```json
{
  "llm": {
    "base_url": "http://127.0.0.1:8000/v1",
    "model": "your-model-name",
    "api_key": "",
    "api_key_env": "OPENAI_API_KEY",
    "timeout_seconds": 20,
    "temperature": 0,
    "max_output_tokens": 1000
  }
}
```

| Key | Default | Description |
|---|---|---|
| `base_url` | `""` | OpenAI-compatible API base URL. E.g. `http://127.0.0.1:8000/v1` for a local server or `https://api.openai.com/v1` for OpenAI. |
| `model` | `""` | **Required.** Model name exactly as your server expects it. |
| `api_key` | `""` | API key value. Leave empty if your local server doesn't require one. |
| `api_key_env` | `"OPENAI_API_KEY"` | Name of the environment variable to read the key from. Takes precedence over `api_key`. |
| `timeout_seconds` | `20` | Seconds to wait for the LLM response before raising an error. |
| `temperature` | `0` | Generation temperature. `0` is deterministic and gives the most consistent edits. |
| `max_output_tokens` | `1000` | Maximum tokens in the polished response. |

### ASR

```json
{
  "asr": {
    "engine": "moonshine",
    "language": "en",
    "nemotron_model_id": "nvidia/nemotron-3.5-asr-streaming-0.6b",
    "nemotron_lookahead_tokens": 3,
    "nemotron_vad_threshold": 0.01,
    "nemotron_silence_duration_s": 1.25
  }
}
```

| Key | Default | Description |
|---|---|---|
| `engine` | `"moonshine"` | ASR engine to use. `"moonshine"` or `"nemotron"`. |
| `language` | `"en"` | Language code. Moonshine accepts `"en"`. Nemotron accepts locale codes such as `"en-US"`, `"de-DE"`, or `"auto"`. |
| `nemotron_model_id` | `"nvidia/nemotron-3.5-asr-streaming-0.6b"` | HuggingFace model ID for Nemotron. Downloaded automatically on first run. |
| `nemotron_lookahead_tokens` | `3` | Controls the streaming chunk size and right-context window. Supported values: `0` (80 ms), `1` (160 ms), `3` (320 ms), `6` (560 ms), `13` (1120 ms). Lower values reduce latency; higher values give the model more context. |
| `nemotron_vad_threshold` | `0.01` | RMS energy level that triggers speech onset detection. Increase if background noise causes false triggers; decrease if the first syllable is being clipped. |
| `nemotron_silence_duration_s` | `1.25` | Seconds of silence after speech ends before the utterance is submitted for transcription. Increase for slower or more deliberate speech. |

### Input

```json
{
  "input": {
    "backend": "auto",
    "append_space": true
  }
}
```

| Key | Default | Description |
|---|---|---|
| `backend` | `"auto"` | Keyboard injection backend. `"auto"` picks `xdotool` on X11 and `ydotool`/`wtype` on Wayland. Set explicitly if auto-detection is wrong. |
| `append_space` | `true` | Append a space after each inserted phrase so the next phrase starts cleanly. |

### Accessibility

```json
{
  "accessibility": {
    "max_text_characters": 12000
  }
}
```

| Key | Default | Description |
|---|---|---|
| `max_text_characters` | `12000` | Safety limit. Polish is refused for text spans larger than this. Prevents accidentally sending a very large document to the LLM. |

### Environment variables

All settings can also be set via environment variables, which take precedence over `settings.json`.

| Variable | Maps to |
|---|---|
| `BOLOTYPE_ASR_ENGINE` | `asr.engine` |
| `OPENAI_BASE_URL` | `llm.base_url` |
| `OPENAI_API_KEY` | `llm.api_key` |
| `VOICE_LLM_MODEL` | `llm.model` |
| `VOICE_LLM_TIMEOUT` | `llm.timeout_seconds` |
| `VOICE_LLM_TEMPERATURE` | `llm.temperature` |
| `VOICE_LLM_MAX_TOKENS` | `llm.max_output_tokens` |
| `BOLOTYPE_CONFIG_DIR` | Config directory (default: `~/.bolotype`) |

### Prompt customization

The LLM polish prompt lives at `~/.bolotype/system_prompt.txt` and is created by `bolotype install`. Edit it freely:

```bash
bolotype prompt-path          # prints the path
nano ~/.bolotype/system_prompt.txt
```

---

## Run

```bash
bolotype run --start-active
```

All subcommands:

```bash
bolotype install            # install system deps + create config
bolotype run                # start the daemon
bolotype toggle             # start/stop listening
bolotype polish             # polish entire focused field
bolotype polish-line        # polish current line
bolotype polish-paragraph   # polish current paragraph
bolotype polish-selection   # polish selected text
bolotype undo               # undo last polish
bolotype status             # show daemon status
bolotype shutdown           # stop the daemon
bolotype config-path        # print ~/.bolotype
bolotype prompt-path        # print ~/.bolotype/system_prompt.txt
```

For GNOME keyboard shortcuts, use the absolute path to the venv binary so the shortcut works outside a terminal session:

```bash
/path/to/bolotype/.venv/bin/bolotype toggle
```

---

## Replacement strategy

**Native GTK fields** (gedit, GNOME Text Editor, LibreOffice, terminals): AT-SPI `EditableText` writes the span directly.

**Browser/Electron fields** (Chrome, Electron apps): AT-SPI `Text.setSelection` selects the span, the polished text is placed on the clipboard via `xclip`/`wl-copy`, and `Ctrl+V` pastes it.

Fields exposing neither interface (password fields, some embedded widgets) are unsupported.

---

## Development

```bash
pip install -e ".[dev]"
python -m build
twine check dist/*
```

---

## Known issues

### Virtual environment

Ubuntu's `pyatspi` and `gi` packages are installed via the system package manager and are not available on PyPI. A normal isolated venv will not see them.

**Required:**

```bash
python3 -m venv --system-site-packages .venv
```

### Conda

Conda environments may be incompatible with Ubuntu's compiled `gi` bindings due to ABI differences. Recommended pattern: run BoloType in a system-Python venv; run external model servers (LMDeploy, vLLM) in their own conda environment and communicate over HTTP.

### Nemotron: GPU required

Nemotron 3.5 is loaded with `device_map="auto"` and has not been tested on CPU. A CUDA-capable GPU is strongly recommended. If you do not have a GPU, use the Moonshine engine instead.

### Nemotron: latency

Nemotron processes audio in streaming chunks but submits complete utterances for transcription. End-to-end latency depends on GPU speed and utterance length. Detailed benchmarking has not been done. Moonshine is lower latency on both CPU and GPU. You are encouraged to tune `nemotron_lookahead_tokens` and `nemotron_silence_duration_s` to match your hardware and speaking style.

### Browser and Electron accessibility

Chromium-based rich text editors may expose only an object-replacement placeholder (`U+FFFC`) via AT-SPI. BoloType searches the AT-SPI subtree for the real text node. If none is found, polish is unsupported for that field.

### Wayland

Input injection differs between compositors. X11 via `xdotool` is more reliable. Wayland requires `ydotool` or `wtype`.

### Rich text

Targeted replacement through accessibility APIs may flatten formatting or operate only on the exposed accessible node.

---

## License

MIT © 2026 Abdullah Baig
