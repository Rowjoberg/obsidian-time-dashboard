from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import cast

import yaml
from dateutil import parser as date_parser

from reporting.services.layout import (
    TaskLayout,
    hours_to_minutes,
    parse_timestamp,
)

WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]]+?)\]\]")
EMBED_RE = re.compile(r"!\[\[[^\]]+\]\]")
TAG_RE = re.compile(r"\s*(?:^|\s)#[\w/\-]+")


@dataclass
class WarningRecord:
    code: str
    message: str
    raw_line: str = ""
    line_number: int = 0


@dataclass
class ParsedTaskLine:
    raw_line: str
    raw_text: str
    display_title: str
    link_target: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_minutes: int | None = None
    has_valid_duration: bool = False
    warnings: list[WarningRecord] = field(default_factory=list)


@dataclass
class ParsedNote:
    frontmatter: dict[str, object]
    body: str
    content_hash: str


class NoteIndex:
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root
        self.relative_map: dict[str, Path] = {}
        self.basename_map: dict[str, list[Path]] = {}
        for path in vault_root.rglob("*.md"):
            if not path.is_file():
                continue
            relative = path.relative_to(vault_root)
            relative_key = self.normalize_key(str(relative.with_suffix("")).replace("\\", "/"))
            self.relative_map[relative_key] = path
            basename_key = self.normalize_key(path.stem)
            self.basename_map.setdefault(basename_key, []).append(path)

    @staticmethod
    def normalize_key(value: str) -> str:
        value = value.replace("\\", "/").strip()
        value = value.split("|", 1)[0]
        value = value.split("#", 1)[0]
        value = value.replace("\\]", "]").replace("]]", "]").strip(" []")
        return value.casefold()

    def resolve(self, target: str) -> tuple[Path | None, list[WarningRecord]]:
        warnings: list[WarningRecord] = []
        normalized = self.normalize_key(target)
        if not normalized:
            return None, warnings

        if normalized in self.relative_map:
            return self.relative_map[normalized], warnings

        basename = PurePosixPath(normalized).name
        matches = self.basename_map.get(basename, [])
        if len(matches) == 1:
            return matches[0], warnings
        if len(matches) > 1:
            warnings.append(
                WarningRecord(
                    code="ambiguous_link",
                    message=f"Ambiguous note target: {target}",
                )
            )
        return None, warnings


def parse_markdown_note(path: Path) -> ParsedNote:
    content = path.read_text(encoding="utf-8", errors="ignore")
    frontmatter: dict = {}
    body = content
    lines = content.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                raw_frontmatter = "\n".join(lines[1:index])
                try:
                    frontmatter = yaml.safe_load(raw_frontmatter) or {}
                except yaml.YAMLError:
                    frontmatter = fallback_frontmatter_parser(raw_frontmatter)
                if not isinstance(frontmatter, dict):
                    frontmatter = {}
                frontmatter = cast(dict[str, object], make_json_safe(frontmatter))
                if not isinstance(frontmatter, dict):
                    frontmatter = {}
                body = "\n".join(lines[index + 1 :])
                break

    return ParsedNote(
        frontmatter=frontmatter,
        body=body,
        content_hash=hashlib.sha1(content.encode("utf-8")).hexdigest(),
    )


def iter_task_lines(note_body: str, layout: TaskLayout | None = None) -> list[tuple[int, str]]:
    task_layout = layout or TaskLayout()
    identifier_regex = task_layout.identifier_regex
    task_lines = []
    for line_number, line in enumerate(note_body.splitlines(), start=1):
        if identifier_regex.match(line):
            task_lines.append((line_number, line.rstrip()))
    return task_lines


def parse_task_line(line: str, layout: TaskLayout | None = None) -> ParsedTaskLine:
    task_layout = layout or TaskLayout()
    stripped = task_layout.identifier_regex.sub("", line).strip()
    warnings: list[WarningRecord] = []

    start_match = task_layout.match_start(stripped)
    end_match = task_layout.match_end(stripped)
    hours_match = _find_hours(task_layout, stripped, (start_match, end_match))
    start_at = None
    end_at = None
    duration_minutes = None
    has_valid_duration = False

    raw_text = _extract_task_region(task_layout, stripped, start_match, end_match, hours_match)

    if start_match and end_match:
        try:
            start_at = parse_timestamp(start_match.group())
            end_at = parse_timestamp(end_match.group())
        except (ValueError, OverflowError):
            warnings.append(
                WarningRecord(
                    code="invalid_duration",
                    message="Task timestamps could not be read.",
                    raw_line=line,
                )
            )
            start_at = None
            end_at = None

    if task_layout.hours_mode:
        if hours_match:
            duration_minutes = hours_to_minutes(hours_match)
            if duration_minutes is None:
                warnings.append(
                    WarningRecord(
                        code="invalid_duration",
                        message="Hours value could not be converted to minutes.",
                        raw_line=line,
                    )
                )
            else:
                has_valid_duration = True
        else:
            warnings.append(
                WarningRecord(
                    code="missing_hours",
                    message="Task line does not include a value matching the hours pattern.",
                    raw_line=line,
                )
            )
    elif start_at and end_at:
        span_minutes = int((end_at - start_at).total_seconds() // 60)
        if span_minutes < 0 and task_layout.overnight_hours:
            span_minutes += 24 * 60
        duration_minutes = span_minutes
        if duration_minutes >= 0:
            has_valid_duration = True
        else:
            warnings.append(
                WarningRecord(
                    code="invalid_duration",
                    message="End timestamp is earlier than start timestamp.",
                    raw_line=line,
                )
            )
            duration_minutes = None
    else:
        warnings.append(
            WarningRecord(
                code="missing_timestamps",
                message="Task line does not include both start and end timestamps.",
                raw_line=line,
            )
        )

    if has_valid_duration and duration_minutes is not None:
        duration_minutes, has_valid_duration = _apply_duration_policy(duration_minutes, task_layout, line, warnings)

    link_target = ""
    for link_match in WIKILINK_RE.finditer(raw_text):
        link_target = sanitize_link_target(link_match.group(1))
        if link_target:
            break

    display_title = humanize_task_text(raw_text)
    if not display_title and link_target:
        display_title = title_from_target(link_target)
    if not display_title:
        display_title = "Untitled Task"

    return ParsedTaskLine(
        raw_line=line,
        raw_text=raw_text,
        display_title=display_title,
        link_target=link_target,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration_minutes,
        has_valid_duration=has_valid_duration,
        warnings=warnings,
    )


def _apply_duration_policy(
    duration_minutes: int,
    task_layout: TaskLayout,
    line: str,
    warnings: list[WarningRecord],
) -> tuple[int, bool]:
    """Round and floor a computed duration according to the configured policy."""
    if task_layout.round_duration_to > 0:
        step = task_layout.round_duration_to
        duration_minutes = int(round(duration_minutes / step) * step)
    if task_layout.min_duration_minutes and duration_minutes < task_layout.min_duration_minutes:
        warnings.append(
            WarningRecord(
                code="below_minimum_duration",
                message=(
                    f"Duration of {duration_minutes} minutes is below the configured "
                    f"minimum of {task_layout.min_duration_minutes}."
                ),
                raw_line=line,
            )
        )
        return None, False
    return duration_minutes, True


def _find_hours(
    task_layout: TaskLayout,
    stripped: str,
    claimed_matches: tuple[re.Match[str] | None, ...],
) -> re.Match[str] | None:
    """Find the hours value, ignoring anything already claimed by a timestamp.

    Without this a clock style pattern such as ``[H]:[M]`` happily matches the
    ``08:00`` inside a timestamp that is itself sitting on the same line.
    """
    hours_regex = task_layout.hours_regex
    if hours_regex is None:
        return None
    claimed = sorted((match.start(), match.end()) for match in claimed_matches if match is not None)
    for match in hours_regex.finditer(stripped):
        if any(match.start() < end and start < match.end() for start, end in claimed):
            continue
        return match
    return None


def _extract_task_region(
    task_layout: TaskLayout,
    stripped: str,
    start_match: re.Match[str] | None,
    end_match: re.Match[str] | None,
    hours_match: re.Match[str] | None,
) -> str:
    """Carve the task title out of the line using the configured task region."""
    region = task_layout.task_region

    if region == "before-start":
        cut_matches = [match for match in (start_match,) if match]
    else:
        cut_matches = [match for match in (start_match, end_match, hours_match) if match]

    raw_text = stripped
    if cut_matches:
        cut = min(cut_matches, key=lambda match: (match.start(), match.end()))
        raw_text = stripped[: cut.start()]

    if region == "title-only":
        raw_text = TAG_RE.sub("", raw_text)

    return raw_text.strip(" ,")


def sanitize_link_target(target: str) -> str:
    return target.split("|", 1)[0].split("#", 1)[0].replace("\\]", "]").strip(" []")


def title_from_target(target: str) -> str:
    return Path(sanitize_link_target(target)).name


def humanize_task_text(raw_text: str) -> str:
    cleaned = EMBED_RE.sub("", raw_text)
    cleaned = WIKILINK_RE.sub(lambda match: title_from_target(match.group(1)), cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,-")
    return cleaned


def infer_task_date(frontmatter: dict, fallback_name: str) -> date:
    date_value = frontmatter.get("date") or fallback_name
    return date_parser.parse(str(date_value)).date()


def note_family_from_relative_path(relative_path: str) -> str:
    path = PurePosixPath(relative_path.replace("\\", "/"))
    return path.parts[0] if path.parts else ""


def normalize_scalar(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def normalize_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    normalized = str(value).strip()
    return [normalized] if normalized else []


def make_json_safe(value):
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [make_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def fallback_frontmatter_parser(raw_frontmatter: str) -> dict[str, object]:
    result: dict[str, object] = {}
    current_key: str | None = None

    for raw_line in raw_frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key:
            existing = result.setdefault(current_key, [])
            if isinstance(existing, list):
                existing.append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            current_key = None
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            current_key = None
            continue
        if value == "":
            result[key] = []
        else:
            result[key] = value
        current_key = key

    return result
