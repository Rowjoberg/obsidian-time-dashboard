import json
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from reporting.forms import EntryControlsForm, FilterForm, WarningFilterForm
from reporting.models import ParseWarning, SourceNote, TaskEntry, TaskLayoutConfig
from reporting.services.reports import (
    ENTRY_SORT_CHOICES,
    GRANULARITY_LABELS,
    apply_filters,
    build_available_group_bys,
    build_entry_rows,
    build_heatmap_rows,
    build_note_family_rows,
    build_summary_rows,
    build_trend_rows,
    build_warning_summary_rows,
    build_weekday_rows,
    choice_label,
    filter_entry_rows,
    get_filter_definitions,
    get_filter_options,
    humanize_field_name,
    prepare_form_data,
)
from reporting.services.roles import role_config
from reporting.services.settings_store import get_config

logger = logging.getLogger(__name__)


def _query_dict_without(query_dict, keys_to_remove):
    params = query_dict.copy()
    for key in keys_to_remove:
        params.pop(key, None)
    return params


def _build_chip_link(path, query_dict, key, value=None):
    params = query_dict.copy()
    if value is None:
        params.pop(key, None)
    else:
        values = [item for item in params.getlist(key) if item != value]
        params.setlist(key, values)
        if not values:
            params.pop(key, None)
    encoded = params.urlencode()
    return f"{path}?{encoded}" if encoded else path


def _build_active_filter_chips(request, filter_form, filter_definitions, period_label, group_by_label):
    chips = []
    if request.GET.get("period"):
        chips.append(
            {
                "label": f"Period: {period_label}",
                "clear_url": _build_chip_link(request.path, request.GET, "period"),
            }
        )
    if request.GET.get("focus_date"):
        chips.append(
            {
                "label": f"Focus: {request.GET.get('focus_date')}",
                "clear_url": _build_chip_link(request.path, request.GET, "focus_date"),
            }
        )
    if request.GET.get("start_date"):
        chips.append(
            {
                "label": f"Start: {request.GET.get('start_date')}",
                "clear_url": _build_chip_link(request.path, request.GET, "start_date"),
            }
        )
    if request.GET.get("end_date"):
        chips.append(
            {
                "label": f"End: {request.GET.get('end_date')}",
                "clear_url": _build_chip_link(request.path, request.GET, "end_date"),
            }
        )
    if request.GET.get("group_by"):
        chips.append(
            {
                "label": f"Group: {group_by_label}",
                "clear_url": _build_chip_link(request.path, request.GET, "group_by"),
            }
        )

    for definition in filter_definitions:
        values = filter_form.cleaned_data.get(definition["form_field"]) or []
        label = definition["label"]
        for value in values:
            chips.append(
                {
                    "label": f"{label}: {value}",
                    "clear_url": _build_chip_link(request.path, request.GET, definition["form_field"], value),
                }
            )
    return chips


def _build_route_with_query(route_name, query=None, extra=None):
    params = query.copy() if query is not None else None
    if params is None:
        encoded = urlencode(extra or {}, doseq=True)
    else:
        for key, value in (extra or {}).items():
            if isinstance(value, (list, tuple)):
                params.setlist(key, list(value))
            else:
                params[key] = value
        encoded = params.urlencode()
    base = reverse(route_name)
    return f"{base}?{encoded}" if encoded else base


def _build_refresh_status():
    latest_entry = TaskEntry.objects.order_by("-task_date").first()
    latest_import = SourceNote.objects.order_by("-imported_at").first()
    warning_count = ParseWarning.objects.count()
    return {
        "last_refreshed_at": latest_import.imported_at if latest_import else None,
        "latest_entry_date": latest_entry.task_date if latest_entry else None,
        "source_count": SourceNote.objects.count(),
        "warning_count": warning_count,
        "entry_count": TaskEntry.objects.count(),
    }


def _build_report_context(request, default_group_by=None):
    latest_entry = TaskEntry.objects.order_by("-task_date").first()
    latest_date = latest_entry.task_date if latest_entry else None
    config = get_config(TaskLayoutConfig)
    filter_definitions = get_filter_definitions(config)
    filter_options = get_filter_options(filter_definitions)

    form_data = prepare_form_data(
        request.GET,
        latest_date=latest_date,
        default_period=config.default_period,
        default_group_by=default_group_by or config.default_group_by,
    )
    bootstrap_form = FilterForm(form_data, filter_definitions=filter_definitions, filter_options=filter_options)
    bootstrap_form.is_valid()
    entries, period = apply_filters(bootstrap_form.cleaned_data, filter_definitions)
    group_by_choices = build_available_group_bys(entries, config)

    filter_form = FilterForm(
        form_data,
        filter_definitions=filter_definitions,
        filter_options=filter_options,
        group_by_choices=group_by_choices,
    )
    filter_form.is_valid()
    entries, period = apply_filters(filter_form.cleaned_data, filter_definitions)

    selected_group_by = filter_form.cleaned_data.get("group_by") or config.default_group_by
    selected_group_by_label = choice_label(
        group_by_choices,
        selected_group_by,
        fallback=humanize_field_name(selected_group_by),
    )
    include_invalid = config.include_invalid_durations_in_totals
    role_labels = role_config(config)
    column_labels = {role["column"]: role["label"] for role in role_labels.values()}
    summary_rows = build_summary_rows(entries, selected_group_by, include_invalid=include_invalid)
    trend_rows = build_trend_rows(entries, period, include_invalid=include_invalid)
    weekday_rows = build_weekday_rows(entries, include_invalid=include_invalid)
    note_family_rows = build_note_family_rows(entries, include_invalid=include_invalid)
    heatmap = build_heatmap_rows(entries, period, include_invalid=include_invalid)
    granularity = period.get("granularity") or "day"
    granularity_label = GRANULARITY_LABELS.get(granularity, granularity.title())
    entry_rows = build_entry_rows(entries)
    entry_controls_form = EntryControlsForm(request.GET)
    entry_controls_form.is_valid()
    entry_search = entry_controls_form.cleaned_data.get("entry_search", "")
    entry_sort = entry_controls_form.cleaned_data.get("entry_sort") or ENTRY_SORT_CHOICES[0][0]
    filtered_entry_rows = filter_entry_rows(entry_rows, search_term=entry_search, sort_key=entry_sort)
    if request.GET.get("is_resolved") == "true":
        filtered_entry_rows = [row for row in filtered_entry_rows if row["is_resolved"]]
    warning_count = ParseWarning.objects.count()
    resolved_count = sum(1 for entry in filtered_entry_rows if entry["is_resolved"])
    valid_entries = [row for row in filtered_entry_rows if row["has_valid_duration"]]
    total_minutes = sum(row["duration_minutes"] or 0 for row in valid_entries)
    average_hours = round((total_minutes / 60) / len(valid_entries), 2) if valid_entries else 0
    active_filter_chips = _build_active_filter_chips(
        request,
        filter_form,
        filter_definitions,
        period["label"],
        selected_group_by_label,
    )
    if request.GET.get("is_resolved") == "true":
        active_filter_chips.append(
            {
                "label": "Resolved only",
                "clear_url": _build_chip_link(request.path, request.GET, "is_resolved"),
            }
        )
    query_without_entry_controls = _query_dict_without(request.GET, ["entry_search", "entry_sort"])
    current_query_string = request.GET.urlencode()

    chart_payload = {
        "summary": {
            "labels": [row["label"] for row in summary_rows[:10]],
            "hours": [row["hours"] for row in summary_rows[:10]],
        },
        "trend": {
            "labels": [row["label"] for row in trend_rows],
            "hours": [row["hours"] for row in trend_rows],
        },
        "weekday": {
            "labels": [row["label"] for row in weekday_rows],
            "hours": [row["hours"] for row in weekday_rows],
        },
        "noteFamily": {
            "labels": [row["label"] for row in note_family_rows[:8]],
            "hours": [row["hours"] for row in note_family_rows[:8]],
        },
        "heatmap": heatmap,
    }

    return {
        "filter_form": filter_form,
        "filter_definitions": filter_definitions,
        "summary_rows": summary_rows,
        "trend_rows": trend_rows,
        "weekday_rows": weekday_rows,
        "note_family_rows": note_family_rows,
        "heatmap": heatmap,
        "granularity": granularity,
        "granularity_label": granularity_label,
        "period": period,
        "warning_count": warning_count,
        "resolved_count": resolved_count,
        "total_hours": round(total_minutes / 60, 2),
        "average_hours": average_hours,
        "entry_count": len(filtered_entry_rows),
        "total_entry_count": len(entry_rows),
        "chart_payload": json.dumps(chart_payload, cls=DjangoJSONEncoder),
        "latest_date": latest_date,
        "selected_group_by": selected_group_by,
        "selected_group_by_label": selected_group_by_label,
        "column_labels": column_labels,
        "entry_rows": filtered_entry_rows,
        "entry_controls_form": entry_controls_form,
        "entry_search": entry_search,
        "entry_sort": entry_sort,
        "active_filter_chips": active_filter_chips,
        "refresh_status": _build_refresh_status(),
        "entries_url": _build_route_with_query("entries", request.GET),
        "summary_url": _build_route_with_query("summary", request.GET),
        "warnings_url": reverse("warnings"),
        "warning_filtered_url": _build_route_with_query("warnings", extra={"code": "all"}),
        "resolved_entries_url": _build_route_with_query(
            "entries", query_without_entry_controls, {"is_resolved": "true"}
        ),
        "current_query_string": current_query_string,
    }


def _redirect_to_safe_next(request):
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("dashboard")


def dashboard_view(request):
    context = _build_report_context(request, default_group_by="display_title")
    return render(request, "reporting/dashboard.html", context)


@require_POST
def refresh_cache_view(request):
    try:
        call_command("refresh_notes")
    except CommandError as exc:
        messages.error(request, f"Cache refresh failed: {exc}")
    except Exception as exc:
        logger.exception("Cache refresh failed unexpectedly.")
        detail = str(exc).strip() or exc.__class__.__name__
        if settings.DEBUG:
            messages.error(request, f"Cache refresh failed: {detail}")
        else:
            messages.error(request, "Cache refresh failed due to an unexpected error.")
    else:
        messages.success(request, "Cache refreshed successfully.")

    return _redirect_to_safe_next(request)


def summary_view(request):
    context = _build_report_context(request)
    return render(request, "reporting/summary.html", context)


def entries_view(request):
    context = _build_report_context(request, default_group_by="display_title")
    return render(request, "reporting/entries.html", context)


def warnings_view(request):
    warnings = ParseWarning.objects.select_related("source_note").all()
    warning_summary_rows = build_warning_summary_rows(warnings)
    warning_code_choices = [("", "All warning codes")] + [
        (row["code"], f"{row['code']} ({row['count']})") for row in warning_summary_rows
    ]

    form = WarningFilterForm(request.GET)
    form.fields["code"].choices = warning_code_choices
    form.is_valid()

    selected_code = form.cleaned_data.get("code") or ""
    source_search = (form.cleaned_data.get("source_search") or "").strip()
    if selected_code:
        warnings = warnings.filter(code=selected_code)
    if source_search:
        warnings = warnings.filter(source_note__relative_path__icontains=source_search)

    warning_rows = list(warnings[:500])
    warning_summary_rows = build_warning_summary_rows(warnings)

    return render(
        request,
        "reporting/warnings.html",
        {
            "warnings": warning_rows,
            "warning_summary_rows": warning_summary_rows,
            "warning_filter_form": form,
            "refresh_status": _build_refresh_status(),
        },
    )
