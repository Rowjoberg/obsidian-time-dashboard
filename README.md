# Task Dashboard

A local Django dashboard that turns `- [t]` rows in Obsidian daily notes into
time-allocation charts, summaries, and warnings.

Nothing leaves your machine: the app reads your vault, caches what it parses in
a local SQLite file, and serves it on `127.0.0.1`.

## Features

- scans `- [t]` task rows from your daily notes
- resolves linked notes across the vault and reads their frontmatter
- reads durations from timestamps, or from an hours value on the line
- dashboard, grouped summary, entry, and warning views
- multi-select filtering on linked-note metadata
- day / week / month / year periods, with matching chart granularity
- task layout and field mapping configurable in the web admin, no code edits

## Requirements

- Python 3.12 or newer
- An Obsidian vault with daily notes containing `- [t]` rows

## Setup

```bash
python -m venv .venv
```

Activate the environment:

| Platform | Command |
| --- | --- |
| Windows | `.venv\Scripts\activate` |
| macOS / Linux | `source .venv/bin/activate` |

Create your config file:

| Platform | Command |
| --- | --- |
| Windows | `copy config.example.yaml config.yaml` |
| macOS / Linux | `cp config.example.yaml config.yaml` |

Then, on any platform:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py refresh_notes
python manage.py runserver
```

With the server running, open:

| URL | Purpose |
| --- | --- |
| <http://127.0.0.1:8000/> | Dashboard with charts |
| <http://127.0.0.1:8000/summary/> | Grouped summary |
| <http://127.0.0.1:8000/entries/> | Raw entry table |
| <http://127.0.0.1:8000/warnings/> | Parse warnings |
| <http://127.0.0.1:8000/admin/> | Django admin, including task layout settings |

`python main.py` prints the same command list if you forget it.

### Creating the admin user

The report pages need no login, but **the task layout settings do**: they live
in the Django admin at `/admin/reporting/tasklayoutconfig/`, which is linked as
**Settings** in the nav bar.

```bash
python manage.py createsuperuser
```

You need this before you can point the app at your vault, because the vault path
is one of the settings. Run it before the first `refresh_notes`. To change the
superuser password later, use `python manage.py changepassword <username>`.

### Configuration

Configuration lives in two places.

**`config.yaml`** holds the process-level values Django needs before it starts.
It is git-ignored, so keep it local.

| Key | Default | Meaning |
| --- | --- | --- |
| `app.secret_key` | `change-me-for-production` | Django secret key. Change it before exposing the app anywhere. |
| `app.debug` | `true` | Debug mode. Keep this off for anything but local use. |
| `app.allowed_hosts` | `127.0.0.1`, `localhost` | Hostnames Django will serve. |
| `app.time_zone` | `Australia/Sydney` | Time zone used for grouping and labels. |
| `vault.path` | *(empty)* | Absolute path to your Obsidian vault. Seeded into the admin on first use. |
| `vault.daily_notes_path` | `Automated Notes/Daily Notes` | Folder inside the vault holding daily notes. |
| `reporting.default_period` | `month` | Period selected on first load. |
| `reporting.default_group_by` | `display_title` | Initial grouping. |
| `reporting.invalid_durations_in_totals` | `false` | Whether rows with an unusable duration count toward totals. |

**The database** holds the task layout and reporting defaults, edited at
`/admin/reporting/tasklayoutconfig/`. On first use the row is seeded from
`config.yaml`; after that the database copy is authoritative and `config.yaml`
only supplies the values Django reads at startup.

The source-key dropdowns in the admin are populated from the frontmatter keys
found in your imported notes, so import once before choosing them.

#### Task layout

| Option | Default | Meaning |
| --- | --- | --- |
| `identifier` | `- [t]` | Literal text that starts a task line. |
| `task_region` | `after-identifier` | Which part of the line holds the title. `after-identifier` cuts at the first time value, `before-start` cuts at the start marker, `title-only` also drops trailing metadata. |
| `hours_mode` | off | Take the duration from `hours_pattern` instead of the timestamps. |
| `hours_pattern` | `[hours]\s*h\b\|[H]:[M]\b` | Matches `2.5h`, `2,5h`, `2:30`, or `0:45`. |
| `start_time_pattern` | `🛫 YYYY-MM-DD HH:mm` | Start timestamp marker. |
| `end_time_pattern` | `📅 YYYY-MM-DD HH:mm` | End timestamp marker. |

Tokens are substituted for you and everything else is passed through as a
regular expression fragment, so alternation and character classes work:

- date/time tokens: `YYYY`, `YY`, `MM`, `DD`, `HH`, `mm`
- hours tokens: `[hours]` (decimal hours), `[H]` (hours), `[M]` (minutes)
- tokens may be bare (`YYYY-MM-DD`) or bracketed (`[YYYY]-[MM]`)
- a bare token is ignored when followed by a letter, so `Done` is not read as a day
- the identifier is matched literally, so regex metacharacters in it are safe
- with `hours_mode` on, timestamps are still parsed when present, so the heatmap
  and time-of-day breakdowns keep working

#### Field mapping

Each role points at a frontmatter key on the linked note. The defaults suit a
Jira-style vault; change them to match yours. The label fields control the
heading text, so the interface stays readable whatever your keys are called.

| Option | Default | Meaning |
| --- | --- | --- |
| `source_unique_identifier` | `jiraTask` | Key holding the task's external identifier. |
| `source_workstream` | `project` | Key holding the project or workstream. |
| `source_status` | `status` | Key holding status. |
| `source_priority` | `priority` | Key holding priority. |
| `source_owner` | `assignee` | Key holding the owner. |
| `source_date` | `date` | Key holding the task date. |
| `source_week` | `week` | Key holding the week label. |
| `label_unique_identifier` | `Unique Identifier` | Heading for the identifier column. |
| `label_workstream` | `Workstream` | Heading for the workstream column. |
| `label_status` | `Status` | Heading for the status column. |
| `label_priority` | `Priority` | Heading for the priority column. |
| `label_owner` | `Owner` | Heading for the owner column. |

#### Resolved state

| Option | Default | Meaning |
| --- | --- | --- |
| `resolved_when` | `link-resolved` | `link-resolved`, `checkbox-complete`, `tag`, or `frontmatter`. |
| `completed_identifier` | `- [x]` | Used when `resolved_when` is `checkbox-complete`. |
| `resolved_tag` | `#done` | Used when `resolved_when` is `tag`. |
| `resolved_field` | `status` | Frontmatter key compared when `resolved_when` is `frontmatter`. |
| `resolved_value` | `done` | Value that counts as resolved. |

#### Durations and filters

| Option | Default | Meaning |
| --- | --- | --- |
| `round_duration_to` | `0` (off) | Round durations to 1, 5, or 15 minutes. |
| `min_duration_minutes` | `0` | Drop durations below this many minutes. |
| `overnight_hours` | off | Treat an end time earlier than the start as crossing midnight. |
| `ignored_frontmatter_keys` | *(empty)* | Frontmatter keys to skip when building filters, one per line. |
| `include_invalid_durations_in_totals` | off | Count rows with an unusable duration in totals. |

Changing the layout only affects new imports. Run `python manage.py refresh_notes`
or press **Refresh Cache** to re-parse the vault.

## Importing

`refresh_notes` scans `daily_notes_path`, resolves each linked note, and rebuilds
the cache in one pass. Import is currently a full rebuild, so it is safe to run
repeatedly. Rows that cannot be parsed are listed at `/warnings/` rather than
being dropped silently.

Sample daily note:

```markdown
---
date: 2026-03-30
week: 2026-W14
---
## Tasks
- [t] [[Obsidian Task Note]] 🛫 2026-03-30 12:30 📅 2026-03-30 15:00
```

## Development

```bash
pip install -r requirements.txt
python manage.py test          # test suite
ruff check . && ruff format .  # lint and format
pre-commit install             # optional: run checks on commit
```

Dependencies are declared in `pyproject.toml`. `requirements.txt` and `uv.lock`
are generated from it:

```bash
uv lock
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
```

### Project layout

| Path | Contents |
| --- | --- |
| `task_dashboard/` | Django project: settings, URLs, `config.yaml` loading. |
| `reporting/models.py` | `SourceNote`, `TaskEntry`, `TaskLayoutConfig`, warnings. |
| `reporting/services/layout.py` | Pattern compilation and value parsing. |
| `reporting/services/notes.py` | Vault scanning and task-row parsing. |
| `reporting/services/reports.py` | Filtering and period aggregation. |
| `reporting/services/roles.py` | Field roles, labels, frontmatter keys. |
| `reporting/services/settings_store.py` | Reads and seeds the config row. |
| `reporting/management/commands/refresh_notes.py` | The import command. |
| `templates/`, `static/` | Templates, CSS, and the Chart.js front end. |

## Privacy

- `db.sqlite3` caches your parsed vault: task titles, notes, and metadata. It is
  git-ignored and must never be committed.
- The SQLite copy of `TaskLayoutConfig` also stores your vault path, so a shared
  database leaks it too.
- The report pages have **no authentication** and the default config has
  `debug: true`. This is a localhost-only tool. Do not expose it to a network
  unless you add authentication, turn `debug` off, and set a real `secret_key`.
- Before sharing the code, run `python tools/build_public_release.py`. It copies
  only the safe files into `dist/task-dashboard/`, substitutes
  `config.example.yaml` for your real config, and fails the build if any
  machine-specific path is still present. Personal tokens for that check live in
  the git-ignored `tools/.release_blocklist.local`.

## Known limitations

- import is a full rebuild on every run
- only `- [t]` rows are read; the marker is configurable but single
- durations come from timestamps or one hours value, not from summed sub-tasks

## License

MIT, see [LICENSE](LICENSE).
