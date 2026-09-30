from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reporting.models import (
    ParseWarning,
    SourceNote,
    TaskEntry,
    TaskEntryFacet,
    TaskLayoutConfig,
)
from reporting.services.layout import TaskLayout
from reporting.services.notes import (
    NoteIndex,
    WarningRecord,
    infer_task_date,
    iter_task_lines,
    normalize_list,
    normalize_scalar,
    note_family_from_relative_path,
    parse_markdown_note,
    parse_task_line,
)
from reporting.services.roles import date_key, role_config, week_key
from reporting.services.settings_store import get_config


@dataclass(frozen=True)
class ImportPolicy:
    """Import behaviour that depends on configuration rather than line layout."""

    roles: dict[str, dict[str, str]] = field(default_factory=dict)
    date_key: str = "date"
    week_key: str = "week"
    resolved_when: str = TaskLayoutConfig.ResolvedWhen.LINK_RESOLVED
    completed_identifier: str = "- [x]"
    resolved_tag: str = ""
    resolved_field: str = ""
    resolved_value: str = ""
    ignored_keys: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config) -> ImportPolicy:
        return cls(
            roles=role_config(config),
            date_key=date_key(config),
            week_key=week_key(config),
            resolved_when=config.resolved_when,
            completed_identifier=config.completed_identifier or "",
            resolved_tag=config.resolved_tag or "",
            resolved_field=config.resolved_field or "",
            resolved_value=config.resolved_value or "",
            ignored_keys=tuple(config.ignored_keys()),
        )

    def frontmatter_value(self, frontmatter: dict, role_name: str) -> str:
        role = self.roles.get(role_name) or {}
        return normalize_scalar(frontmatter.get(role.get("source", "")))

    def column_values(self, frontmatter: dict) -> dict[str, str]:
        values = {role["column"]: self.frontmatter_value(frontmatter, name) for name, role in self.roles.items()}
        return {column: value for column, value in values.items() if value}

    def is_resolved(self, line: str, linked_frontmatter: dict, link_resolved: bool) -> bool:
        if self.resolved_when == TaskLayoutConfig.ResolvedWhen.LINK_RESOLVED:
            return link_resolved
        if self.resolved_when == TaskLayoutConfig.ResolvedWhen.CHECKBOX_COMPLETE:
            return bool(self.completed_identifier) and line.lstrip().startswith(self.completed_identifier)
        if self.resolved_when == TaskLayoutConfig.ResolvedWhen.TAG:
            return bool(self.resolved_tag) and self.resolved_tag.casefold() in line.casefold()
        if self.resolved_when == TaskLayoutConfig.ResolvedWhen.FRONTMATTER:
            actual = normalize_scalar(linked_frontmatter.get(self.resolved_field))
            return bool(actual) and actual.casefold() == self.resolved_value.casefold()
        return link_resolved

    def is_ignored_key(self, field_name: str) -> bool:
        return field_name in self.ignored_keys


class Command(BaseCommand):
    help = "Rebuilds the cached task-entry index from the configured Obsidian vault."

    def handle(self, *args, **options):
        config = get_config(TaskLayoutConfig)
        vault_root = Path(config.vault_path)
        daily_root = vault_root / config.daily_notes_path
        if not vault_root.exists():
            raise CommandError(f"Vault path does not exist: {vault_root}")
        if not daily_root.exists():
            raise CommandError(f"Daily notes path does not exist: {daily_root}")

        layout = TaskLayout.from_config(config)
        policy = ImportPolicy.from_config(config)
        note_index = NoteIndex(vault_root)
        source_cache: dict[str, SourceNote] = {}

        with transaction.atomic():
            ParseWarning.objects.all().delete()
            TaskEntryFacet.objects.all().delete()
            TaskEntry.objects.all().delete()
            SourceNote.objects.all().delete()

            for daily_path in sorted(daily_root.rglob("*.md")):
                self._import_daily_note(daily_path, vault_root, note_index, source_cache, layout, policy)

        self.stdout.write(self.style.SUCCESS(f"Imported {TaskEntry.objects.count()} task entries."))
        self.stdout.write(self.style.SUCCESS(f"Recorded {ParseWarning.objects.count()} warnings."))

    def _import_daily_note(self, daily_path, vault_root, note_index, source_cache, layout, policy):
        relative_path = daily_path.relative_to(vault_root).as_posix()
        parsed_note = parse_markdown_note(daily_path)
        source_note = self._get_or_create_source_note(
            relative_path=relative_path,
            title=daily_path.stem,
            note_type=SourceNote.NoteType.DAILY,
            note_family=note_family_from_relative_path(relative_path),
            frontmatter=parsed_note.frontmatter,
            content_hash=parsed_note.content_hash,
            modified_at=datetime.fromtimestamp(daily_path.stat().st_mtime),
            cache=source_cache,
        )
        task_date = infer_task_date(
            {policy.date_key: parsed_note.frontmatter.get(policy.date_key)},
            daily_path.stem,
        )
        week_label = normalize_scalar(parsed_note.frontmatter.get(policy.week_key))

        for line_number, line in iter_task_lines(parsed_note.body, layout):
            parsed_task = parse_task_line(line, layout)
            linked_note = None
            linked_frontmatter = {}
            linked_note_path = ""
            linked_note_title = ""
            note_family = ""
            link_resolved = False

            resolved_path = None
            resolution_warnings = []
            if parsed_task.link_target:
                resolved_path, resolution_warnings = note_index.resolve(parsed_task.link_target)

            for warning in resolution_warnings:
                self._create_warning(source_note, line_number, warning, line)

            if resolved_path:
                linked_note_path = resolved_path.relative_to(vault_root).as_posix()
                linked_note_title = resolved_path.stem
                note_family = note_family_from_relative_path(linked_note_path)
                linked_note, linked_frontmatter = self._load_linked_note(
                    resolved_path,
                    vault_root,
                    source_cache,
                )
                link_resolved = True
            elif parsed_task.link_target:
                self._create_warning(
                    source_note,
                    line_number,
                    WarningRecord(
                        code="unresolved_link",
                        message=f"Could not resolve task link: {parsed_task.link_target}",
                        raw_line=line,
                    ),
                    line,
                )

            is_resolved = policy.is_resolved(line, linked_frontmatter, link_resolved)
            column_values = policy.column_values(linked_frontmatter)

            task_entry = TaskEntry.objects.create(
                source_note=source_note,
                linked_note=linked_note,
                task_date=task_date,
                week_label=week_label,
                start_at=parsed_task.start_at,
                end_at=parsed_task.end_at,
                duration_minutes=parsed_task.duration_minutes,
                raw_line=parsed_task.raw_line,
                raw_text=parsed_task.raw_text,
                display_title=parsed_task.display_title,
                link_target=parsed_task.link_target,
                linked_note_path=linked_note_path,
                linked_note_title=linked_note_title,
                note_family=note_family,
                project=column_values.get("project", ""),
                status=column_values.get("status", ""),
                priority=column_values.get("priority", ""),
                assignee=column_values.get("assignee", ""),
                jira_task=column_values.get("jira_task", ""),
                is_resolved=is_resolved,
                has_valid_duration=parsed_task.has_valid_duration,
            )

            for warning in parsed_task.warnings:
                self._create_warning(source_note, line_number, warning, line)

            self._create_facets(task_entry, linked_frontmatter, policy)

    def _load_linked_note(self, resolved_path, vault_root, source_cache):
        relative_path = resolved_path.relative_to(vault_root).as_posix()
        parsed_note = parse_markdown_note(resolved_path)
        source_note = self._get_or_create_source_note(
            relative_path=relative_path,
            title=resolved_path.stem,
            note_type=SourceNote.NoteType.LINKED,
            note_family=note_family_from_relative_path(relative_path),
            frontmatter=parsed_note.frontmatter,
            content_hash=parsed_note.content_hash,
            modified_at=datetime.fromtimestamp(resolved_path.stat().st_mtime),
            cache=source_cache,
        )
        return source_note, parsed_note.frontmatter

    def _get_or_create_source_note(
        self,
        relative_path,
        title,
        note_type,
        note_family,
        frontmatter,
        content_hash,
        modified_at,
        cache,
    ):
        if relative_path in cache:
            return cache[relative_path]
        source_note = SourceNote.objects.create(
            relative_path=relative_path,
            title=title,
            note_type=note_type,
            note_family=note_family,
            frontmatter=frontmatter,
            content_hash=content_hash,
            modified_at=modified_at,
        )
        cache[relative_path] = source_note
        return source_note

    def _create_warning(self, source_note, line_number, warning, raw_line):
        ParseWarning.objects.create(
            source_note=source_note,
            line_number=line_number,
            code=warning.code,
            message=warning.message,
            raw_line=warning.raw_line or raw_line,
        )

    def _create_facets(self, task_entry, linked_frontmatter, policy):
        seen_facets = set()
        for field_name, raw_value in linked_frontmatter.items():
            if isinstance(raw_value, dict):
                continue
            if policy.is_ignored_key(str(field_name)):
                continue
            for value in normalize_list(raw_value):
                if not value:
                    continue
                facet_key = (str(field_name), value)
                if facet_key in seen_facets:
                    continue
                seen_facets.add(facet_key)
                TaskEntryFacet.objects.create(
                    task_entry=task_entry,
                    field_name=facet_key[0],
                    field_value=value,
                )
