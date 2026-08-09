"""
Django settings for Bayço Teknoloji.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Üretimde: ortam değişkenleriyle geçersiz kılın.
# export DJANGO_SECRET_KEY=... DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=alanadiniz.com
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-g4o)v-5z7d@gu^@80j$707gg5&t#$wytql8$wzso1!r!dxd*ou",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",") if o
]

# nginx TLS'i origin'de sonlandırıp X-Forwarded-Proto gönderiyor. Bu olmadan
# request.scheme "http" kalır ve robots.txt / sitemap.xml http:// URL üretir.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    # Local apps
    "apps.sitecore",
    "apps.catalog",
    "apps.leads",
    "apps.website",
    "apps.dashboard",
    "apps.stock",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.sitecore.context_processors.site_globals",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
#
# transaction_mode="IMMEDIATE" stok modülü için zorunlu: her servis fonksiyonu
# transaction içinde oku-sonra-yaz yapıyor ve SQLite'ın DEFERRED varsayılanında
# iki eşzamanlı okutma "database is locked" üretir. IMMEDIATE yazma kilidini
# BEGIN anında alır. WAL, panel yazarken sitenin okumaya devam etmesini sağlar.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True


# Static files
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Non-manifest: works in dev without collectstatic. For production
        # cache-busting, switch to whitenoise.storage.CompressedManifestStaticFilesStorage
        # and run `manage.py collectstatic`.
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# Media files (uploads)
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Auth / panel
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "dashboard:login"


# Güvenlik (üretim)
#
# Kamera ile barkod okutma YALNIZCA güvenli bağlamda (https:// veya localhost)
# çalışır — http://192.168.x.x üzerinde navigator.mediaDevices tanımsızdır.
# TLS sonlandıran bir proxy (Caddy/nginx) arkasında SECURE_PROXY_SSL_HEADER
# ayarlanmadan SECURE_SSL_REDIRECT açılırsa sonsuz yönlendirme döngüsü olur.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
