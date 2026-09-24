"""Hareket kaydı yazma yardımcıları.

Kural: log yazımı isteği ASLA bozmaz. Her yazım kendi savepoint'inde ve
try/except içindedir; veritabanı hatası bile yalnızca sunucu loguna düşer.
"""

import logging
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.db import transaction
from django.utils import timezone

from .models import ActivityLog

logger = logging.getLogger(__name__)

RETENTION_DAYS = 365

#: Adında bunlardan biri geçen POST alanı loga HİÇ yazılmaz.
SECRET_MARKERS = ("password", "sifre", "şifre", "csrf", "token")
MAX_VALUE = 200
MAX_FIELDS = 40


def client_ip(request):
    """Vekil sunucu arkasında gerçek istemci adresi X-Forwarded-For'un ilk
    girdisidir. Bilgi amaçlıdır: başlık istemci tarafından uydurulabilir."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    try:
        validate_ipv46_address(ip)
    except ValidationError:
        return None
    return ip


def sanitize_post(request) -> dict:
    """POST verisinin loga yazılacak hali: sırlar yok, değerler kısaltılmış."""
    data = {}
    for key in request.POST:
        if len(data) >= MAX_FIELDS:
            break
        if any(marker in key.lower() for marker in SECRET_MARKERS):
            continue
        values = [value[:MAX_VALUE] for value in request.POST.getlist(key)]
        data[key] = values[0] if len(values) == 1 else values
    for key, upload in request.FILES.items():
        data[key] = f"dosya: {upload.name}"[:MAX_VALUE]
    return data


def record(*, kind, action, request=None, user=None, username="", target="",
           target_url="", view_name="", detail=None, status_code=None):
    if user is None and request is not None:
        user = getattr(request, "user", None)
    if user is not None and not user.is_authenticated:
        user = None
    try:
        with transaction.atomic():
            ActivityLog.objects.create(
                user=user,
                username=(username or getattr(user, "username", ""))[:150],
                kind=kind,
                action=str(action)[:160],
                target=str(target or "")[:200],
                target_url=(target_url or "")[:300],
                view_name=(view_name or "")[:100],
                path=request.path[:300] if request is not None else "",
                status_code=status_code,
                detail=detail or {},
                ip=client_ip(request) if request is not None else None,
                user_agent=(request.META.get("HTTP_USER_AGENT", "")[:200]
                            if request is not None else ""),
            )
    except Exception:  # log yazılamadı diye istek düşmesin
        logger.exception("Hareket kaydı yazılamadı: %s", action)


def log_denied(request):
    """Yetkisiz erişim denemesi. Middleware aynı isteği ikinci kez yazmaz."""
    from .actions import describe

    info = describe(request)
    record(
        kind=ActivityLog.Kind.YETKISIZ,
        action=info.label,   # tür sütunu zaten "Yetkisiz deneme" der
        request=request,
        target=info.target,
        view_name=info.view_name,
        detail=sanitize_post(request) if request.method == "POST" else {},
    )
    request._activity_logged = True


def prune(days=RETENTION_DAYS) -> int:
    """`days` günden eski kayıtları siler; silinen satır sayısını döner."""
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = ActivityLog.objects.filter(at__lt=cutoff).delete()
    return deleted
