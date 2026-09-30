# Contributing

## Setup

```bash
python -m venv .venv
```

Activate it with `.venv\Scripts\activate` on Windows or
`source .venv/bin/activate` on macOS and Linux, then:

```bash
pip install -r requirements.txt
```

Copy `config.example.yaml` to `config.yaml` (`copy` on Windows, `cp` elsewhere)
and run `python manage.py migrate`.

`config.yaml` is git-ignored. Point `vault.path` at a throwaway vault, or leave
it empty: the test suite builds its own temporary vaults and never reads yours.

## Before you open a pull request

```bash
python manage.py check
python manage.py test
ruff check .
ruff format .
```

`pre-commit install` runs the same lint and format checks on every commit.

## Guidelines

- Keep the dashboard usable without JavaScript changes beyond `static/reporting/`.
- New settings belong on `TaskLayoutConfig`, not in `config.yaml`. Only values
  Django needs at startup belong in `config.yaml`.
- If you add a model field, run `python manage.py makemigrations reporting` and
  commit the migration.
- Report a parse problem as a `ParseWarning` rather than dropping the row.
- Do not commit `config.yaml`, `db.sqlite3`, or anything under `.venv/`.

## Publishing a release copy

```bash
python tools/build_public_release.py
```

This writes a sanitised copy to `dist/task-dashboard/` and fails if it finds a
machine-specific path. Add any personal tokens worth checking to
`tools/.release_blocklist.local`; that file is git-ignored.
