from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Prefetch
from django.utils.text import slugify

from reporting.models import TaskEntry, TaskEntryFacet
from reporting.services.roles import column_label

PERIOD_CHOICES = [
    ("day", "Day"),
    ("week", "Week"),
    ("month", "Month"),
    ("year", "Year"),
    ("custom", "Custom"),
]

# Charts roll up to the natural grain of the selected period, so a month view is
# summarised by week and a year view by month.
PERIOD_GRANULARITY = {
    "day": "hour",
    "week": "day",
    "month": "week",
    "year": "month",
}

GRANULARITY_LABELS = {
    "hour": "Hour",
    "day": "Day",
    "week": "Week",
    "month": "Month",
}

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_LABELS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
WEEKS_PER_MONTH = 5

ENTRY_SORT_CHOICES = [
    ("date_desc", "Newest first"),
    ("date_asc", "Oldest first"),
    ("duration_desc", "Longest first"),
    ("duration_asc", "Shortest first"),
    ("task_asc", "Task A-Z"),
    ("jira_asc", "Jira A-Z"),
    ("family_asc", "Note family A-Z"),
]

GROUP_BY_CHOICES = [
    ("display_title", "Task"),
    ("note_family", "Note Family"),
    ("project", "Project"),
    ("jira_task", "Jira Task"),
    ("jobNumber", "Job Number"),
    ("changeRequest", "Change Request"),
    ("status", "Status"),
    ("assignee", "Assignee"),
    ("prefix", "Prefix"),
]

# Columns whose label is user configurable through the layout configuration.
CONFIGURABLE_LABEL_COLUMNS = ("project", "jira_task", "status", "priority", "assignee")

STATIC_FILTER_FIELDS = [
    ("jobNumber", "Job Number", "facet"),
    ("changeRequest", "Change Request", "facet"),
    ("sytelineItem", "Syteline Item", "facet"),
    ("labels", "Labels", "facet"),
    ("components", "Components", "facet"),
    ("tags", "Tags", "facet"),
    ("prefix", "Prefix", "facet"),
    ("jira_task", "Jira Task", "scalar"),
    ("project", "Project", "scalar"),
    ("status", "Status", "scalar"),
    ("priority", "Priority", "scalar"),
    ("assignee", "Assignee", "scalar"),
    ("note_family", "Note Family", "scalar"),
]

DEFAULT_DYNAMIC_FIELDS = [
    "prefix",
    "jobNumber",
    "changeRequest",
    "sytelineItem",
    "labels",
    "components",
    "tags",
]


def label_for_column(column: str, config=None) -> str:
    """Return the display label for a column, honouring configured role labels."""
    if config is not None and column in CONFIGURABLE_LABEL_COLUMNS:
        return column_label(config, column)
    for value, label in GROUP_BY_CHOICES:
        if value == column:
            return label
    return humanize_field_name(column)


def build_group_by_choices(config=None) -> list[tuple[str, str]]:
    return [
        (value, label_for_column(value, config) if value in CONFIGURABLE_LABEL_COLUMNS else label)
        for value, label in GROUP_BY_CHOICES
    ]


def get_filter_definitions(config=None) -> list[dict[str, str]]:
    definitions = []
    for key, label, source_type in STATIC_FILTER_FIELDS:
        definitions.append(
            {
                "form_field": form_field_name(key),
                "field_name": key,
                "label": label_for_column(key, config) if key in CONFIGURABLE_LABEL_COLUMNS else label,
                "source_type": source_type,
                "dynamic": source_type == "facet",
            }
        )

    known_form_fields = {item["form_field"] for item in definitions}
    known_filter_keys = {canonical_filter_key(item["field_name"]) for item in definitions}
    dynamic_field_names = (
        TaskEntryFacet.objects.exclude(field_name__exact="").order_by().values_list("field_name", flat=True).distinct()
    )
    for field_name in sorted({value for value in dynamic_field_names if value and value not in DEFAULT_DYNAMIC_FIELDS}):
        form_field = form_field_name(field_name)
        filter_key = canonical_filter_key(field_name)
        if form_field in known_form_fields or filter_key in known_filter_keys:
            continue
        known_form_fields.add(form_field)
        known_filter_keys.add(filter_key)
        definitions.append(
            {
                "form_field": form_field,
                "field_name": field_name,
                "label": humanize_field_name(field_name),
                "source_type": "facet",
                "dynamic": True,
            }
        )
    return definitions


def get_filter_options(filter_definitions=None) -> dict[str, list[str]]:
    options: dict[str, list[str]] = {}
    filter_definitions = filter_definitions or get_filter_definitions()
    for definition in filter_definitions:
        if definition["source_type"] == "scalar":
            values = (
                TaskEntry.objects.exclude(**{f"{definition['field_name']}__exact": ""})
                .order_by()
                .values_list(definition["field_name"], flat=True)
                .distinct()
            )
        else:
            values = (
                TaskEntryFacet.objects.filter(field_name=definition["field_name"])
                .order_by()
                .values_list("field_value", flat=True)
                .distinct()
            )
        options[definition["form_field"]] = sorted({value for value in values if value})
    return options


def prepare_form_data(
    query_dict,
    latest_date=None,
    default_period="month",
    default_group_by="display_title",
):
    data = query_dict.copy()
    if not data.get("period"):
        data["period"] = default_period
    if latest_date and not data.get("focus_date"):
        data["focus_date"] = latest_date.isoformat()
    if not data.get("group_by"):
        data["group_by"] = default_group_by
    return data


def apply_filters(cleaned_data, filter_definitions=None):
    queryset = TaskEntry.objects.select_related("source_note", "linked_note").prefetch_related(
        Prefetch(
            "facets",
            queryset=TaskEntryFacet.objects.order_by("field_name", "field_value"),
        )
    )
    filter_definitions = filter_definitions or get_filter_definitions()
    period = resolve_period(cleaned_data)
    start_date = period["start_date"]
    end_date = period["end_date"]
    if start_date:
        queryset = queryset.filter(task_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(task_date__lte=end_date)

    for definition in filter_definitions:
        values = cleaned_data.get(definition["form_field"]) or []
        if not values:
            continue
        if definition["source_type"] == "scalar":
            queryset = queryset.filter(**{f"{definition['field_name']}__in": values})
        else:
            queryset = queryset.filter(
                id__in=TaskEntryFacet.objects.filter(
                    field_name=definition["field_name"],
                    field_value__in=values,
                ).values("task_entry_id")
            )

    queryset = queryset.order_by("-task_date", "start_at", "display_title").distinct()
    return list(queryset), {
        "start_date": start_date,
        "end_date": end_date,
        "label": period["label"],
        "choice": period["choice"],
        "granularity": period["granularity"],
    }


def resolve_period(cleaned_data):
    period = cleaned_data.get("period") or "month"
    focus_date = cleaned_data.get("focus_date") or date.today()
    start_date = cleaned_data.get("start_date")
    end_date = cleaned_data.get("end_date")

    if period not in PERIOD_GRANULARITY and period != "custom":
        period = "month"

    if period == "custom":
        if start_date and end_date:
            resolved = {
                "start_date": start_date,
                "end_date": end_date,
                "label": f"{start_date.isoformat()} to {end_date.isoformat()}",
            }
        else:
            resolved = {
                "start_date": None,
                "end_date": None,
                "label": "All Imported Data",
            }
        resolved["granularity"] = auto_granularity(resolved["start_date"], resolved["end_date"])
        resolved["choice"] = period
        return resolved

    if period == "day":
        resolved = {
            "start_date": focus_date,
            "end_date": focus_date,
            "label": focus_date.strftime("%A, %d %b %Y"),
        }
    elif period == "week":
        start = focus_date - timedelta(days=focus_date.weekday())
        resolved = {
            "start_date": start,
            "end_date": start + timedelta(days=6),
            "label": f"Week of {start.strftime('%d %b %Y')}",
        }
    elif period == "year":
        resolved = {
            "start_date": focus_date.replace(month=1, day=1),
            "end_date": focus_date.replace(month=12, day=31),
            "label": f"{focus_date.year}",
        }
    else:
        start = focus_date.replace(day=1)
        if focus_date.month == 12:
            next_month = focus_date.replace(year=focus_date.year + 1, month=1, day=1)
        else:
            next_month = focus_date.replace(month=focus_date.month + 1, day=1)
        resolved = {
            "start_date": start,
            "end_date": next_month - timedelta(days=1),
            "label": focus_date.strftime("%B %Y"),
        }

    resolved["choice"] = period
    resolved["granularity"] = PERIOD_GRANULARITY[period]
    return resolved


def auto_granularity(start_date, end_date):
    if not start_date or not end_date:
        return "month"
    span_days = max((end_date - start_date).days + 1, 1)
    if span_days <= 62:
        return "day"
    if span_days <= 366:
        return "week"
    return "month"


def build_summary_rows(entries, group_by, include_invalid=False):
    grouped = defaultdict(int)
    for entry in entries:
        if not include_invalid and not entry.has_valid_duration:
            continue
        if not entry.duration_minutes:
            continue
        label = group_value_for_entry(entry, group_by)
        grouped[label] += entry.duration_minutes
    rows = [{"label": label, "minutes": minutes, "hours": round(minutes / 60, 2)} for label, minutes in grouped.items()]
    return sorted(rows, key=lambda row: (-row["minutes"], row["label"]))


def build_trend_rows(entries, period, include_invalid=False):
    granularity = period.get("granularity") or auto_granularity(period.get("start_date"), period.get("end_date"))
    grouped = defaultdict(int)

    for entry in entries:
        if not include_invalid and not entry.has_valid_duration:
            continue
        if not entry.duration_minutes:
            continue
        label = trend_label_for_entry(entry, granularity)
        if label is None:
            continue
        grouped[label] += entry.duration_minutes

    return [
        {"label": label, "minutes": minutes, "hours": round(minutes / 60, 2)}
        for label, minutes in sorted(grouped.items())
    ]


def trend_label_for_entry(entry, granularity):
    if granularity == "hour":
        if not entry.start_at:
            return None
        return entry.start_at.strftime("%H:00")
    if granularity == "day":
        return entry.task_date.isoformat()
    if granularity == "week":
        week_start = entry.task_date - timedelta(days=entry.task_date.weekday())
        return week_start.isoformat()
    return entry.task_date.strftime("%Y-%m")


def build_weekday_rows(entries, include_invalid=False):
    grouped = {index: 0 for index in range(7)}
    for entry in entries:
        if not include_invalid and not entry.has_valid_duration:
            continue
        if not entry.duration_minutes:
            continue
        grouped[entry.task_date.weekday()] += entry.duration_minutes
    return [
        {
            "label": WEEKDAY_LABELS[index],
            "minutes": minutes,
            "hours": round(minutes / 60, 2),
        }
        for index, minutes in grouped.items()
    ]


def build_note_family_rows(entries, include_invalid=False):
    grouped = defaultdict(int)
    for entry in entries:
        if not include_invalid and not entry.has_valid_duration:
            continue
        if not entry.duration_minutes:
            continue
        label = entry.note_family or "Unlinked"
        grouped[label] += entry.duration_minutes
    return [
        {"label": label, "minutes": minutes, "hours": round(minutes / 60, 2)}
        for label, minutes in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_heatmap_rows(entries, period=None, include_invalid=False):
    granularity = (period or {}).get("granularity") or "hour"
    if granularity == "month":
        return build_calendar_heatmap(entries, include_invalid=include_invalid)
    return build_hour_heatmap(entries, include_invalid=include_invalid)


def build_hour_heatmap(entries, include_invalid=False):
    grid = defaultdict(int)
    for entry in entries:
        if not include_invalid and not entry.has_valid_duration:
            continue
        if not entry.duration_minutes or not entry.start_at:
            continue
        grid[(entry.task_date.weekday(), entry.start_at.hour)] += entry.duration_minutes

    column_labels = [f"{hour:02d}:00" for hour in range(24)]
    return _heatmap_payload(
        rows=7,
        columns=24,
        row_label="Day of Week",
        column_label="Start Hour",
        row_labels=WEEKDAY_LABELS,
        column_labels=column_labels,
        grid=grid,
    )


def build_calendar_heatmap(entries, include_invalid=False):
    grid = defaultdict(int)
    for entry in entries:
        if not include_invalid and not entry.has_valid_duration:
            continue
        if not entry.duration_minutes:
            continue
        week_of_month = min((entry.task_date.day - 1) // 7, WEEKS_PER_MONTH - 1)
        grid[(entry.task_date.month - 1, week_of_month)] += entry.duration_minutes

    return _heatmap_payload(
        rows=12,
        columns=WEEKS_PER_MONTH,
        row_label="Month",
        column_label="Week of Month",
        row_labels=MONTH_LABELS,
        column_labels=[f"W{week + 1}" for week in range(WEEKS_PER_MONTH)],
        grid=grid,
    )


def _heatmap_payload(rows, columns, row_label, column_label, row_labels, column_labels, grid):
    cells = []
    for row_index in range(rows):
        for column_index in range(columns):
            minutes = grid.get((row_index, column_index), 0)
            cells.append(
                {
                    "row": row_index,
                    "row_label": row_labels[row_index],
                    "column": column_index,
                    "column_label": column_labels[column_index],
                    "minutes": minutes,
                    "hours": round(minutes / 60, 2),
                }
            )
    return {
        "row_count": rows,
        "column_count": columns,
        "row_label": row_label,
        "column_label": column_label,
        "row_labels": row_labels,
        "column_labels": column_labels,
        "cells": cells,
    }


def build_entry_rows(entries):
    rows = []
    for entry in entries:
        facet_map = defaultdict(list)
        for facet in entry.facets.all():
            facet_map[facet.field_name].append(facet.field_value)
        rows.append(
            {
                "task_date": entry.task_date,
                "display_title": entry.display_title,
                "start_at": entry.start_at,
                "end_at": entry.end_at,
                "duration_minutes": entry.duration_minutes,
                "duration_hours": entry.duration_hours,
                "note_family": entry.note_family,
                "project": entry.project,
                "status": entry.status,
                "assignee": entry.assignee,
                "jira_task": entry.jira_task,
                "raw_text": entry.raw_text,
                "raw_line": entry.raw_line,
                "source_note_path": entry.source_note.relative_path,
                "is_resolved": entry.is_resolved,
                "has_valid_duration": entry.has_valid_duration,
                "linked_note_path": entry.linked_note_path,
                "job_numbers": facet_map.get("jobNumber", []),
                "change_requests": facet_map.get("changeRequest", []),
                "syteline_items": facet_map.get("sytelineItem", []),
                "facets": dict(sorted(facet_map.items())),
            }
        )
    return rows


def build_available_group_bys(entries, config=None) -> list[tuple[str, str]]:
    available = {choice[0] for choice in GROUP_BY_CHOICES}
    for entry in entries:
        for facet in entry.facets.all():
            available.add(facet.field_name)
    base_choices = build_group_by_choices(config)
    existing = {value for value, _ in base_choices}
    existing_keys = {canonical_filter_key(value) for value in existing}
    dynamic_choices = []
    for field_name in sorted(
        value for value in available if value not in existing and value not in {"labels", "components", "tags"}
    ):
        filter_key = canonical_filter_key(field_name)
        if filter_key in existing_keys:
            continue
        existing_keys.add(filter_key)
        dynamic_choices.append((field_name, humanize_field_name(field_name)))
    return base_choices + dynamic_choices


def filter_entry_rows(rows, search_term="", sort_key="date_desc"):
    filtered_rows = list(rows)
    normalized_search = search_term.strip().casefold()
    if normalized_search:
        filtered_rows = [row for row in filtered_rows if normalized_search in _entry_search_text(row)]

    sorters = {
        "date_asc": lambda row: (
            _entry_date_key(row),
            _entry_start_key(row),
            row["display_title"].casefold(),
        ),
        "duration_desc": lambda row: (
            _entry_duration_key(row),
            _entry_date_key(row),
            row["display_title"].casefold(),
        ),
        "duration_asc": lambda row: (
            _entry_missing_duration_key(row),
            _entry_date_key(row),
            row["display_title"].casefold(),
        ),
        "task_asc": lambda row: (
            row["display_title"].casefold(),
            _entry_date_key(row),
            _entry_start_key(row),
        ),
        "jira_asc": lambda row: (
            (row["jira_task"] or "").casefold(),
            row["display_title"].casefold(),
            _entry_date_key(row),
        ),
        "family_asc": lambda row: (
            (row["note_family"] or "").casefold(),
            row["display_title"].casefold(),
            _entry_date_key(row),
        ),
    }
    if sort_key == "date_desc":
        return sorted(
            filtered_rows,
            key=lambda row: (
                _entry_date_key(row),
                _entry_start_key(row),
                row["display_title"].casefold(),
            ),
            reverse=True,
        )
    sorter = sorters.get(sort_key) or sorters["date_asc"]
    reverse = sort_key == "duration_desc"
    return sorted(filtered_rows, key=sorter, reverse=reverse)


def build_warning_summary_rows(warnings):
    grouped = defaultdict(int)
    for warning in warnings:
        grouped[warning.code] += 1
    return [
        {"code": code, "count": count} for code, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
    ]


def choice_label(choices, value, fallback=""):
    for option_value, label in choices:
        if option_value == value:
            return label
    return fallback or humanize_field_name(value)


def group_value_for_entry(entry, group_by):
    if hasattr(entry, group_by):
        value = getattr(entry, group_by, "")
        return value or "Unassigned"
    values = [facet.field_value for facet in entry.facets.all() if facet.field_name == group_by]
    return ", ".join(sorted(values)) if values else "Unassigned"


def canonical_filter_key(field_name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", field_name.casefold())


def form_field_name(field_name: str) -> str:
    return f"facet_{slugify(field_name).replace('-', '_')}"


def humanize_field_name(field_name: str) -> str:
    field_name = field_name.replace("_", " ")
    field_name = field_name.replace("-", " ")
    return field_name[:1].upper() + field_name[1:]


def _entry_date_key(row):
    return row["task_date"].isoformat()


def _entry_start_key(row):
    start_at = row["start_at"]
    return start_at.isoformat() if start_at else ""


def _entry_duration_key(row):
    duration_minutes = row["duration_minutes"]
    return duration_minutes if duration_minutes is not None else -1


def _entry_missing_duration_key(row):
    duration_minutes = row["duration_minutes"]
    return duration_minutes if duration_minutes is not None else 10**9


def _entry_search_text(row):
    parts = [
        row["display_title"],
        row["linked_note_path"],
        row["source_note_path"],
        row["jira_task"],
        row["note_family"],
        row["project"],
        row["status"],
        row["assignee"],
        row["raw_text"],
        row["raw_line"],
    ]
    for values in row["facets"].values():
        parts.extend(values)
    return " ".join(str(part or "") for part in parts).casefold()
