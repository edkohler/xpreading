from pathlib import Path
import os
import environ
import logging
import sentry_sdk



sentry_sdk.init(
    dsn="https://382707f0c49ac83738b5f83aa6df88b7@o4508541680091136.ingest.us.sentry.io/4508541680418816",
)

env = environ.Env(DEBUG=(bool, False))

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_URLCONF = "django_project.urls"

# Load environment variables
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

# General settings
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1"]
)


# Installed apps, middleware, templates, etc.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount.providers.google",
    "crispy_forms",
    "crispy_bootstrap5",
    #"debug_toolbar",
    "accounts",
    "pages",
    "import_export",
    "storages",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    #"debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# Database
DATABASES = {
    "default": env.db(),
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # Add your custom template directory here
        "APP_DIRS": True,  # Ensure this is set to True
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",  # Required by Django admin
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Static and media files
#STATIC_URL = "/static/"



DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.CustomUser"
SITE_ID=1
CRISPY_TEMPLATE_PACK = "bootstrap5"
# S3 Configuration for AWS
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
AWS_S3_REGION_NAME = env("AWS_REGION", default="us-east-1")
AWS_STORAGE_BUCKET_NAME = 'xpreading'
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',
}

# Static files configuration
AWS_LOCATION = 'static'  # Static files location in S3
STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_LOCATION}/"

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),  # Local static directory for development
]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')  # Collectstatic directory

# Media files configuration
DEFAULT_FILE_STORAGE = "django_project.storage_backends.MediaStorage"
MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": "media_upload_debug.log",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["file"],
            "level": "DEBUG",
            "propagate": True,
        },
    },
}
