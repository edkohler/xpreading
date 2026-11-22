import logging
import os
from pathlib import Path

import environ
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
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])


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
    "django.contrib.sitemaps",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "crispy_forms",
    "crispy_bootstrap5",
    # "debug_toolbar",
    "storages",
    "accounts",
    "pages",
    "import_export",
    "django.contrib.humanize",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # "debug_toolbar.middleware.DebugToolbarMiddleware",
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
# STATIC_URL = "/static/"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.CustomUser"
SITE_ID = 1

# ---------------------------------------------------------------------------
# Authentication (django-allauth): username/email accounts + Google sign-in
# ---------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    # Needed to log in by username in Django admin, regardless of allauth
    "django.contrib.auth.backends.ModelBackend",
    # allauth-specific authentication methods, such as login by email
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "my_books"  # used when there is no ?next= to return to
ACCOUNT_LOGOUT_REDIRECT_URL = "home"

# Kids can sign in with either their username or their email address
ACCOUNT_LOGIN_METHODS = {"username", "email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "optional"  # a confirmation email is sent, not required
ACCOUNT_SESSION_REMEMBER = None  # show a "Remember me" checkbox
ACCOUNT_FORMS = {"login": "accounts.allauth_forms.XPLoginForm"}
ACCOUNT_LOGIN_ON_PASSWORD_RESET = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = False
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[XP Reading] "

# Google sign-in. Credentials come from the GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
# environment variables (.env locally, `fly secrets` in production). If they are
# not set, the Google button is simply hidden.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online", "prompt": "select_account"},
        "EMAIL_AUTHENTICATION": True,
        "APPS": (
            [{"client_id": GOOGLE_CLIENT_ID, "secret": GOOGLE_CLIENT_SECRET, "key": ""}]
            if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
            else []
        ),
    }
}
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"  # Google has already verified the address
# If someone who signed up with email+password later clicks "Continue with Google"
# using the same (Google-verified) address, log them into that existing account
# and link Google to it instead of failing or creating a duplicate.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Domain used for absolute URLs in /sitemap.xml and robots.txt
SITEMAP_DOMAIN = env("SITEMAP_DOMAIN", default="xpreading.com")
CRISPY_TEMPLATE_PACK = "bootstrap5"


# AWS S3 Settings
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")  # replace with your key
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")  # replace with your secret
AWS_STORAGE_BUCKET_NAME = os.getenv(
    "AWS_STORAGE_BUCKET_NAME"
)  # replace with your bucket name
AWS_S3_REGION_NAME = "us-east-1"  # replace with your region
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"

# Static files
STATICFILES_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # Local directory for collectstatic

# Media files
DEFAULT_FILE_STORAGE = "django_project.storage_backends.MediaStorage"

# MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'

AWS_S3_FILE_OVERWRITE = False  # Don't overwrite files with the same name
# AWS_DEFAULT_ACL = 'public-read'  # Make files publicly readable
AWS_S3_SIGNATURE_VERSION = "s3v4"  # Important for certain regions

ASIN_DATA_API_KEY = os.getenv("ASIN_DATA_API_KEY")


AMAZON_API = {
    "AMAZON_PRODUCT_ADVERTISING_ACCESS_KEY": os.getenv(
        "AMAZON_PRODUCT_ADVERTISING_ACCESS_KEY"
    ),
    "AMAZON_PRODUCT_ADVERTISING_SECRET_KEY": os.getenv(
        "AMAZON_PRODUCT_ADVERTISING_SECRET_KEY"
    ),
    "AMAZON_PRODUCT_ADVERTISING_REGION": os.getenv("AMAZON_PRODUCT_ADVERTISING_REGION"),
    "AMAZON_PRODUCT_ADVERTISING_ASSOCIATE_TAG": os.getenv(
        "AMAZON_PRODUCT_ADVERTISING_ASSOCIATE_TAG"
    ),
}

ASINDATAAPI = os.environ.get("ASINDATAAPI")


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django_project.storage_backends": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
        "boto3": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
        "botocore": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
    },
}
