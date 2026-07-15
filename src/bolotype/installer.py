from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


_APT_PACKAGES_X11 = [
    "python3-pyatspi",
    "python3-gi",
    "at-spi2-core",
    "xdotool",
    "xclip",
    "portaudio19-dev",
    "libportaudio2",
]

_APT_PACKAGES_WAYLAND = [
    "python3-pyatspi",
    "python3-gi",
    "at-spi2-core",
    "ydotool",
    "xclip",
    "portaudio19-dev",
    "libportaudio2",
]


def _packaged_resource(name: str) -> Path:
    return Path(__file__).parent / "resources" / name


def _install_python_extras(extra: str) -> None:
    # Detect editable install: pyproject.toml at repo root (src/bolotype -> src -> root)
    repo_root = Path(__file__).parent.parent.parent
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        spec = f".[{extra}]"
        cmd = [sys.executable, "-m", "pip", "install", "-e", spec]
        cwd = str(repo_root)
    else:
        spec = f"bolotype[{extra}]"
        cmd = [sys.executable, "-m", "pip", "install", spec]
        cwd = None
    print(f"\nInstalling Python packages: {spec}")
    subprocess.run(cmd, check=True, cwd=cwd)


def install(engine: str | None = None) -> None:
    # --- Platform check ---
    if sys.platform == "win32":
        print("BoloType: Windows integration is not supported yet.")
        return
    if sys.platform == "darwin":
        print("BoloType: macOS integration is not supported yet.")
        return
    if sys.platform != "linux":
        print(f"BoloType: Unsupported platform: {sys.platform}")
        return

    # --- Venv check ---
    if sys.prefix == sys.base_prefix:
        print(
            "\nWarning: BoloType is not running inside a virtual environment.\n"
            "\nRecommended setup:\n"
            "  python3 -m venv --system-site-packages .venv\n"
            "  source .venv/bin/activate\n"
            "  pip install bolotype\n"
            "  bolotype install\n"
        )

    # --- Install Python extras ---
    extra = engine or "all"
    _install_python_extras(extra)

    # --- Detect package manager ---
    if shutil.which("apt-get"):
        _install_apt()
    else:
        print(
            "\nApt not found. Please install the following packages manually "
            "using your distribution's package manager:\n"
        )
        for pkg in _APT_PACKAGES_X11:
            print(f"  {pkg}")
        print()

    # --- Create config directory ---
    _create_config_dir()

    print("\nBoloType installation complete.")
    print("Edit ~/.bolotype/settings.json to configure your LLM.")
    print("Edit ~/.bolotype/system_prompt.txt to customize the AI prompt.")


def _install_apt() -> None:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    packages = _APT_PACKAGES_WAYLAND if session == "wayland" else _APT_PACKAGES_X11

    print("\nBoloType will now install Linux system dependencies via apt-get.")
    print("This requires sudo. Packages to install:")
    for p in packages:
        print(f"  {p}")
    print()

    try:
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "install", "-y"] + packages, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"\napt-get failed: {exc}")
        print("You may need to install the packages manually.")


def _create_config_dir() -> None:
    from .config import get_config_dir, get_prompt_path

    config_dir = get_config_dir()
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    (config_dir / "logs").mkdir(exist_ok=True)
    (config_dir / "runtime").mkdir(exist_ok=True)

    settings_dest = config_dir / "settings.json"
    if settings_dest.exists():
        print(f"  preserved: {settings_dest}")
    else:
        shutil.copy(_packaged_resource("default_settings.json"), settings_dest)
        settings_dest.chmod(0o600)
        print(f"  created:   {settings_dest}")

    prompt_dest = get_prompt_path()
    if prompt_dest.exists():
        print(f"  preserved: {prompt_dest}")
    else:
        shutil.copy(_packaged_resource("default_system_prompt.txt"), prompt_dest)
        print(f"  created:   {prompt_dest}")
