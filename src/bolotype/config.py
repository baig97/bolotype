from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Settings dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LLMSettings:
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = "OPENAI_API_KEY"
    model: str | None = None
    timeout_seconds: float = 20.0
    temperature: float = 0.0
    max_output_tokens: int = 1000


@dataclass
class ASRSettings:
    language: str = "en"
    engine: str = "moonshine"
    nemotron_model_id: str = "nvidia/nemotron-3.5-asr-streaming-0.6b"
    nemotron_lookahead_tokens: int = 3
    nemotron_vad_threshold: float = 0.01
    nemotron_silence_duration_s: float = 1.25


@dataclass
class InputSettings:
    backend: str = "auto"
    append_space: bool = True


@dataclass
class AccessibilitySettings:
    max_text_characters: int = 12000


@dataclass
class Settings:
    llm: LLMSettings = field(default_factory=LLMSettings)
    asr: ASRSettings = field(default_factory=ASRSettings)
    input: InputSettings = field(default_factory=InputSettings)
    accessibility: AccessibilitySettings = field(default_factory=AccessibilitySettings)
    config_dir: Path = field(default_factory=lambda: Path.home() / ".bolotype")
    prompt_path: Path | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_config_dir() -> Path:
    env = os.environ.get("BOLOTYPE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".bolotype"


def get_prompt_path() -> Path:
    return get_config_dir() / "system_prompt.txt"


def _packaged_defaults_path() -> Path:
    return Path(__file__).parent / "resources" / "default_settings.json"


def _packaged_prompt_path() -> Path:
    return Path(__file__).parent / "resources" / "default_system_prompt.txt"


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        elif v not in (None, ""):
            result[k] = v
    return result


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_settings(cli_overrides: dict[str, Any] | None = None) -> Settings:
    config_dir = get_config_dir()

    # Start from packaged defaults
    raw = _load_json(_packaged_defaults_path())

    # Overlay user settings.json
    user_settings_path = config_dir / "settings.json"
    if user_settings_path.exists():
        raw = _deep_merge(raw, _load_json(user_settings_path))

    llm_raw = raw.get("llm", {})
    asr_raw = raw.get("asr", {})
    input_raw = raw.get("input", {})
    acc_raw = raw.get("accessibility", {})

    llm = LLMSettings(
        base_url=llm_raw.get("base_url") or None,
        api_key=llm_raw.get("api_key") or None,
        api_key_env=llm_raw.get("api_key_env") or "OPENAI_API_KEY",
        model=llm_raw.get("model") or None,
        timeout_seconds=float(llm_raw.get("timeout_seconds", 20.0)),
        temperature=float(llm_raw.get("temperature", 0.0)),
        max_output_tokens=int(llm_raw.get("max_output_tokens", 1000)),
    )
    asr = ASRSettings(
        language=asr_raw.get("language", "en"),
        engine=asr_raw.get("engine", "moonshine"),
        nemotron_model_id=asr_raw.get("nemotron_model_id", "nvidia/nemotron-3.5-asr-streaming-0.6b"),
        nemotron_lookahead_tokens=int(asr_raw.get("nemotron_lookahead_tokens", 3)),
        nemotron_vad_threshold=float(asr_raw.get("nemotron_vad_threshold", 0.01)),
        nemotron_silence_duration_s=float(asr_raw.get("nemotron_silence_duration_s", 0.8)),
    )
    inp = InputSettings(
        backend=input_raw.get("backend", "auto"),
        append_space=bool(input_raw.get("append_space", True)),
    )
    acc = AccessibilitySettings(
        max_text_characters=int(acc_raw.get("max_text_characters", 12000)),
    )

    # Apply environment overrides
    if os.environ.get("BOLOTYPE_ASR_ENGINE"):
        asr.engine = os.environ["BOLOTYPE_ASR_ENGINE"]
    if os.environ.get("OPENAI_BASE_URL"):
        llm.base_url = os.environ["OPENAI_BASE_URL"]
    if os.environ.get("VOICE_LLM_MODEL"):
        llm.model = os.environ["VOICE_LLM_MODEL"]
    if os.environ.get("VOICE_LLM_TIMEOUT"):
        llm.timeout_seconds = float(os.environ["VOICE_LLM_TIMEOUT"])
    if os.environ.get("VOICE_LLM_TEMPERATURE"):
        llm.temperature = float(os.environ["VOICE_LLM_TEMPERATURE"])
    if os.environ.get("VOICE_LLM_MAX_TOKENS"):
        llm.max_output_tokens = int(os.environ["VOICE_LLM_MAX_TOKENS"])

    # Apply CLI overrides
    if cli_overrides:
        if cli_overrides.get("llm_base_url"):
            llm.base_url = cli_overrides["llm_base_url"]
        if cli_overrides.get("llm_model"):
            llm.model = cli_overrides["llm_model"]
        if cli_overrides.get("llm_timeout") is not None:
            llm.timeout_seconds = cli_overrides["llm_timeout"]
        if cli_overrides.get("llm_temperature") is not None:
            llm.temperature = cli_overrides["llm_temperature"]
        if cli_overrides.get("llm_max_tokens") is not None:
            llm.max_output_tokens = cli_overrides["llm_max_tokens"]
        if cli_overrides.get("language"):
            asr.language = cli_overrides["language"]
        if cli_overrides.get("asr_engine"):
            asr.engine = cli_overrides["asr_engine"]
        if cli_overrides.get("backend"):
            inp.backend = cli_overrides["backend"]
        if cli_overrides.get("append_space") is not None:
            inp.append_space = cli_overrides["append_space"]
        if cli_overrides.get("max_polish_characters") is not None:
            acc.max_text_characters = cli_overrides["max_polish_characters"]

    # Resolve API key: cli → env var named in api_key_env → OPENAI_API_KEY → settings
    resolved_key = (
        (cli_overrides or {}).get("api_key")
        or (os.environ.get(llm.api_key_env) if llm.api_key_env else None)
        or os.environ.get("OPENAI_API_KEY")
        or llm.api_key
    )
    llm.api_key = resolved_key

    # Resolve prompt path
    prompt_path: Path | None = None
    if cli_overrides and cli_overrides.get("prompt_file"):
        prompt_path = Path(cli_overrides["prompt_file"])
    else:
        user_prompt = get_prompt_path()
        if user_prompt.exists():
            prompt_path = user_prompt
        else:
            prompt_path = _packaged_prompt_path()

    return Settings(
        llm=llm,
        asr=asr,
        input=inp,
        accessibility=acc,
        config_dir=config_dir,
        prompt_path=prompt_path,
    )
