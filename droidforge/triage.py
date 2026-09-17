"""AI-assisted crash triage via Claude API.

Takes a CrashEvent + recent log context, asks Claude Opus 4.7 for a
root-cause hypothesis and suggested next steps. Streams the response so
long outputs don't hit HTTP timeouts.

Design notes:
    - System prompt is large + stable -> wrapped in cache_control to cut
      cost ~90% on repeated triage calls in same session.
    - Adaptive thinking + effort=high -> Claude decides depth, no manual
      budget tuning.
    - Streaming + get_final_message() -> safe for any response size.
    - Caller supplies recent log lines as context (tail buffer).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable, Iterator

from .logcat import CrashEvent

_LOG = logging.getLogger(__name__)
_MODEL = "claude-opus-4-7"
_MAX_TOKENS = 16000
# Cap log context so we don't blow past sensible token budgets on chatty apps.
_CONTEXT_LINE_CAP = 200

_SYSTEM_PROMPT = """You are a senior Android engineer triaging a crash report \
captured by DroidForge, a local Android testing engine. You have access to:
1. The crash event the engine flagged (severity, tag, message, timestamp)
2. The most recent logcat lines leading up to the crash (chronological order)

Your job is to produce, in this order:

## Hypothesis
One paragraph: most likely root cause, in plain engineering language. \
Cite specific log lines (by tag + key tokens) that support your guess. \
If multiple causes are plausible, rank them.

## Why this is happening
Explain the failure mode at the level a developer needs to fix it. Reference \
Android subsystems where relevant (lifecycle, ART, Binder, view hierarchy, \
Dalvik/native bridge, etc.).

## Suggested next steps
A short numbered list. Concrete actions the developer can take *right now* \
in their codebase or testing setup. Order by leverage (highest-impact first).

## Confidence
Low / Medium / High, one line of reasoning.

Constraints:
- Be terse. Skip preamble like "Based on the logs..." or "Looking at this...".
- Don't hedge with "could be" five times. Pick the most likely cause.
- If the logs don't contain enough info, say so explicitly under Hypothesis \
and request what additional info you'd need.
- Use markdown headings as shown above so the GUI can render them.
"""


@dataclass(frozen=True)
class TriageResult:
    """Final output of one triage call."""
    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0


class TriageError(RuntimeError):
    """Raised when Claude API is unreachable or unconfigured."""


def _build_user_message(event: CrashEvent, context_lines: list[str]) -> str:
    """Render the per-call user payload. Volatile, post-cache-breakpoint."""
    lines_block = "\n".join(context_lines[-_CONTEXT_LINE_CAP:])
    return (
        f"## Crash Event\n"
        f"- Severity: {event.severity.value}\n"
        f"- Detected at: {event.detected_at.isoformat()}\n"
        f"- Tag: {event.line.tag}\n"
        f"- Level: {event.line.level}\n"
        f"- PID/TID: {event.line.pid}/{event.line.tid}\n"
        f"- Message: {event.line.message}\n\n"
        f"## Recent logcat (chronological, oldest first)\n"
        f"```\n{lines_block}\n```\n"
    )


def is_configured() -> bool:
    """True if ANTHROPIC_API_KEY is set in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def triage(
    event: CrashEvent,
    context_lines: list[str],
    *,
    on_token: Callable[[str], None] | None = None,
) -> TriageResult:
    """Run Claude triage on a crash. Returns the final TriageResult.

    `on_token` (optional): called on each streamed text chunk so the GUI
    can show a live "typing" indicator. Safe from any thread.

    Raises TriageError if API key missing or call fails.
    """
    if not is_configured():
        raise TriageError(
            "ANTHROPIC_API_KEY not set. Export it and restart, or run "
            "`droidforge` without triage to skip AI assistance."
        )

    # Lazy import: keeps anthropic out of CLI startup cost when triage unused.
    try:
        import anthropic
    except ImportError as e:
        raise TriageError(f"anthropic SDK not installed: {e}") from e

    client = anthropic.Anthropic()
    user_text = _build_user_message(event, context_lines)

    try:
        with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            # System prompt is the cache anchor: stable across calls in
            # the same session, so we pay full price once then ~10% on
            # every later triage in the next 5 minutes.
            system=[{
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            if on_token is not None:
                for chunk in stream.text_stream:
                    try:
                        on_token(chunk)
                    except Exception:  # noqa: BLE001 - never let UI bug kill stream
                        _LOG.exception("on_token callback raised")
            final = stream.get_final_message()
    except anthropic.APIStatusError as e:
        raise TriageError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise TriageError(f"Claude API connection failed: {e}") from e

    text = "".join(b.text for b in final.content if b.type == "text")
    usage = final.usage
    return TriageResult(
        text=text,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_creation_tokens=usage.cache_creation_input_tokens or 0,
    )


def stream_triage(
    event: CrashEvent,
    context_lines: list[str],
) -> Iterator[str]:
    """Generator variant: yields text chunks as they arrive.

    Useful for CLI `tail` mode where you want to print tokens as they come.
    Caller drives the loop; doesn't need to manage callbacks.
    """
    chunks: list[str] = []

    def collect(s: str) -> None:
        chunks.append(s)

    # Run triage synchronously, but yield from the buffer as it fills.
    # Note: this is a simple sync generator; for true real-time streaming
    # in async code, refactor to AsyncAnthropic. Keeping sync for now
    # because the engine's event loop is tk-driven, not asyncio.
    result = triage(event, context_lines, on_token=collect)
    for c in chunks:
        yield c
    # Trailing usage summary
    yield (
        f"\n\n[tokens: in={result.input_tokens} out={result.output_tokens} "
        f"cache_read={result.cache_read_tokens}]"
    )
