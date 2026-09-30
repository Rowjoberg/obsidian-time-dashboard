"""Compiles user-authored task layout patterns into matchers.

Patterns are plain text with a few tokens so they stay readable in the admin:

    🛫 YYYY-MM-DD HH:mm     a start timestamp marker
    [hours]\\s*h\\b|[H]:[M]\\b  a duration

Tokens are substituted and everything else is treated as a regular expression
fragment, so alternation and character classes are available too. A bad pattern
is reported by ``validate_layout`` rather than escaping as a crash at import time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from dateutil import parser as date_parser

DATETIME_TOKENS = {
    "YYYY": r"\d{4}",
    "YY": r"\d{2}",
    "MM": r"\d{1,2}",
    "DD": r"\d{1,2}",
    "HH": r"\d{1,2}",
    "mm": r"\d{1,2}",
}

HOURS_TOKENS = {
    "hours": r"(?P<hours>\d+(?:[.,]\d+)?)",
    "H": r"(?P<H>\d{1,2})",
    "M": r"(?P<M>\d{1,2})",
}

DEFAULT_IDENTIFIER = "- [t]"
DEFAULT_TASK_REGION = "after-identifier"
DEFAULT_HOURS_PATTERN = r"[hours]\s*h\b|[H]:[M]\b"
DEFAULT_START_TIME_PATTERN = "🛫 YYYY-MM-DD HH:mm"
DEFAULT_END_TIME_PATTERN = "📅 YYYY-MM-DD HH:mm"

TASK_REGION_CHOICES = [
    (DEFAULT_TASK_REGION, "Everything after the identifier"),
    ("before-start", "Text before the start-time marker"),
    ("title-only", "Text only, dropping trailing metadata"),
]


class LayoutError(ValueError):
    """Raised when a configured pattern cannot be compiled."""


@dataclass(frozen=True)
class TaskLayout:
    identifier: str = DEFAULT_IDENTIFIER
    task_region: str = DEFAULT_TASK_REGION
    hours_mode: bool = False
    hours_pattern: str = DEFAULT_HOURS_PATTERN
    start_time_pattern: str = DEFAULT_START_TIME_PATTERN
    end_time_pattern: str = DEFAULT_END_TIME_PATTERN
    round_duration_to: int = 0
    min_duration_minutes: int = 0
    overnight_hours: bool = False

    @classmethod
    def from_config(cls, config) -> TaskLayout:
        if config is None:
            return cls()
        return cls(
            identifier=config.identifier or DEFAULT_IDENTIFIER,
            task_region=config.task_region or DEFAULT_TASK_REGION,
            hours_mode=bool(config.hours_mode),
            hours_pattern=config.hours_pattern or DEFAULT_HOURS_PATTERN,
            start_time_pattern=config.start_time_pattern or DEFAULT_START_TIME_PATTERN,
            end_time_pattern=config.end_time_pattern or DEFAULT_END_TIME_PATTERN,
            round_duration_to=int(getattr(config, "round_duration_to", 0) or 0),
            min_duration_minutes=int(getattr(config, "min_duration_minutes", 0) or 0),
            overnight_hours=bool(getattr(config, "overnight_hours", False)),
        )

    @property
    def identifier_regex(self) -> re.Pattern[str]:
        return re.compile(rf"^{re.escape(self.identifier)}\s*")

    @property
    def start_regex(self) -> re.Pattern[str] | None:
        return _safe_compile(self.start_time_pattern, DATETIME_TOKENS)

    @property
    def end_regex(self) -> re.Pattern[str] | None:
        return _safe_compile(self.end_time_pattern, DATETIME_TOKENS)

    @property
    def hours_regex(self) -> re.Pattern[str] | None:
        if not self.hours_mode:
            return None
        return _safe_compile(self.hours_pattern, HOURS_TOKENS)

    def match_start(self, text: str) -> re.Match[str] | None:
        return _search(self.start_regex, text)

    def match_end(self, text: str) -> re.Match[str] | None:
        return _search(self.end_regex, text)

    def match_hours(self, text: str) -> re.Match[str] | None:
        return _search(self.hours_regex, text)


def tokenize(pattern: str, tokens: dict[str, str]):
    """Yield ``(kind, value)`` pairs of ``token``/``literal`` from a pattern.

    Tokens may be written bare (``YYYY-MM-DD``) or bracketed (``[YYYY]-[MM]``).
    A bare token is only recognised when it is not followed by a letter, so a
    literal word such as ``Done`` is never mistaken for a day token.
    """
    ordered = sorted(tokens, key=len, reverse=True)
    index = 0
    buffer: list[str] = []
    while index < len(pattern):
        if pattern[index] == "[":
            closing = pattern.find("]", index)
            name = pattern[index + 1 : closing] if closing != -1 else ""
            if closing != -1 and name in tokens:
                if buffer:
                    yield "literal", "".join(buffer)
                    buffer = []
                yield "token", name
                index = closing + 1
                continue
        bare = _match_bare_token(pattern, index, ordered)
        if bare:
            if buffer:
                yield "literal", "".join(buffer)
                buffer = []
            yield "token", bare
            index += len(bare)
            continue
        buffer.append(pattern[index])
        index += 1
    if buffer:
        yield "literal", "".join(buffer)


def _match_bare_token(pattern: str, index: int, ordered: list[str]) -> str | None:
    for name in ordered:
        if not pattern.startswith(name, index):
            continue
        following = pattern[index + len(name) : index + len(name) + 1]
        if following.isalpha():
            continue
        return name
    return None


def compile_pattern(pattern: str, tokens: dict[str, str]) -> str:
    """Turn a token pattern into a regular expression source string.

    Tokens are substituted; everything else is passed through untouched so
    users can use alternation, character classes and escapes in their patterns.
    """
    parts = []
    for kind, value in tokenize(pattern or "", tokens):
        parts.append(tokens[value] if kind == "token" else value)
    if not parts:
        raise LayoutError("Pattern is empty.")
    return "".join(parts)


def hours_to_minutes(match: re.Match[str]) -> int | None:
    """Convert a matched hours pattern into whole minutes."""
    hours = match.groupdict().get("hours")
    if hours:
        return int(round(float(hours.replace(",", ".")) * 60))
    hour_part = match.groupdict().get("H")
    if hour_part:
        minute_part = match.groupdict().get("M") or 0
        return int(hour_part) * 60 + int(minute_part)
    return None


def parse_timestamp(value: str) -> datetime:
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = re.sub(r"^[^\d]+", "", cleaned)
    return date_parser.parse(cleaned)


def validate_layout(identifier: str, start: str, end: str, hours: str) -> list[str]:
    """Return a list of human readable problems with the configured patterns."""
    problems = []
    if not (identifier or "").strip():
        problems.append("Identifier cannot be empty.")
    for label, pattern in (("Start-time", start), ("End-time", end), ("Hours", hours)):
        if not (pattern or "").strip():
            problems.append(f"{label} pattern cannot be empty.")
            continue
        try:
            compiled = compile_pattern(pattern, HOURS_TOKENS if label == "Hours" else DATETIME_TOKENS)
        except LayoutError as exc:
            problems.append(f"{label} pattern is invalid: {exc}")
            continue
        try:
            re.compile(compiled)
        except re.error as exc:
            problems.append(f"{label} pattern is invalid: {exc}")
    return problems


def _safe_compile(pattern: str, tokens: dict[str, str]) -> re.Pattern[str] | None:
    if not (pattern or "").strip():
        return None
    try:
        return re.compile(compile_pattern(pattern, tokens))
    except (LayoutError, re.error):
        return None


def _search(regex: re.Pattern[str] | None, text: str) -> re.Match[str] | None:
    if regex is None:
        return None
    return regex.search(text)
