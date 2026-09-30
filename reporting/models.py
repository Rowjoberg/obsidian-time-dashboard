from django.db import models


class SourceNote(models.Model):
    class NoteType(models.TextChoices):
        DAILY = "daily", "Daily Note"
        LINKED = "linked", "Linked Note"

    relative_path = models.CharField(max_length=500, unique=True)
    title = models.CharField(max_length=255)
    note_type = models.CharField(max_length=16, choices=NoteType.choices)
    note_family = models.CharField(max_length=100, blank=True)
    frontmatter = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=40, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["relative_path"]

    def __str__(self) -> str:
        return self.relative_path


class TaskEntry(models.Model):
    source_note = models.ForeignKey(SourceNote, on_delete=models.CASCADE, related_name="task_entries")
    linked_note = models.ForeignKey(
        SourceNote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linked_entries",
    )
    task_date = models.DateField()
    week_label = models.CharField(max_length=16, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField(null=True, blank=True)
    raw_line = models.TextField()
    raw_text = models.TextField(blank=True)
    display_title = models.CharField(max_length=255)
    link_target = models.CharField(max_length=255, blank=True)
    linked_note_path = models.CharField(max_length=500, blank=True)
    linked_note_title = models.CharField(max_length=255, blank=True)
    note_family = models.CharField(max_length=100, blank=True)
    project = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=100, blank=True)
    priority = models.CharField(max_length=100, blank=True)
    assignee = models.CharField(max_length=255, blank=True)
    jira_task = models.CharField(max_length=100, blank=True)
    is_resolved = models.BooleanField(default=False)
    has_valid_duration = models.BooleanField(default=False)

    class Meta:
        ordering = ["-task_date", "start_at", "display_title"]
        indexes = [
            models.Index(fields=["task_date"]),
            models.Index(fields=["note_family"]),
            models.Index(fields=["jira_task"]),
            models.Index(fields=["has_valid_duration"]),
        ]

    def __str__(self) -> str:
        return f"{self.task_date} - {self.display_title}"

    @property
    def duration_hours(self) -> float:
        return round((self.duration_minutes or 0) / 60, 2)


class TaskEntryFacet(models.Model):
    task_entry = models.ForeignKey(TaskEntry, on_delete=models.CASCADE, related_name="facets")
    field_name = models.CharField(max_length=50)
    field_value = models.CharField(max_length=255)

    class Meta:
        ordering = ["field_name", "field_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["task_entry", "field_name", "field_value"],
                name="unique_task_entry_facet",
            )
        ]
        indexes = [models.Index(fields=["field_name", "field_value"])]

    def __str__(self) -> str:
        return f"{self.field_name}={self.field_value}"


class TaskLayoutConfig(models.Model):
    """Singleton row describing how task lines are laid out in the vault."""

    class TaskRegion(models.TextChoices):
        AFTER_IDENTIFIER = "after-identifier", "Everything after the identifier"
        BEFORE_START = "before-start", "Text before the start-time marker"
        TITLE_ONLY = "title-only", "Text only, dropping trailing metadata"

    class ResolvedWhen(models.TextChoices):
        LINK_RESOLVED = "link-resolved", "When the task link resolves to a note"
        CHECKBOX_COMPLETE = "checkbox-complete", "When the line uses the completed identifier"
        TAG = "tag", "When the line carries the resolved tag"
        FRONTMATTER = "frontmatter", "When linked-note frontmatter matches the resolved value"

    class Rounding(models.IntegerChoices):
        NONE = 0, "No rounding"
        ONE = 1, "Nearest minute"
        FIVE = 5, "Nearest 5 minutes"
        FIFTEEN = 15, "Nearest 15 minutes"

    identifier = models.CharField(
        max_length=100,
        default="- [t]",
        help_text='Exact text that marks the start of a task line, e.g. "- [t]".',
    )
    task_region = models.CharField(
        max_length=32,
        choices=TaskRegion.choices,
        default=TaskRegion.AFTER_IDENTIFIER,
        help_text="Which part of the line holds the task text.",
    )
    hours_mode = models.BooleanField(
        default=False,
        help_text="Read the duration from the hours pattern instead of the start/end timestamps.",
    )
    hours_pattern = models.CharField(
        max_length=200,
        default=r"[hours]\s*h\b|[H]:[M]\b",
        help_text=r'Matches "2.5h" or "2:30". Tokens: [hours] decimal hours, [H] hours, [M] minutes.',
    )
    start_time_pattern = models.CharField(
        max_length=200,
        default="🛫 YYYY-MM-DD HH:mm",
        help_text="Tokens: YYYY MM DD HH mm (or YY). Everything else is a regular expression.",
    )
    end_time_pattern = models.CharField(
        max_length=200,
        default="📅 YYYY-MM-DD HH:mm",
        help_text="Tokens: YYYY MM DD HH mm (or YY). Everything else is a regular expression.",
    )
    include_invalid_durations_in_totals = models.BooleanField(
        default=False,
        help_text="Count entries with a broken duration in dashboard totals.",
    )
    default_period = models.CharField(max_length=16, default="month")
    default_group_by = models.CharField(max_length=64, default="display_title")
    vault_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Absolute path to the Obsidian vault, e.g. C:\\Users\\me\\Obsidian.",
    )
    daily_notes_path = models.CharField(
        max_length=500,
        blank=True,
        help_text="Vault-relative folder scanned for daily notes.",
    )

    source_unique_identifier = models.CharField(max_length=100, blank=True, default="jiraTask")
    source_workstream = models.CharField(max_length=100, blank=True, default="project")
    source_status = models.CharField(max_length=100, blank=True, default="status")
    source_priority = models.CharField(max_length=100, blank=True, default="priority")
    source_owner = models.CharField(max_length=100, blank=True, default="assignee")
    source_date = models.CharField(max_length=100, blank=True, default="date")
    source_week = models.CharField(max_length=100, blank=True, default="week")

    label_unique_identifier = models.CharField(max_length=64, blank=True, default="Unique Identifier")
    label_workstream = models.CharField(max_length=64, blank=True, default="Workstream")
    label_status = models.CharField(max_length=64, blank=True, default="Status")
    label_priority = models.CharField(max_length=64, blank=True, default="Priority")
    label_owner = models.CharField(max_length=64, blank=True, default="Owner")

    resolved_when = models.CharField(
        max_length=32,
        choices=ResolvedWhen.choices,
        default=ResolvedWhen.LINK_RESOLVED,
        help_text="How a task counts as resolved.",
    )
    completed_identifier = models.CharField(
        max_length=100,
        blank=True,
        default="- [x]",
        help_text="Line prefix that marks a task as done.",
    )
    resolved_tag = models.CharField(
        max_length=100, blank=True, default="#done", help_text="Tag marking a task as done."
    )
    resolved_field = models.CharField(
        max_length=100,
        blank=True,
        default="status",
        help_text="Linked-note frontmatter key compared against the resolved value.",
    )
    resolved_value = models.CharField(max_length=100, blank=True, default="done")

    round_duration_to = models.PositiveSmallIntegerField(
        choices=Rounding.choices,
        default=Rounding.NONE,
        help_text="Round durations to this many minutes.",
    )
    min_duration_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text="Drop durations below this many minutes instead of reporting them.",
    )
    overnight_hours = models.BooleanField(
        default=False,
        help_text="Treat an end time earlier than the start time as crossing midnight.",
    )

    ignored_frontmatter_keys = models.TextField(
        blank=True,
        default="",
        help_text="Frontmatter keys to skip when building filters, one per line.",
    )

    class Meta:
        verbose_name = "Task layout configuration"
        verbose_name_plural = "Task layout configuration"

    def __str__(self) -> str:
        return f"Task layout ({self.identifier!r}, hours={self.hours_mode})"

    def ignored_keys(self) -> list[str]:
        return [key.strip() for key in self.ignored_frontmatter_keys.splitlines() if key.strip()]


class ParseWarning(models.Model):
    source_note = models.ForeignKey(
        SourceNote,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="warnings",
    )
    line_number = models.IntegerField(default=0)
    code = models.CharField(max_length=50)
    message = models.CharField(max_length=255)
    raw_line = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["source_note__relative_path", "line_number", "code"]

    def __str__(self) -> str:
        return f"{self.code} at line {self.line_number}"
