from .base import *

DEBUG = False

ALLOWED_HOSTS = [
    "xpreading.com",
    "www.xpreading.com",
    "*.xpreading.com",
    "katyreads.fly.dev",
]
# Add production-specific security settings
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# S3 for static and media files
"""
AWS_STORAGE_BUCKET_NAME = "xpreading"
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"

STATICFILES_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
"""


"""
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.your-email-provider.com"
EMAIL_PORT = 587  # Use 465 for SSL, 587 for TLS
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "your-email@example.com"
EMAIL_HOST_PASSWORD = "your-email-password"
DEFAULT_FROM_EMAIL = "your-email@example.com"
"""


# Outgoing email (password resets, email confirmations).
# Set SENDGRID_API_KEY with `fly secrets set` to send real email through SendGrid.
# Without it, emails are written to the app log instead of crashing the request.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="XP Reading <noreply@xpreading.com>")
SERVER_EMAIL = env("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
SENDGRID_API_KEY = env("SENDGRID_API_KEY", default="")
if SENDGRID_API_KEY:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.sendgrid.net"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = "apikey"
    EMAIL_HOST_PASSWORD = SENDGRID_API_KEY
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Make sure allauth builds https:// callback URLs (Google requires an exact match)
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"
