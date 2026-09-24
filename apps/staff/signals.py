"""Giriş / çıkış / hatalı giriş kayıtları ve eski logların temizliği."""

from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver

from . import audit
from .models import ActivityLog


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    audit.record(kind=ActivityLog.Kind.GIRIS, action="Giriş yaptı",
                 request=request, user=user)
    # Saklama süresi: cron yok, günde en az bir giriş var. Tek indeksli DELETE.
    audit.prune()


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is None:
        return
    audit.record(kind=ActivityLog.Kind.CIKIS, action="Çıkış yaptı",
                 request=request, user=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    # credentials içinde şifre YOKTUR (Django maskeler), yine de yalnızca
    # kullanıcı adını alıyoruz.
    username = str(credentials.get("username", ""))[:150]
    audit.record(kind=ActivityLog.Kind.HATALI_GIRIS, action="Hatalı giriş denemesi",
                 request=request, user=None, username=username,
                 target=username)
