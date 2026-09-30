"""Build a publishable copy of the project in dist/task-dashboard.

Only files on SAFE_FILES/SAFE_TREES are copied, so personal data (the real
config.yaml, the SQLite vault cache, virtualenvs, git data) can never be
included. Generic path checks then run over every copied file and the build
fails if anything still looks machine-specific.

Personal specifics (your username, internal work-item prefixes, project codes)
are deliberately NOT hardcoded here, because this file ships with the release.
Put them in tools/.release_blocklist.local, which is git-ignored.

Usage:
    python tools/build_public_release.py
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist" / "task-dashboard"
LOCAL_BLOCKLIST = ROOT / "tools" / ".release_blocklist.local"

SAFE_FILES = [
    ".gitignore",
    ".pre-commit-config.yaml",
    ".python-version",
    "CHECKLIST.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "config.example.yaml",
    "main.py",
    "manage.py",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
]
SAFE_TREES = [".github", "reporting", "static", "task_dashboard", "templates", "tools"]
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite3", ".sqlite"}

# Must never appear in a release, whatever else changes.
FORBIDDEN_NAMES = {"config.yaml", "db.sqlite3", ".env", ".venv", ".git"}

# A Windows user profile is only a leak when the name is not a documentation
# placeholder such as C:\Users\me\Obsidian.
USER_HOME_PATTERN = re.compile(r"[A-Z]:\\+Users\\+([A-Za-z0-9._-]+)")
USER_HOME_ALLOWLIST = {
    "me",
    "myuser",
    "youruser",
    "yourname",
    "your-username",
    "username",
    "example",
}
LOCAL_PATH_PATTERN = re.compile(r"[A-Z]:\\+(dev|Users\\+Public|tmp|home)\\+", re.IGNORECASE)
SECRET_PATTERN = re.compile(r"secret_key\s*[:=]\s*['\"]?(?!\s*(change-me|$|null|none|example))\S{12,}")


def load_blocklist() -> list[re.Pattern[str]]:
    if not LOCAL_BLOCKLIST.is_file():
        return []
    patterns = []
    for raw in LOCAL_BLOCKLIST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(re.compile(line, re.IGNORECASE))
    return patterns


def iter_safe_files() -> list[Path]:
    found = []
    for name in SAFE_FILES:
        source = ROOT / name
        if source.is_file():
            found.append(source)

    for tree in SAFE_TREES:
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            if EXCLUDED_DIRS & set(relative.parts):
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            if path.name in FORBIDDEN_NAMES:
                continue
            if path == LOCAL_BLOCKLIST or path.name.startswith("."):
                continue
            found.append(path)
    return sorted(found)


def line_is_leaky(line: str, blocklist: list[re.Pattern[str]]) -> bool:
    if SECRET_PATTERN.search(line):
        return True
    if LOCAL_PATH_PATTERN.search(line):
        return True
    if any(match.group(1).lower() not in USER_HOME_ALLOWLIST for match in USER_HOME_PATTERN.finditer(line)):
        return True
    return any(pattern.search(line) for pattern in blocklist)


def verify(paths: list[Path], blocklist: list[re.Pattern[str]]) -> list[str]:
    problems = []
    for path in paths:
        relative = path.relative_to(OUTPUT).as_posix()
        if relative in FORBIDDEN_NAMES:
            problems.append(f"{relative}: must never be published")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if line_is_leaky(line, blocklist):
                problems.append(f"{relative}:{number}: {line.strip()[:100]}")
    return problems


def main() -> int:
    blocklist = load_blocklist()
    if not blocklist:
        print(f"note: no local blocklist at {LOCAL_BLOCKLIST.name}, running generic checks only")

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    written = []
    for source in iter_safe_files():
        relative = source.relative_to(ROOT)
        target = OUTPUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(target)

    problems = verify(written, blocklist)
    if problems:
        shutil.rmtree(OUTPUT)
        print("Release build aborted, possible leaks found:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"Wrote {len(written)} files to {OUTPUT.relative_to(ROOT)}")
    print("Recipients create config.yaml from config.example.yaml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
