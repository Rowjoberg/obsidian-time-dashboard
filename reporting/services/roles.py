"""Role based frontmatter mapping.

The dashboard used to hardcode vault specific names such as ``jiraTask`` and
``assignee``. Those are now *roles*: each role keeps a generic label ("Unique
Identifier") while the frontmatter key that feeds it is configurable, so the same
install can read a Jira vault or a plain markdown vault.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    name: str
    column: str
    source_field: str
    label_field: str
    default_source: str
    default_label: str


ROLES = [
    Role(
        name="unique_identifier",
        column="jira_task",
        source_field="source_unique_identifier",
        label_field="label_unique_identifier",
        default_source="jiraTask",
        default_label="Unique Identifier",
    ),
    Role(
        name="workstream",
        column="project",
        source_field="source_workstream",
        label_field="label_workstream",
        default_source="project",
        default_label="Workstream",
    ),
    Role(
        name="status",
        column="status",
        source_field="source_status",
        label_field="label_status",
        default_source="status",
        default_label="Status",
    ),
    Role(
        name="priority",
        column="priority",
        source_field="source_priority",
        label_field="label_priority",
        default_source="priority",
        default_label="Priority",
    ),
    Role(
        name="owner",
        column="assignee",
        source_field="source_owner",
        label_field="label_owner",
        default_source="assignee",
        default_label="Owner",
    ),
]

ROLES_BY_NAME = {role.name: role for role in ROLES}
ROLES_BY_COLUMN = {role.column: role for role in ROLES}

DEFAULT_DATE_KEY = "date"
DEFAULT_WEEK_KEY = "week"


def role_config(config) -> dict[str, dict[str, str]]:
    """Return ``{role_name: {'column', 'source', 'label'}}`` for a config row."""
    resolved = {}
    for role in ROLES:
        resolved[role.name] = {
            "column": role.column,
            "source": (getattr(config, role.source_field, "") or role.default_source),
            "label": (getattr(config, role.label_field, "") or role.default_label),
        }
    return resolved


def column_label(config, column: str) -> str:
    role = ROLES_BY_COLUMN.get(column)
    if role is None:
        return column
    return getattr(config, role.label_field, "") or role.default_label


def source_key(config, role_name: str) -> str:
    role = ROLES_BY_NAME.get(role_name)
    if role is None:
        return ""
    return getattr(config, role.source_field, "") or role.default_source


def date_key(config) -> str:
    return getattr(config, "source_date", "") or DEFAULT_DATE_KEY


def week_key(config) -> str:
    return getattr(config, "source_week", "") or DEFAULT_WEEK_KEY


def frontmatter_keys(limit: int = 4000) -> list[str]:
    """Return the distinct frontmatter keys present in the cached notes."""
    from reporting.models import SourceNote

    keys: set[str] = set()
    for frontmatter in SourceNote.objects.values_list("frontmatter", flat=True)[:limit]:
        if isinstance(frontmatter, dict):
            keys.update(str(key) for key in frontmatter)
    return sorted(keys, key=str.casefold)
