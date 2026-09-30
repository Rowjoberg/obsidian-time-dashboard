from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from reporting.models import (
    ParseWarning,
    SourceNote,
    TaskEntry,
    TaskEntryFacet,
    TaskLayoutConfig,
)
from reporting.services.layout import TaskLayout, validate_layout
from reporting.services.notes import iter_task_lines, parse_task_line
from reporting.services.reports import (
    PERIOD_GRANULARITY,
    build_available_group_bys,
    build_entry_rows,
    build_heatmap_rows,
    build_summary_rows,
    build_trend_rows,
    build_warning_summary_rows,
    filter_entry_rows,
    get_filter_definitions,
    get_filter_options,
    resolve_period,
)
from reporting.services.settings_store import get_config


def set_config(**values):
    """Write the single configuration row the refresh command and views read."""
    config = TaskLayoutConfig.objects.order_by("pk").first()
    if config is None:
        config = TaskLayoutConfig.objects.create()
    for field, value in values.items():
        setattr(config, field, value)
    config.save()
    return config


class ParserTests(TestCase):
    def test_parse_standard_linked_task(self):
        parsed = parse_task_line("- [t] [[Pullkey Test Plan]] 🛫 2026-03-30 12:30 📅 2026-03-30 15:00")
        self.assertEqual(parsed.link_target, "Pullkey Test Plan")
        self.assertEqual(parsed.display_title, "Pullkey Test Plan")
        self.assertEqual(parsed.duration_minutes, 150)
        self.assertTrue(parsed.has_valid_duration)

    def test_parse_plain_text_task(self):
        parsed = parse_task_line("- [t] Public Holiday 🛫 2025-10-06 06:00 📅 2025-10-06 14:06")
        self.assertEqual(parsed.link_target, "")
        self.assertEqual(parsed.display_title, "Public Holiday")
        self.assertEqual(parsed.duration_minutes, 486)

    def test_parse_invalid_duration_generates_warning(self):
        parsed = parse_task_line("- [t] [[Public Holiday]] 🛫 2025-10-04 06:14 📅 2025-10-04 06:00")
        self.assertFalse(parsed.has_valid_duration)
        self.assertEqual(parsed.warnings[0].code, "invalid_duration")


class ImportTests(TestCase):
    def test_refresh_notes_imports_entries_and_warnings(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Automated Notes" / "Daily Notes"
            jira_dir = vault / "Jira Tasks" / "DP"
            daily_dir.mkdir(parents=True)
            jira_dir.mkdir(parents=True)

            (jira_dir / "Pullkey Test Plan.md").write_text(
                "---\nproject: Engineering\nstatus: active\njobNumber:\n  - JOB-311\njiraTask: TASK-1234\n---\n",
                encoding="utf-8",
            )
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\nweek: 2026-W14\n---\n## 📋 Tasks\n"
                "- [t] [[Pullkey Test Plan]] 🛫 2026-03-30 12:30 📅 2026-03-30 15:00\n"
                "- [t] [[Broken Link]] 🛫 2026-03-30 15:00 📅 2026-03-30 14:00\n",
                encoding="utf-8",
            )

            set_config(
                vault_path=str(vault),
                daily_notes_path="Automated Notes/Daily Notes",
            )
            call_command("refresh_notes")

            self.assertEqual(TaskEntry.objects.count(), 2)
            self.assertEqual(TaskEntry.objects.filter(is_resolved=True).count(), 1)
            self.assertTrue(ParseWarning.objects.filter(code="invalid_duration").exists())
            self.assertTrue(ParseWarning.objects.filter(code="unresolved_link").exists())

    def test_summary_rows_roll_up_duration(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Automated Notes" / "Daily Notes"
            jira_dir = vault / "Jira Tasks" / "DP"
            daily_dir.mkdir(parents=True)
            jira_dir.mkdir(parents=True)
            (jira_dir / "Pullkey Test Plan.md").write_text("---\nproject: Engineering\n---\n", encoding="utf-8")
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\n---\n"
                "- [t] [[Pullkey Test Plan]] 🛫 2026-03-30 12:30 📅 2026-03-30 15:00\n"
                "- [t] [[Pullkey Test Plan]] 🛫 2026-03-30 15:00 📅 2026-03-30 16:00\n",
                encoding="utf-8",
            )
            set_config(
                vault_path=str(vault),
                daily_notes_path="Automated Notes/Daily Notes",
            )
            call_command("refresh_notes")

            rows = build_summary_rows(list(TaskEntry.objects.prefetch_related("facets")), "display_title")
            self.assertEqual(rows[0]["label"], "Pullkey Test Plan")
            self.assertEqual(rows[0]["minutes"], 210)

    def test_dynamic_frontmatter_filter_definition_is_available(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Automated Notes" / "Daily Notes"
            jira_dir = vault / "Jira Tasks" / "AIR"
            daily_dir.mkdir(parents=True)
            jira_dir.mkdir(parents=True)
            (jira_dir / "AIR Task.md").write_text(
                "---\nprefix: AIR\nproject: Engineering\n---\n",
                encoding="utf-8",
            )
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\n---\n- [t] [[AIR Task]] 🛫 2026-03-30 08:00 📅 2026-03-30 09:00\n",
                encoding="utf-8",
            )
            set_config(
                vault_path=str(vault),
                daily_notes_path="Automated Notes/Daily Notes",
            )
            call_command("refresh_notes")

            definitions = get_filter_definitions()
            self.assertTrue(any(item["field_name"] == "prefix" for item in definitions))
            group_choices = build_available_group_bys(list(TaskEntry.objects.prefetch_related("facets")))
            self.assertTrue(any(choice[0] == "prefix" for choice in group_choices))

    def test_refresh_notes_deduplicates_duplicate_frontmatter_values_per_task(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Automated Notes" / "Daily Notes"
            jira_dir = vault / "Jira Tasks" / "DP"
            daily_dir.mkdir(parents=True)
            jira_dir.mkdir(parents=True)

            (jira_dir / "Pullkey Test Plan.md").write_text(
                "---\ntags:\n  - alpha\n  - alpha\n  - beta\nproject: Engineering\n---\n",
                encoding="utf-8",
            )
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\n---\n- [t] [[Pullkey Test Plan]] 🛫 2026-03-30 12:30 📅 2026-03-30 15:00\n",
                encoding="utf-8",
            )

            set_config(
                vault_path=str(vault),
                daily_notes_path="Automated Notes/Daily Notes",
            )
            call_command("refresh_notes")

            entry = TaskEntry.objects.get()
            self.assertEqual(entry.facets.filter(field_name="tags", field_value="alpha").count(), 1)
            self.assertEqual(entry.facets.filter(field_name="tags", field_value="beta").count(), 1)

    def test_entry_rows_support_search_and_duration_sort(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Automated Notes" / "Daily Notes"
            jira_dir = vault / "Jira Tasks" / "DP"
            daily_dir.mkdir(parents=True)
            jira_dir.mkdir(parents=True)

            (jira_dir / "Alpha Task.md").write_text("---\nproject: Engineering\n---\n", encoding="utf-8")
            (jira_dir / "Beta Task.md").write_text("---\nproject: Operations\n---\n", encoding="utf-8")
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\n---\n"
                "- [t] [[Alpha Task]] 🛫 2026-03-30 08:00 📅 2026-03-30 10:00\n"
                "- [t] [[Beta Task]] 🛫 2026-03-30 10:00 📅 2026-03-30 11:00\n",
                encoding="utf-8",
            )

            set_config(
                vault_path=str(vault),
                daily_notes_path="Automated Notes/Daily Notes",
            )
            call_command("refresh_notes")

            rows = build_entry_rows(list(TaskEntry.objects.select_related("source_note").prefetch_related("facets")))
            filtered = filter_entry_rows(rows, search_term="operations", sort_key="duration_desc")

            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["display_title"], "Beta Task")

    def test_entry_rows_sort_handles_missing_timestamps_and_durations(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Automated Notes" / "Daily Notes"
            daily_dir.mkdir(parents=True)
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\n---\n"
                "- [t] Timed Task 🛫 2026-03-30 08:00 📅 2026-03-30 10:00\n"
                "- [t] Untimed Task\n",
                encoding="utf-8",
            )

            set_config(
                vault_path=str(vault),
                daily_notes_path="Automated Notes/Daily Notes",
            )
            call_command("refresh_notes")

            rows = build_entry_rows(list(TaskEntry.objects.select_related("source_note").prefetch_related("facets")))
            self.assertTrue(any(row["start_at"] is None for row in rows))

            for sort_key in (
                "date_desc",
                "date_asc",
                "duration_desc",
                "duration_asc",
                "task_asc",
                "jira_asc",
                "family_asc",
            ):
                with self.subTest(sort_key=sort_key):
                    sorted_rows = filter_entry_rows(rows, sort_key=sort_key)
                    self.assertEqual(len(sorted_rows), 2)


class TaskLayoutTests(TestCase):
    def test_default_layout_matches_current_vault_syntax(self):
        parsed = parse_task_line("- [t] [[Pullkey Test Plan]] 🛫 2026-03-30 12:30 📅 2026-03-30 15:00")

        self.assertEqual(parsed.display_title, "Pullkey Test Plan")
        self.assertEqual(parsed.duration_minutes, 150)
        self.assertTrue(parsed.has_valid_duration)
        self.assertEqual(parsed.warnings, [])

    def test_custom_identifier_is_configurable(self):
        layout = TaskLayout(identifier="* [task]")
        lines = iter_task_lines(
            "* [task] Design review 🛫 2026-03-30 09:00 📅 2026-03-30 10:00\n"
            "- [t] Not a task under this layout 🛫 2026-03-30 09:00 📅 2026-03-30 10:00",
            layout,
        )

        self.assertEqual(len(lines), 1)
        self.assertEqual(parse_task_line(lines[0][1], layout).display_title, "Design review")

    def test_custom_timestamp_markers_are_configurable(self):
        layout = TaskLayout(
            start_time_pattern="from YYYY-MM-DD HH:mm",
            end_time_pattern="to YYYY-MM-DD HH:mm",
        )
        parsed = parse_task_line("- [t] Workshop from 2026-03-30 09:00 to 2026-03-30 11:30", layout)

        self.assertEqual(parsed.display_title, "Workshop")
        self.assertEqual(parsed.duration_minutes, 150)
        self.assertTrue(parsed.has_valid_duration)

    def test_hours_mode_bypasses_timestamps(self):
        layout = TaskLayout(hours_mode=True)
        parsed = parse_task_line("- [t] Deep work 2.5h", layout)

        self.assertEqual(parsed.duration_minutes, 150)
        self.assertTrue(parsed.has_valid_duration)
        self.assertEqual(parsed.display_title, "Deep work")
        self.assertEqual([warning.code for warning in parsed.warnings], [])

    def test_hours_mode_supports_clock_style_values(self):
        layout = TaskLayout(hours_mode=True)

        self.assertEqual(parse_task_line("- [t] Pairing 1:30", layout).duration_minutes, 90)
        self.assertEqual(parse_task_line("- [t] Standup 0:45", layout).duration_minutes, 45)

    def test_hours_mode_keeps_timestamps_for_time_of_day_reporting(self):
        layout = TaskLayout(hours_mode=True)
        parsed = parse_task_line("- [t] Deep work 🛫 2026-03-30 08:00 📅 2026-03-30 12:00 2.5h", layout)

        self.assertEqual(parsed.start_at, datetime(2026, 3, 30, 8, 0))
        self.assertEqual(parsed.end_at, datetime(2026, 3, 30, 12, 0))
        self.assertEqual(parsed.duration_minutes, 150)

    def test_hours_mode_warns_when_value_is_missing(self):
        layout = TaskLayout(hours_mode=True)
        parsed = parse_task_line("- [t] Deep work", layout)

        self.assertFalse(parsed.has_valid_duration)
        self.assertEqual([warning.code for warning in parsed.warnings], ["missing_hours"])

    def test_hours_pattern_is_configurable(self):
        layout = TaskLayout(hours_mode=True, hours_pattern=r"\(([hours])\)")

        self.assertEqual(parse_task_line("- [t] Review (1.5)", layout).duration_minutes, 90)
        self.assertEqual(parse_task_line("- [t] Review 1.5h", layout).duration_minutes, None)

    def test_hours_mode_disabled_ignores_hours_pattern(self):
        parsed = parse_task_line("- [t] Deep work 2.5h")

        self.assertEqual(parsed.duration_minutes, None)
        self.assertEqual([warning.code for warning in parsed.warnings], ["missing_timestamps"])

    def test_before_start_region_keeps_hours_value_in_title(self):
        layout = TaskLayout(hours_mode=True, task_region="before-start")
        parsed = parse_task_line("- [t] Standup 0:45", layout)

        self.assertEqual(parsed.display_title, "Standup 0:45")
        self.assertEqual(parsed.duration_minutes, 45)

    def test_title_only_region_strips_inline_tags(self):
        layout = TaskLayout(task_region="title-only")
        parsed = parse_task_line(
            "- [t] Ship release 🛫 2026-03-30 09:00 📅 2026-03-30 10:00 #urgent #ops",
            layout,
        )

        self.assertEqual(parsed.display_title, "Ship release")
        self.assertEqual(parsed.duration_minutes, 60)

    def test_hours_can_be_written_with_comma_decimal_separator(self):
        layout = TaskLayout(hours_mode=True)

        self.assertEqual(parse_task_line("- [t] Review 2,5h", layout).duration_minutes, 150)

    def test_identifiers_are_matched_literally(self):
        layout = TaskLayout(identifier="- [t] (x)")

        self.assertEqual(len(iter_task_lines("- [t] (x) Literal\n", layout)), 1)
        self.assertEqual(len(iter_task_lines("- [xt] Not matched\n", layout)), 0)

    def test_invalid_patterns_are_reported(self):
        problems = validate_layout("", "", "📅 YYYY-MM-DD HH:mm", "")

        self.assertIn("Identifier cannot be empty.", problems)
        self.assertIn("Start-time pattern cannot be empty.", problems)
        self.assertIn("Hours pattern cannot be empty.", problems)

    def test_patterns_with_unbalanced_brackets_do_not_crash(self):
        layout = TaskLayout(hours_mode=True, hours_pattern="[hours")
        parsed = parse_task_line("- [t] Review 2.5h", layout)

        self.assertEqual(parsed.duration_minutes, None)
        self.assertFalse(parsed.has_valid_duration)


class SettingsStoreTests(TestCase):
    def test_config_row_is_seeded_from_project_config(self):
        config = get_config(TaskLayoutConfig)

        self.assertEqual(config.identifier, "- [t]")
        self.assertFalse(config.hours_mode)
        self.assertEqual(TaskLayoutConfig.objects.count(), 1)

    def test_config_row_is_reused_not_duplicated(self):
        first = get_config(TaskLayoutConfig)
        second = get_config(TaskLayoutConfig)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TaskLayoutConfig.objects.count(), 1)

    @override_settings(
        CONFIG={
            "vault": {"path": "C:\\vault", "daily_notes_path": "Notes/Daily"},
            "reporting": {
                "default_period": "week",
                "default_group_by": "note_family",
                "invalid_durations_in_totals": True,
            },
        }
    )
    def test_seed_values_come_from_config_yaml(self):
        from reporting.services.settings_store import seed_values

        values = seed_values()

        self.assertEqual(values["vault_path"], "C:\\vault")
        self.assertEqual(values["daily_notes_path"], "Notes/Daily")
        self.assertEqual(values["default_period"], "week")
        self.assertEqual(values["default_group_by"], "note_family")
        self.assertTrue(values["include_invalid_durations_in_totals"])

    def test_refresh_command_uses_configured_vault(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Daily"
            daily_dir.mkdir(parents=True)
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\n---\n* [task] [[Plan]] from 2026-03-30 09:00 to 2026-03-30 11:00\n",
                encoding="utf-8",
            )
            set_config(
                vault_path=str(vault),
                daily_notes_path="Daily",
                identifier="* [task]",
                start_time_pattern="from YYYY-MM-DD HH:mm",
                end_time_pattern="to YYYY-MM-DD HH:mm",
            )

            call_command("refresh_notes")

            entry = TaskEntry.objects.get()
            self.assertEqual(entry.display_title, "Plan")
            self.assertEqual(entry.duration_minutes, 120)


class TaskLayoutAdminTests(TestCase):
    def _login(self):
        user = get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="secret")
        self.client.force_login(user)
        return user

    def _change_url(self, config):
        return reverse("admin:reporting_tasklayoutconfig_change", args=[config.pk])

    def _payload(self, config, **overrides):
        data = {
            field.name: getattr(config, field.name)
            for field in TaskLayoutConfig._meta.get_fields()
            if getattr(field, "concrete", False) and not field.primary_key
        }
        data.update(overrides)
        return data

    def test_admin_change_page_renders(self):
        self._login()
        config = get_config(TaskLayoutConfig)

        response = self.client.get(self._change_url(config))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="start_time_pattern"')
        self.assertContains(response, 'name="hours_pattern"')

    def test_admin_offers_frontmatter_keys_as_dropdowns(self):
        self._login()
        config = get_config(TaskLayoutConfig)
        SourceNote.objects.create(
            relative_path="Jira Tasks/DP/Custom Field.md",
            title="Custom Field",
            note_type="linked",
            frontmatter={"program": "Horizon", "epicKey": "HOR-1"},
        )

        response = self.client.get(self._change_url(config))

        self.assertContains(response, "program")
        self.assertContains(response, "epicKey")
        self.assertContains(response, 'name="source_workstream"')
        self.assertContains(response, 'name="label_workstream"')

    def test_admin_blocks_adding_a_second_configuration_row(self):
        self._login()
        get_config(TaskLayoutConfig)

        response = self.client.get(reverse("admin:reporting_tasklayoutconfig_add"))

        self.assertEqual(response.status_code, 403)

    def test_admin_rejects_invalid_patterns(self):
        self._login()
        config = get_config(TaskLayoutConfig)

        response = self.client.post(
            self._change_url(config),
            self._payload(config, identifier="", start_time_pattern="", hours_pattern=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Identifier cannot be empty.")
        config.refresh_from_db()
        self.assertEqual(config.identifier, "- [t]")

    def test_admin_accepts_a_valid_layout(self):
        self._login()
        config = get_config(TaskLayoutConfig)

        response = self.client.post(
            self._change_url(config),
            self._payload(
                config,
                identifier="* [task]",
                hours_mode=True,
                start_time_pattern="from YYYY-MM-DD HH:mm",
                end_time_pattern="to YYYY-MM-DD HH:mm",
                default_period="week",
            ),
        )

        self.assertEqual(response.status_code, 302)
        config.refresh_from_db()
        self.assertEqual(config.identifier, "* [task]")
        self.assertTrue(config.hours_mode)
        self.assertEqual(config.default_period, "week")


class FilterDefinitionTests(TestCase):
    def _make_entry(self, relative_path, **field_values):
        source_note = SourceNote.objects.create(relative_path=relative_path, title="note", note_type="linked")
        entry = TaskEntry.objects.create(
            source_note=source_note,
            task_date="2026-03-30",
            raw_line="- [t] Task",
            display_title="Task",
            project=field_values.get("project", ""),
            status=field_values.get("status", ""),
        )
        for field_name, value in field_values.items():
            if field_name in {"project", "status"}:
                continue
            TaskEntryFacet.objects.create(task_entry=entry, field_name=field_name, field_value=value)
        return entry

    def test_filter_definitions_are_not_duplicated_by_repeated_facet_values(self):
        for index in range(5):
            self._make_entry(
                f"Jira Tasks/DP/Task {index}.md",
                project="Engineering",
                status="active",
                keywords=f"keyword-{index % 2}",
            )

        definitions = get_filter_definitions()
        field_names = [item["field_name"] for item in definitions]

        self.assertEqual(len(field_names), len(set(field_names)))
        self.assertEqual(len([name for name in field_names if name == "keywords"]), 1)

    def test_filter_options_are_not_duplicated_for_scalar_and_facet_fields(self):
        for index in range(5):
            self._make_entry(
                f"Jira Tasks/DP/Task {index}.md",
                project="Engineering",
                status="active",
                tags=f"tag-{index}",
            )

        options = get_filter_options(get_filter_definitions())

        self.assertEqual(options["facet_project"], ["Engineering"])
        self.assertEqual(options["facet_status"], ["active"])
        self.assertEqual(len(options["facet_tags"]), 5)
        self.assertEqual(len(options["facet_tags"]), len(set(options["facet_tags"])))

    def test_facet_field_does_not_duplicate_existing_scalar_filter(self):
        self._make_entry("Jira Tasks/DP/Task.md", project="Engineering", jiraTask="TASK-1234")

        field_names = [item["field_name"] for item in get_filter_definitions()]

        self.assertIn("jira_task", field_names)
        self.assertNotIn("jiraTask", field_names)


class WarningViewTests(TestCase):
    def test_build_warning_summary_rows_counts_codes(self):
        source_note = ParseWarning._meta.get_field("source_note").related_model.objects.create(
            relative_path="Automated Notes/Daily Notes/2026-03-30.md",
            title="2026-03-30",
            note_type="daily",
        )
        ParseWarning.objects.create(source_note=source_note, code="invalid_duration", message="Bad duration")
        ParseWarning.objects.create(source_note=source_note, code="invalid_duration", message="Bad duration")
        ParseWarning.objects.create(source_note=source_note, code="unresolved_link", message="Missing note")

        rows = build_warning_summary_rows(ParseWarning.objects.all())

        self.assertEqual(rows[0], {"code": "invalid_duration", "count": 2})
        self.assertEqual(rows[1], {"code": "unresolved_link", "count": 1})


class RefreshCacheViewTests(TestCase):
    def test_refresh_cache_post_runs_command_end_to_end(self):
        with TemporaryDirectory() as temp_dir:
            vault = Path(temp_dir) / "Vault"
            daily_dir = vault / "Automated Notes" / "Daily Notes"
            jira_dir = vault / "Jira Tasks" / "DP"
            daily_dir.mkdir(parents=True)
            jira_dir.mkdir(parents=True)

            (jira_dir / "Pullkey Test Plan.md").write_text(
                "---\nproject: Engineering\nstatus: active\n---\n",
                encoding="utf-8",
            )
            (daily_dir / "2026-03-30.md").write_text(
                "---\ndate: 2026-03-30\n---\n- [t] [[Pullkey Test Plan]] 🛫 2026-03-30 12:30 📅 2026-03-30 15:00\n",
                encoding="utf-8",
            )

            set_config(
                vault_path=str(vault),
                daily_notes_path="Automated Notes/Daily Notes",
            )
            response = self.client.post(reverse("refresh_cache"), {"next": reverse("summary")}, follow=True)

            self.assertRedirects(response, reverse("summary"))
            self.assertEqual(TaskEntry.objects.count(), 1)
            self.assertEqual(ParseWarning.objects.count(), 0)
            messages = [message.message for message in get_messages(response.wsgi_request)]
            self.assertIn("Cache refreshed successfully.", messages)

    @patch("reporting.views.call_command")
    def test_refresh_cache_post_runs_command_and_sets_success_message(self, mock_call_command):
        response = self.client.post(reverse("refresh_cache"), {"next": reverse("summary")}, follow=True)

        self.assertRedirects(response, reverse("summary"))
        mock_call_command.assert_called_once_with("refresh_notes")
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Cache refreshed successfully.", messages)

    @patch("reporting.views.call_command")
    def test_refresh_cache_post_handles_command_error(self, mock_call_command):
        mock_call_command.side_effect = CommandError("boom")

        response = self.client.post(reverse("refresh_cache"), {"next": reverse("dashboard")}, follow=True)

        self.assertRedirects(response, reverse("dashboard"))
        mock_call_command.assert_called_once_with("refresh_notes")
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Cache refresh failed: boom", messages)

    @override_settings(DEBUG=True)
    @patch("reporting.views.call_command")
    def test_refresh_cache_post_surfaces_unexpected_error_details_in_debug(self, mock_call_command):
        mock_call_command.side_effect = RuntimeError("vault is locked")

        response = self.client.post(reverse("refresh_cache"), {"next": reverse("dashboard")}, follow=True)

        self.assertRedirects(response, reverse("dashboard"))
        mock_call_command.assert_called_once_with("refresh_notes")
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Cache refresh failed: vault is locked", messages)

    @patch("reporting.views.call_command")
    def test_refresh_cache_get_is_not_allowed(self, mock_call_command):
        response = self.client.get(reverse("refresh_cache"))

        self.assertEqual(response.status_code, 405)
        mock_call_command.assert_not_called()


class StaticAssetTests(TestCase):
    def _asset_source(self, name):
        from django.conf import settings as django_settings

        return (Path(django_settings.BASE_DIR) / "static" / "reporting" / name).read_text(encoding="utf-8")

    def test_pages_reference_cache_busted_static_assets(self):
        response = self.client.get(reverse("dashboard"))

        content = response.content.decode()
        self.assertIn("/static/reporting/app.js?v=", content)
        self.assertIn("/static/reporting/app.css?v=", content)

    def test_axis_label_constant_is_declared_before_the_load_time_chart_calls(self):
        source = self._asset_source("app.js")

        declaration = source.index("const MAX_AXIS_LABEL_LENGTH")
        first_chart_call = source.index("renderBarChart('summary-chart'")

        self.assertLess(
            declaration,
            first_chart_call,
            "A top-level const read by a chart function must be declared before the "
            "block that draws charts, otherwise the script throws a ReferenceError.",
        )

    def test_axis_labels_are_capped_at_24_characters(self):
        source = self._asset_source("app.js")

        self.assertIn("const MAX_AXIS_LABEL_LENGTH = 24;", source)
        self.assertIn("labels: labels.map((label) => truncateAxisLabel(label))", source)


class PeriodGranularityTests(TestCase):
    def _make_entry(self, index, task_date, start_at=None, duration_minutes=60):
        source_note = SourceNote.objects.create(
            relative_path=f"Automated Notes/Daily Notes/{task_date}-{index}.md",
            title=str(task_date),
            note_type="daily",
        )
        return TaskEntry.objects.create(
            source_note=source_note,
            task_date=task_date,
            start_at=start_at,
            end_at=start_at,
            duration_minutes=duration_minutes,
            has_valid_duration=bool(duration_minutes),
            raw_line="- [t] Task",
            display_title=f"Task {index}",
        )

    def test_named_periods_use_expected_granularity(self):
        self.assertEqual(
            PERIOD_GRANULARITY,
            {"day": "hour", "week": "day", "month": "week", "year": "month"},
        )

    def test_year_period_spans_the_whole_year_and_rolls_up_by_month(self):
        period = resolve_period({"period": "year", "focus_date": date(2026, 3, 30)})

        self.assertEqual(period["start_date"], date(2026, 1, 1))
        self.assertEqual(period["end_date"], date(2026, 12, 31))
        self.assertEqual(period["granularity"], "month")
        self.assertEqual(period["choice"], "year")
        self.assertEqual(period["label"], "2026")

    def test_month_period_rolls_up_by_week(self):
        period = resolve_period({"period": "month", "focus_date": date(2026, 3, 30)})

        self.assertEqual(period["granularity"], "week")
        self.assertEqual(period["start_date"], date(2026, 3, 1))
        self.assertEqual(period["end_date"], date(2026, 3, 31))

    def test_month_trend_groups_entries_by_week(self):
        first = self._make_entry(1, date(2026, 3, 2))
        second = self._make_entry(2, date(2026, 3, 5))
        third = self._make_entry(3, date(2026, 3, 9))

        rows = build_trend_rows(
            [first, second, third],
            resolve_period({"period": "month", "focus_date": date(2026, 3, 30)}),
        )

        self.assertEqual([row["label"] for row in rows], ["2026-03-02", "2026-03-09"])
        self.assertEqual([row["hours"] for row in rows], [2.0, 1.0])

    def test_year_trend_groups_entries_by_month(self):
        january = self._make_entry(1, date(2026, 1, 8))
        february = self._make_entry(2, date(2026, 2, 12), duration_minutes=120)
        march = self._make_entry(3, date(2026, 3, 3))

        rows = build_trend_rows(
            [january, february, march],
            resolve_period({"period": "year", "focus_date": date(2026, 3, 30)}),
        )

        self.assertEqual([row["label"] for row in rows], ["2026-01", "2026-02", "2026-03"])
        self.assertEqual([row["hours"] for row in rows], [1.0, 2.0, 1.0])

    def test_day_trend_groups_entries_by_start_hour(self):
        morning = self._make_entry(1, date(2026, 3, 30), start_at=datetime(2026, 3, 30, 9, 15))
        afternoon = self._make_entry(
            2,
            date(2026, 3, 30),
            start_at=datetime(2026, 3, 30, 14, 0),
            duration_minutes=30,
        )

        rows = build_trend_rows(
            [morning, afternoon],
            resolve_period({"period": "day", "focus_date": date(2026, 3, 30)}),
        )

        self.assertEqual([row["label"] for row in rows], ["09:00", "14:00"])
        self.assertEqual([row["hours"] for row in rows], [1.0, 0.5])

    def test_hour_heatmap_is_weekday_by_hour(self):
        entry = self._make_entry(1, date(2026, 3, 30), start_at=datetime(2026, 3, 30, 9, 0))

        payload = build_heatmap_rows(
            [entry],
            resolve_period({"period": "month", "focus_date": date(2026, 3, 30)}),
        )

        self.assertEqual(payload["row_count"], 7)
        self.assertEqual(payload["column_count"], 24)
        self.assertEqual(payload["row_label"], "Day of Week")
        self.assertEqual(len(payload["cells"]), 168)

        monday_nine = next(cell for cell in payload["cells"] if cell["row"] == 0 and cell["column"] == 9)
        self.assertEqual(monday_nine["row_label"], "Mon")
        self.assertEqual(monday_nine["column_label"], "09:00")
        self.assertEqual(monday_nine["hours"], 1.0)

    def test_year_heatmap_is_month_by_week_of_month(self):
        first_week = self._make_entry(1, date(2026, 1, 3), start_at=datetime(2026, 1, 3, 9, 0))
        fourth_week = self._make_entry(
            2,
            date(2026, 1, 25),
            start_at=datetime(2026, 1, 25, 9, 0),
            duration_minutes=30,
        )

        payload = build_heatmap_rows(
            [first_week, fourth_week],
            resolve_period({"period": "year", "focus_date": date(2026, 3, 30)}),
        )

        self.assertEqual(payload["row_count"], 12)
        self.assertEqual(payload["column_count"], 5)
        self.assertEqual(payload["row_label"], "Month")
        self.assertEqual(payload["column_label"], "Week of Month")
        self.assertEqual(payload["row_labels"][0], "Jan")
        self.assertEqual(payload["column_labels"], ["W1", "W2", "W3", "W4", "W5"])
        self.assertEqual(len(payload["cells"]), 60)

        january = [cell for cell in payload["cells"] if cell["row"] == 0]
        self.assertEqual([cell["hours"] for cell in january], [1.0, 0, 0, 0.5, 0])

    def test_custom_period_without_dates_keeps_whole_vault_fallback(self):
        period = resolve_period({"period": "custom"})

        self.assertIsNone(period["start_date"])
        self.assertIsNone(period["end_date"])
        self.assertEqual(period["granularity"], "month")

    def test_dashboard_renders_year_period(self):
        response = self.client.get(reverse("dashboard"), {"period": "year", "focus_date": "2026-03-30"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["period"]["choice"], "year")
        self.assertEqual(response.context["granularity_label"], "Month")
        self.assertEqual(response.context["heatmap"]["row_label"], "Month")
        self.assertContains(response, "2026 &middot; by Month", html=False)
        self.assertContains(response, "Month vs Week of Month")
