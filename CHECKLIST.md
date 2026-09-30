# Task Dashboard Checklist

## Project Setup
- [ ] Create Python virtual environment in `.venv`
- [ ] Install dependencies: `django`, `pyyaml`, `python-dateutil`
- [ ] Create Django project in the repository root
- [ ] Create Django app named `reporting`
- [ ] Add a `.gitignore` for `.venv`, `db.sqlite3`, `__pycache__`, local config, and local env files

## Configuration
- [ ] Copy `config.example.yaml` to `config.yaml` and set `vault.path` to your Obsidian vault
- [ ] Set `vault.daily_notes_path` to your daily notes folder
- [ ] Confirm local-only settings: `DEBUG=True`, `ALLOWED_HOSTS=127.0.0.1,localhost`
- [ ] Configure templates, static files, and SQLite defaults

## Data Model
- [ ] Create `SourceNote` model for source file tracking and import state
- [ ] Create `TaskEntry` model for parsed timed task rows
- [ ] Create `TaskEntryFacet` model for repeatable metadata filters
- [ ] Create `ParseWarning` model for malformed lines and unresolved links
- [ ] Add migrations and run initial database setup

## Parsing and Import
- [ ] Build daily-note scanner for markdown files under `Automated Notes/Daily Notes`
- [ ] Parse daily-note frontmatter fields like `date` and `week`
- [ ] Extract `- [t]` task lines and timestamps from `🛫 ...` and `📅 ...`
- [ ] Compute task duration in minutes
- [ ] Resolve primary linked note using the first non-embed wiki link
- [ ] Strip heading anchors like `#2025-04-22` before note resolution
- [ ] Load linked note frontmatter with `PyYAML`
- [ ] Normalize scalar fields onto `TaskEntry`
- [ ] Normalize repeatable fields into `TaskEntryFacet`
- [ ] Record parse warnings for malformed rows, unresolved notes, and invalid durations
- [ ] Add a `refresh_notes` Django management command

## Metadata and Filtering
- [ ] Index scalar metadata: `jiraTask`, `project`, `status`, `priority`, `assignee`, `noteFamily`
- [ ] Index repeatable metadata: `jobNumber`, `changeRequest`, `sytelineItem`, `labels`, `components`, `tags`
- [ ] Implement OR logic within a field and AND logic across fields
- [ ] Support repeated query params for multi-select filters
- [ ] Exclude invalid-duration rows from totals by default while keeping them visible in detail views

## Aggregation
- [ ] Build a service for daily summaries
- [ ] Build a service for weekly summaries
- [ ] Build a service for monthly summaries
- [ ] Build a service for custom date-range summaries
- [ ] Add grouping by task title, `jobNumber`, `jiraTask`, `changeRequest`, `project`, and `noteFamily`

## UI
- [ ] Create dashboard page at `/`
- [ ] Create grouped summary page at `/summary/`
- [ ] Create raw entry page at `/entries/`
- [ ] Create warnings page at `/warnings/`
- [ ] Add searchable multi-select widgets for filters
- [ ] Add summary cards for total hours, entry count, resolved count, and warning count
- [ ] Add charts with `Chart.js` for allocation and trend views
- [ ] Keep filter state consistent across pages

## Testing
- [ ] Add parser tests for standard linked tasks
- [ ] Add parser tests for plain-text tasks
- [ ] Add parser tests for multiple links on one task line
- [ ] Add parser tests for malformed wiki links and bad timestamps
- [ ] Add note-resolution tests for basename and path-based links
- [ ] Add aggregation tests for daily, weekly, monthly, and custom periods
- [ ] Add filter tests for multi-select OR/AND behavior

## Developer Workflow
- [ ] Document setup steps in `README.md`
- [ ] Document import and refresh commands
- [ ] Document known parsing limitations and warning behavior
- [ ] Add a sample run sequence: migrate, refresh, runserver

## Nice-to-Have After MVP
- [ ] Incremental imports based on modified time or content hash
- [ ] CSV export for filtered summaries
- [ ] Saved filter presets
- [ ] Manual refresh button in the UI
