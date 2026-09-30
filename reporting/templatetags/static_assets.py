import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders

register = template.Library()


@register.simple_tag
def versioned_static(asset_path):
    """Return an absolute static URL carrying the asset's mtime as a cache-buster.

    Without the query string browsers keep serving a stale copy of app.js/app.css,
    which silently breaks the dashboard when the chart payload shape changes.
    """
    url = f"/{settings.STATIC_URL.lstrip('/')}{asset_path.lstrip('/')}"
    source_path = finders.find(asset_path)
    if not source_path:
        return url
    try:
        modified_at = int(os.path.getmtime(source_path))
    except OSError:
        return url
    return f"{url}?v={modified_at}"
