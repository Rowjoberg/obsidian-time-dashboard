from pathlib import Path

from task_dashboard.config import load_project_config

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG = load_project_config(BASE_DIR)

SECRET_KEY = CONFIG["app"]["secret_key"]
DEBUG = CONFIG["app"]["debug"]
ALLOWED_HOSTS = CONFIG["app"]["allowed_hosts"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "reporting",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "task_dashboard.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "task_dashboard.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-au"
TIME_ZONE = CONFIG["app"]["time_zone"]
USE_I18N = True
USE_TZ = False

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

OBSIDIAN_VAULT_PATH = Path(CONFIG["vault"]["path"])
OBSIDIAN_DAILY_NOTES_PATH = CONFIG["vault"]["daily_notes_path"]
REPORTING_DEFAULT_PERIOD = CONFIG["reporting"]["default_period"]
REPORTING_DEFAULT_GROUP_BY = CONFIG["reporting"]["default_group_by"]
REPORTING_INCLUDE_INVALID_DURATIONS_IN_TOTALS = CONFIG["reporting"]["invalid_durations_in_totals"]
