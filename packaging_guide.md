# BoloType Packaging and Code Structure Guide

## 1. Packaging goal

BoloType should be distributed as a normal Python package using `pyproject.toml`.

The intended installation flow is:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate

pip install bolotype
bolotype install
bolotype run
```

Responsibilities should be split clearly:

* `pip install bolotype`

  * installs BoloType’s Python package and Python dependencies;
  * creates the `bolotype` command;
  * does not invoke `sudo`;
  * does not install Linux system packages.

* `bolotype install`

  * detects the current platform;
  * installs or guides installation of required OS-level dependencies;
  * creates the user configuration directory;
  * creates default configuration and prompt files;
  * validates that the installation is usable.

* `bolotype run`

  * starts the daemon;
  * checks required runtime dependencies before startup;
  * prints a clear installation command if something is missing.

For the first release, BoloType may officially support Ubuntu/Linux only. Windows and macOS should fail gracefully with a clear message rather than crashing on imports.

---

# 2. Recommended repository layout

Use a `src` layout:

```text
bolotype/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── scripts/
│   └── install_linux.sh
├── src/
│   └── bolotype/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── installer.py
│       ├── config.py
│       ├── daemon.py
│       ├── control.py
│       ├── editor.py
│       ├── llm.py
│       ├── commands.py
│       ├── accessibility/
│       │   ├── __init__.py
│       │   └── linux_atspi.py
│       ├── input/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── linux.py
│       └── resources/
│           ├── default_settings.json
│           └── default_system_prompt.txt
└── tests/
    ├── test_config.py
    ├── test_commands.py
    ├── test_llm.py
    ├── test_spans.py
    └── test_installer.py
```

The package directory should be named `bolotype`, matching the PyPI distribution name unless there is a strong reason not to.

---

# 3. Use relative imports inside the package

All internal package imports should use explicit relative imports.

Use:

```python
from .config import load_settings
from .editor import VoiceEditor
from .llm import TranscriptPolisher
from .accessibility.linux_atspi import LinuxAccessibilityBackend
```

Inside a subpackage:

```python
from ..config import Settings
from .base import InputBackend
```

Avoid imports such as:

```python
from config import load_settings
from voice_typing.editor import VoiceEditor
```

These commonly break after packaging because they depend on the current working directory or the old repository layout.

Absolute imports using the installed package name are also acceptable:

```python
from bolotype.config import load_settings
```

However, relative imports are recommended for internal modules because they survive package renaming and avoid accidentally importing an unrelated top-level package.

Imports should not rely on the user launching the program from the repository root.

The following commands must work from any directory:

```bash
bolotype run
python -m bolotype run
```

---

# 4. `pyproject.toml`

Use `pyproject.toml` as the only packaging configuration unless a legacy tool explicitly requires something else.

Recommended outline:

```toml
[build-system]
requires = ["setuptools>=77", "wheel"]
build-backend = "setuptools.build_meta"


[project]
name = "bolotype"
version = "0.1.0"
description = "System-wide local voice typing with AI-powered editing"
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"

authors = [
    { name = "Muhammad Abdullah Baig" }
]

classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: End Users/Desktop",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Multimedia :: Sound/Audio :: Speech",
]

dependencies = [
    "moonshine-voice",
    "openai>=1.0",
    "platformdirs>=4.0",
]


[project.optional-dependencies]
dev = [
    "build",
    "twine",
    "pytest",
    "ruff",
]


[project.scripts]
bolotype = "bolotype.cli:main"


[tool.setuptools]
package-dir = { "" = "src" }


[tool.setuptools.packages.find]
where = ["src"]


[tool.setuptools.package-data]
bolotype = [
    "resources/*.json",
    "resources/*.txt",
]
```

Do not list Ubuntu package names under Python dependencies.

Packages such as these are not pip dependencies:

```text
python3-pyatspi
python3-gi
at-spi2-core
xdotool
xclip
ydotool
portaudio19-dev
```

---

# 5. CLI architecture

Expose one root command:

```bash
bolotype
```

Recommended subcommands:

```text
bolotype install
bolotype run
bolotype start
bolotype stop
bolotype toggle
bolotype status
bolotype undo
bolotype polish-line
bolotype polish-paragraph
bolotype polish-all
bolotype polish-selection
bolotype config-path
bolotype prompt-path
```

The CLI should remain lightweight. Linux-specific modules should not be imported merely to display:

```bash
bolotype --help
```

The command dispatcher should import platform-specific functionality only when the corresponding command runs.

Conceptually:

```python
def main() -> None:
    args = parse_args()

    if args.command == "install":
        from .installer import install
        install()
        return

    if args.command == "run":
        from .daemon import run
        run()
        return
```

---

# 6. `bolotype install`

The install command handles post-pip setup.

It should perform these steps:

## 6.1 Detect the platform

For the first release:

```text
Linux:
    proceed

Windows:
    print that Windows integration is not supported yet

macOS:
    print that macOS integration is not supported yet
```

Use a clear colored error if Rich is retained, or ANSI output otherwise.

Do not let unsupported platforms fail with an obscure `ImportError`.

## 6.2 Detect the Linux distribution

Initially, support Ubuntu and Debian-family systems.

Read:

```text
/etc/os-release
```

If `apt-get` is available, use the Ubuntu/Debian installation path.

For unsupported Linux distributions, print the required components rather than attempting a guessed package-manager command.

## 6.3 Install system dependencies

The command may invoke:

```bash
sudo apt-get update
sudo apt-get install -y \
  python3-pyatspi \
  python3-gi \
  at-spi2-core \
  xdotool \
  xclip \
  portaudio19-dev
```

Wayland support may additionally require:

```bash
sudo apt-get install -y ydotool
```

The installer should explain that it is about to invoke `sudo` before doing so.

Do not invoke system installation during `pip install`. It should only happen after the user explicitly runs:

```bash
bolotype install
```

The system-package list should live in one place inside `installer.py`, not be duplicated across several scripts and README sections.

## 6.4 Check the Python environment

The installer should detect whether BoloType is running inside a virtual environment.

A practical check:

```python
inside_venv = sys.prefix != sys.base_prefix
```

If it is not inside a virtual environment, print a warning such as:

```text
BoloType is not running inside a virtual environment.

Recommended setup:

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install bolotype
bolotype install
```

The install command may continue after warning, but the README should strongly recommend a virtual environment.

Because `pyatspi` and `gi` are commonly installed through Ubuntu’s system Python packages, the recommended environment command should be:

```bash
python3 -m venv --system-site-packages .venv
```

This requirement should also appear under Known Issues.

## 6.5 Create the configuration directory

Use:

```text
~/.bolotype/
```

Initial structure:

```text
~/.bolotype/
├── settings.json
├── system_prompt.txt
├── logs/
└── runtime/
```

The installer should create missing files but never overwrite files the user has edited.

If the directory already exists:

* keep the existing configuration;
* add only missing default files;
* report which files were created or preserved.

---

# 7. Configuration design

Use `~/.bolotype/settings.json` as the main source of persistent settings.

Example:

```json
{
  "llm": {
    "base_url": "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
    "api_key": "",
    "api_key_env": "AWS_BEARER_TOKEN_BEDROCK",
    "model": "openai.gpt-oss-120b-1:0",
    "timeout_seconds": 20,
    "temperature": 0,
    "max_output_tokens": 1000
  },
  "asr": {
    "language": "en"
  },
  "input": {
    "backend": "auto",
    "append_space": true
  },
  "commands": {
    "polish_line": "polish this line",
    "polish_paragraph": "polish this paragraph",
    "polish_all": "polish everything",
    "polish_selection": "polish this selection",
    "undo": "undo that"
  },
  "accessibility": {
    "max_text_characters": 12000
  }
}
```

## Secrets

Avoid encouraging users to store secret API keys directly in `settings.json`.

Prefer:

```json
{
  "api_key_env": "AWS_BEARER_TOKEN_BEDROCK"
}
```

Then load the key from:

```bash
export AWS_BEARER_TOKEN_BEDROCK="..."
```

Direct `api_key` support may remain available for convenience, but:

* warn that the file contains a plaintext secret;
* create `settings.json` with user-only permissions where possible;
* do not print the key in logs;
* never include the user file in bug reports automatically.

Recommended permissions:

```text
~/.bolotype              0700
~/.bolotype/settings.json 0600
```

---

# 8. Environment-variable loading

Use a clear precedence order.

Recommended order, from highest priority to lowest:

1. Command-line arguments
2. Process environment variables
3. `~/.bolotype/settings.json`
4. Packaged defaults

For example:

```text
--llm-model command-line argument
VOICE_LLM_MODEL environment variable
settings.json llm.model
built-in default
```

Suggested environment variables:

```text
OPENAI_API_KEY
OPENAI_BASE_URL
VOICE_LLM_MODEL
VOICE_LLM_TIMEOUT
VOICE_LLM_TEMPERATURE
VOICE_LLM_MAX_TOKENS
BOLOTYPE_CONFIG_DIR
```

`AWS_BEARER_TOKEN_BEDROCK` may be supported as a fallback API-key variable.

Recommended API-key lookup:

```python
api_key = (
    cli_api_key
    or os.environ.get(configured_api_key_env)
    or os.environ.get("OPENAI_API_KEY")
    or settings.llm.api_key
)
```

The package should not depend on a `.env` file in the current working directory.

That behavior is unreliable after PyPI installation because users may launch BoloType from any directory.

A `.env` file may optionally be supported at:

```text
~/.bolotype/.env
```

However, `settings.json` plus environment variables is cleaner. Avoid introducing `.env` support unless it provides a real benefit.

The daemon should always resolve configuration through a central configuration loader rather than calling `os.environ` throughout the codebase.

---

# 9. Central configuration loader

Create:

```text
src/bolotype/config.py
```

Responsibilities:

* resolve the config directory;
* create paths;
* load packaged defaults;
* load `settings.json`;
* apply environment overrides;
* apply CLI overrides;
* validate required fields;
* return a typed settings object.

Use dataclasses or typed models:

```python
@dataclass
class LLMSettings:
    base_url: str | None
    api_key: str | None
    api_key_env: str | None
    model: str | None
    timeout_seconds: float
    temperature: float
    max_output_tokens: int
```

All modules should receive settings explicitly rather than independently rereading files.

Prefer:

```python
settings = load_settings(cli_overrides)
daemon = VoiceDaemon(settings)
```

Avoid hidden global configuration state.

---

# 10. System prompt

Store the user-editable prompt at:

```text
~/.bolotype/system_prompt.txt
```

The packaged default lives at:

```text
src/bolotype/resources/default_system_prompt.txt
```

During `bolotype install`:

* copy the packaged prompt if the user prompt does not exist;
* never overwrite an existing prompt;
* mention its path after setup.

At runtime:

1. use the explicit CLI prompt path if supplied;
2. otherwise use `~/.bolotype/system_prompt.txt`;
3. if it is missing, fall back to the packaged default.

Recommended lookup:

```text
--prompt-file
~/.bolotype/system_prompt.txt
packaged default
```

Provide:

```bash
bolotype prompt-path
```

which prints:

```text
/home/user/.bolotype/system_prompt.txt
```

This makes prompt customization discoverable without adding a UI.

---

# 11. Runtime dependency checks

Do not create a separate doctor command.

Before starting Linux integration, check required dependencies.

Examples:

```python
import shutil

required_commands = [
    "xdotool",
    "xclip",
]
```

Lazy-check imports:

```python
try:
    import pyatspi
except ImportError:
    ...
```

If something is missing, show:

```text
BoloType Linux integration is not installed.

Run:

    bolotype install
```

Optionally include the exact missing dependency:

```text
Missing Python module: pyatspi
Missing command: xclip
```

Do not emit a long traceback for expected missing-platform dependencies.

The runtime check should happen before:

* microphone startup;
* model loading;
* daemon initialization.

This prevents users from waiting for the ASR model to load before seeing a basic dependency error.

---

# 12. Lazy platform imports

Platform-specific imports should remain inside platform-specific modules or factories.

Avoid this at top-level package import:

```python
import pyatspi
```

Instead:

```python
def create_linux_accessibility_backend():
    try:
        import pyatspi
    except ImportError as exc:
        raise MissingSystemDependency(
            "pyatspi is unavailable. Run `bolotype install`."
        ) from exc

    from .accessibility.linux_atspi import LinuxAccessibilityBackend
    return LinuxAccessibilityBackend()
```

The same principle applies later to:

* Windows UI Automation packages;
* macOS accessibility bindings;
* Linux input-injection libraries.

This allows:

```bash
bolotype --help
bolotype install
bolotype config-path
```

to work even when desktop integration dependencies are missing.

---

# 13. Input and accessibility architecture

Even though the first version is Linux-only, isolate Linux integration from core behavior.

Recommended conceptual separation:

```text
Moonshine ASR
    ↓
Voice command parser
    ↓
Editing controller
    ├── polish line
    ├── polish paragraph
    ├── polish selection
    ├── polish all
    └── undo
    ↓
Linux accessibility and input backends
```

Core modules should not import `pyatspi` directly.

For example:

```text
commands.py
editor.py
llm.py
```

should remain platform-independent.

Linux-specific details belong under:

```text
accessibility/linux_atspi.py
input/linux.py
```

This makes future Windows and macOS work possible without prematurely designing a full shared API.

---

# 14. Console scripts instead of shell wrappers

After PyPI installation, use the `bolotype` entry point rather than requiring shell scripts.

Replace:

```text
run_daemon.sh
voice-toggle.sh
voice-undo.sh
voice-polish.sh
```

with:

```bash
bolotype run
bolotype toggle
bolotype undo
bolotype polish-paragraph
```

Shell scripts may remain in the GitHub repository for development or desktop integration, but they should not be the primary user interface.

GNOME shortcuts can invoke:

```bash
/path/to/venv/bin/bolotype toggle
```

or, when the environment is already properly exposed:

```bash
bolotype toggle
```

Document that desktop shortcuts may require an absolute path to the installed console command.

---

# 15. README installation instructions

Keep the main path short.

## Ubuntu setup

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate

pip install bolotype
bolotype install
```

Configure:

```bash
nano ~/.bolotype/settings.json
nano ~/.bolotype/system_prompt.txt
```

Run:

```bash
bolotype run --start-active
```

The README should clearly explain:

* `pip install` installs the Python package;
* `bolotype install` installs Linux integrations and creates configuration;
* the virtual environment should use `--system-site-packages`;
* API keys are preferably read from environment variables;
* settings live under `~/.bolotype`.

---

# 16. Known issues section

Include at least these points:

## Virtual environments

Ubuntu’s `pyatspi` and `gi` packages are installed through the system package manager. A normal isolated virtual environment may not see them.

Recommended:

```bash
python3 -m venv --system-site-packages .venv
```

## Conda

Conda environments may be incompatible with Ubuntu’s compiled `gi` bindings because they can use a different Python ABI.

Recommended:

* run BoloType in a system-Python virtual environment;
* run external model servers such as LMDeploy in their own Conda environment;
* communicate over HTTP.

## Browser and Electron accessibility

Chromium-based rich text editors may expose incomplete or nested AT-SPI text models. BoloType may use selection and clipboard-based replacement where direct `EditableText` support is unavailable.

## Wayland

Input injection support differs between compositors. X11 through `xdotool` may be more reliable initially. Wayland may require `ydotool` or another supported backend.

## Rich text

Targeted replacement through accessibility APIs may flatten formatting or operate on only the exposed accessible node.

---

# 17. Build and release process

Development installation:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Build:

```bash
python -m build
```

Validate:

```bash
twine check dist/*
```

Test the wheel in a clean environment:

```bash
python3 -m venv --system-site-packages /tmp/bolotype-test
source /tmp/bolotype-test/bin/activate

pip install dist/bolotype-0.1.0-py3-none-any.whl
bolotype --help
bolotype install
```

Publish to TestPyPI before production PyPI.

---

# 18. Recommended implementation order

1. Move the package under `src/bolotype`.
2. Convert internal imports to relative imports.
3. Add `pyproject.toml`.
4. Add the `bolotype` console entry point.
5. Consolidate shell-script behavior into CLI subcommands.
6. Add the central configuration loader.
7. Add `~/.bolotype/settings.json`.
8. Add `~/.bolotype/system_prompt.txt`.
9. Add `bolotype install`.
10. Add lightweight runtime dependency checks.
11. Lazy-load `pyatspi` and other platform-specific modules.
12. Build and test the wheel in a clean environment.
13. Update the README and Known Issues.
14. Publish first to TestPyPI.

---

# 19. Guiding principles

* Pip installs Python packages.
* `bolotype install` handles explicit OS integration.
* Runtime checks should fail clearly, not with stack traces.
* User configuration must not depend on the working directory.
* Persistent files belong in `~/.bolotype`.
* Secrets should preferably come from environment variables.
* User-edited prompt and settings files must never be overwritten.
* Platform-specific imports must be lazy.
* Internal imports must be relative or package-qualified.
* Shell scripts should not be required after PyPI installation.
* Keep version one Linux-focused rather than prematurely building cross-platform abstractions.
