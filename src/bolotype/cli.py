from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


_CONTROL_COMMANDS = {
    "start", "stop", "toggle", "undo", "status", "shutdown",
    "polish", "polish-line", "polish-paragraph", "polish-all", "polish-selection",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bolotype",
        description="BoloType — system-wide voice typing with AI-powered editing",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("install", help="Install Linux system dependencies and create config files")
    sub.add_parser("config-path", help="Print the config directory path")
    sub.add_parser("prompt-path", help="Print the system prompt file path")

    # run subcommand
    run_p = sub.add_parser("run", help="Start the BoloType daemon")
    run_p.add_argument("--start-active", action="store_true", help="Begin listening immediately")
    run_p.add_argument("--language", default=None)
    run_p.add_argument("--asr-engine", choices=["moonshine", "nemotron"], default=None)
    run_p.add_argument("--backend", choices=["auto", "xdotool", "ydotool", "wtype"], default=None)
    run_p.add_argument("--no-append-space", action="store_true")
    run_p.add_argument("--command-prefix", default="")
    run_p.add_argument("--llm-model", default=None)
    run_p.add_argument("--llm-base-url", default=None)
    run_p.add_argument("--llm-timeout", type=float, default=None)
    run_p.add_argument("--llm-temperature", type=float, default=None)
    run_p.add_argument("--llm-max-tokens", type=int, default=None)
    run_p.add_argument("--prompt-file", type=Path, default=None)
    run_p.add_argument("--llm-fail-closed", action="store_true")
    run_p.add_argument("--max-polish-characters", type=int, default=None)
    run_p.add_argument("--socket", type=Path, default=None)

    # control subcommands
    for name in sorted(_CONTROL_COMMANDS):
        sub.add_parser(name, help=f"Send '{name}' to the running daemon")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "install":
        from .installer import install
        install()
        return

    if args.command == "config-path":
        from .config import get_config_dir
        print(get_config_dir())
        return

    if args.command == "prompt-path":
        from .config import get_prompt_path
        print(get_prompt_path())
        return

    if args.command == "run":
        from .config import load_settings
        from .daemon import run_daemon

        cli_overrides: dict = {}
        if args.language:
            cli_overrides["language"] = args.language
        if args.asr_engine:
            cli_overrides["asr_engine"] = args.asr_engine
        if args.backend:
            cli_overrides["backend"] = args.backend
        if args.llm_model:
            cli_overrides["llm_model"] = args.llm_model
        if args.llm_base_url:
            cli_overrides["llm_base_url"] = args.llm_base_url
        if args.llm_timeout is not None:
            cli_overrides["llm_timeout"] = args.llm_timeout
        if args.llm_temperature is not None:
            cli_overrides["llm_temperature"] = args.llm_temperature
        if args.llm_max_tokens is not None:
            cli_overrides["llm_max_tokens"] = args.llm_max_tokens
        if args.max_polish_characters is not None:
            cli_overrides["max_polish_characters"] = args.max_polish_characters
        if args.no_append_space:
            cli_overrides["append_space"] = False
        if args.prompt_file:
            cli_overrides["prompt_file"] = args.prompt_file

        settings = load_settings(cli_overrides)
        run_daemon(
            settings,
            start_active=args.start_active,
            socket_path=args.socket,
            command_prefix=args.command_prefix,
            llm_fail_open=not args.llm_fail_closed,
        )
        return

    if args.command in _CONTROL_COMMANDS:
        from .control import send_action
        send_action(args.command)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
