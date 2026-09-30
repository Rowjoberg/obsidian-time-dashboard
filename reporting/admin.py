from django import forms
from django.contrib import admin

from reporting.models import (
    ParseWarning,
    SourceNote,
    TaskEntry,
    TaskEntryFacet,
    TaskLayoutConfig,
)
from reporting.services.layout import validate_layout
from reporting.services.roles import frontmatter_keys

SOURCE_FIELDS = [
    "source_unique_identifier",
    "source_workstream",
    "source_status",
    "source_priority",
    "source_owner",
    "source_date",
    "source_week",
]


class TaskEntryFacetInline(admin.TabularInline):
    model = TaskEntryFacet
    extra = 0


class TaskLayoutConfigForm(forms.ModelForm):
    class Meta:
        model = TaskLayoutConfig
        fields = "__all__"
        help_texts = {
            "identifier": "Exact text that starts a task line. The rest of the line is parsed with the patterns below.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "None")] + [(key, key) for key in frontmatter_keys()]
        for field_name in SOURCE_FIELDS:
            self.fields[field_name].widget = forms.Select(choices=choices)
            self.fields[
                field_name
            ].help_text = "Frontmatter key in the linked note, picked from the keys found in your vault."

    def clean(self):
        cleaned_data = super().clean()
        problems = validate_layout(
            cleaned_data.get("identifier", ""),
            cleaned_data.get("start_time_pattern", ""),
            cleaned_data.get("end_time_pattern", ""),
            cleaned_data.get("hours_pattern", ""),
        )
        if problems:
            raise forms.ValidationError(problems)
        return cleaned_data


@admin.register(TaskLayoutConfig)
class TaskLayoutConfigAdmin(admin.ModelAdmin):
    form = TaskLayoutConfigForm
    list_display = (
        "identifier",
        "task_region",
        "hours_mode",
        "default_period",
        "vault_path",
    )

    def has_add_permission(self, request):
        return not TaskLayoutConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SourceNote)
class SourceNoteAdmin(admin.ModelAdmin):
    list_display = ("relative_path", "note_type", "note_family", "modified_at")
    search_fields = ("relative_path", "title")
    list_filter = ("note_type", "note_family")


@admin.register(TaskEntry)
class TaskEntryAdmin(admin.ModelAdmin):
    list_display = (
        "task_date",
        "display_title",
        "duration_minutes",
        "note_family",
        "jira_task",
        "is_resolved",
    )
    search_fields = ("display_title", "raw_text", "jira_task", "linked_note_path")
    list_filter = (
        "note_family",
        "status",
        "project",
        "is_resolved",
        "has_valid_duration",
    )
    inlines = [TaskEntryFacetInline]


@admin.register(ParseWarning)
class ParseWarningAdmin(admin.ModelAdmin):
    list_display = ("code", "source_note", "line_number", "message", "created_at")
    search_fields = ("code", "message", "raw_line")
    list_filter = ("code",)
