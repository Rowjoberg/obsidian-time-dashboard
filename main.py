"""Print the standard commands for working on this project."""

import sys

WINDOWS_STEPS = [
    ".venv\\Scripts\\activate",
    "copy config.example.yaml config.yaml",
]
POSIX_STEPS = [
    "source .venv/bin/activate",
    "cp config.example.yaml config.yaml",
]
SHARED_STEPS = [
    "pip install -r requirements.txt",
    "python manage.py migrate",
    "python manage.py createsuperuser",
    "python manage.py refresh_notes",
    "python manage.py runserver",
]


def main() -> int:
    if len(sys.argv) > 1:
        print(f"unknown argument: {sys.argv[1]}", file=sys.stderr)
        return 2

    platform_steps = WINDOWS_STEPS if sys.platform == "win32" else POSIX_STEPS
    steps = ["python -m venv .venv", *platform_steps, *SHARED_STEPS]

    print("Setup and run this project with:")
    print()
    for step in steps:
        print(f"  {step}")
    print()
    print("Then open http://127.0.0.1:8000/ for the dashboard and")
    print("http://127.0.0.1:8000/admin/ to configure the task layout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
