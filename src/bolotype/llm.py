from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol

DEFAULT_SYSTEM_PROMPT = """You are the transcript-cleaning layer of a real-time dictation application.

Transform the raw ASR transcript into the exact text the user intended to insert at the cursor.

Rules:
- Preserve the user's meaning, tone, language, and level of formality.
- Fix punctuation, capitalization, obvious ASR mistakes, repetitions, filler words, and natural self-corrections.
- When the speaker corrects themselves (for example, 'Thursday, no, Friday'), keep the corrected intent only.
- Preserve technical identifiers and conventional casing when context makes them clear, such as useEffect, PyTorch, NumPy, OpenAI, and RTX 4090.
- Preserve mixed-language and Roman Urdu text rather than translating it.
- Convert clearly dictated symbols and compact expressions when unambiguous, but do not mathematically or factually correct the user.
- Do not add facts or wording that were not spoken.
- If the transcript is already clean, return it unchanged.

Return only the polished transcript.

Do not include reasoning, analysis, explanations, XML tags, labels, preambles,
or quotation marks. Your entire response must be the final replacement text.
"""



class ChatCompletionsClient(Protocol):
    class _Chat(Protocol):
        class _Completions(Protocol):
            def create(self, **kwargs): ...

        completions: _Completions

    chat: _Chat


@dataclass(frozen=True)
class LLMConfig:
    model: str
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 12.0
    temperature: float = 0.0
    max_output_tokens: int = 300
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


class TranscriptPolisher:
    """Polishes finalized ASR segments through an OpenAI-compatible endpoint."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        client: ChatCompletionsClient | None = None,
    ) -> None:
        self.config = config
        if client is not None:
            self.client = client
            return

        # The OpenAI client requires a non-empty API key even for local servers
        # that ignore authentication.
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The OpenAI Python package is missing or too old. "
                "Run: pip install --upgrade 'openai>=1.0'"
            ) from exc

        api_key = config.api_key or os.environ.get("OPENAI_API_KEY") or "not-needed"
        kwargs: dict = {
            "api_key": api_key,
            "timeout": config.timeout_seconds,
            "max_retries": 0,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self.client = OpenAI(**kwargs)

    def polish(self, transcript: str, *, recent_context: str = "") -> str:
        transcript = transcript.strip()
        if not transcript:
            return transcript

        user_content = f"Raw transcript:\n{transcript}"
        if recent_context.strip():
            user_content = (
                "Recent text inserted immediately before this segment "
                "(context only; do not repeat it):\n"
                f"{recent_context.strip()}\n\n"
                f"Raw transcript:\n{transcript}"
            )

        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_output_tokens,
        )

        if not response.choices:
            raise RuntimeError(f"LLM returned no choices (response: {response})")

        content = response.choices[0].message.content
        print(f"[LLM raw response] {content!r}", flush=True)
        if not isinstance(content, str):
            raise RuntimeError("LLM returned no text content")

        cleaned = self._clean_model_output(content)
        print(f"[LLM cleaned] {cleaned!r}", flush=True)
        if not cleaned:
            raise RuntimeError("LLM returned an empty transcript")
        return cleaned

    @staticmethod
    def _clean_model_output(text: str) -> str:
        text = text.strip()

        # Strip reasoning/thinking blocks emitted by chain-of-thought models
        # (e.g. DeepSeek-R1). Keep only what follows the closing tag.
        text = re.sub(r"<(?:reasoning|thinking)>.*?</(?:reasoning|thinking)>", "", text, flags=re.DOTALL)
        text = text.strip()

        # Some otherwise compatible models ignore the 'text only' instruction.
        fenced = re.fullmatch(r"```(?:text|plaintext)?\s*(.*?)\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()

        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1].strip()

        return text
