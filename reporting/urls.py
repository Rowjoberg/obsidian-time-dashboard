from django.urls import path

from reporting import views

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("refresh-cache/", views.refresh_cache_view, name="refresh_cache"),
    path("summary/", views.summary_view, name="summary"),
    path("entries/", views.entries_view, name="entries"),
    path("warnings/", views.warnings_view, name="warnings"),
]
