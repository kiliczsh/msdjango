"""Fast isolated local tests; Docker tests use the PostgreSQL settings instead."""

from config.settings import *  # noqa: F403
from config.settings import MIDDLEWARE as APPLICATION_MIDDLEWARE

MIDDLEWARE = [item for item in APPLICATION_MIDDLEWARE if "whitenoise" not in item]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
