from django.conf import settings
from django.db import models
from django.utils import timezone

from .access import staff_permissions


class PanelAccess(models.Model):
    """Tablosu olmayan izin taşıyıcısı.

    Personel sayfasındaki tikler Django izinleridir (user.user_permissions)
    ve her izin bir modele bağlı olmak zorundadır. managed=False tablo
    yaratmaz; Django yine de bu Meta.permissions satırlarını her `migrate`
    sonunda (post_migrate) oluşturur. Liste apps/staff/access.py'den gelir.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = staff_permissions()
        verbose_name = "Panel yetkisi"
        verbose_name_plural = "Panel yetkileri"


class ActivityLog(models.Model):
    """Paneldeki her işlemin kaydı. Yalnızca Patron görür.

    `username` ve `target` kayıt anındaki METİNDİR: kullanıcı ya da nesne
    sonradan silinse/yeniden adlandırılsa da log okunur kalır.
    """

    class Kind(models.TextChoices):
        GIRIS = "giris", "Giriş"
        CIKIS = "cikis", "Çıkış"
        HATALI_GIRIS = "hatali_giris", "Hatalı giriş"
        ISLEM = "islem", "İşlem"
        YETKISIZ = "yetkisiz", "Yetkisiz deneme"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="activity_logs",
                             verbose_name="Kullanıcı")
    username = models.CharField("Kullanıcı adı", max_length=150, blank=True)
    at = models.DateTimeField("Zaman", default=timezone.now, db_index=True)
    kind = models.CharField("Tür", max_length=16, choices=Kind.choices,
                            default=Kind.ISLEM)
    action = models.CharField("İşlem", max_length=160)
    target = models.CharField("Kayıt", max_length=200, blank=True)
    target_url = models.CharField(max_length=300, blank=True)
    view_name = models.CharField(max_length=100, blank=True)
    path = models.CharField(max_length=300, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    detail = models.JSONField("Girilen değerler", default=dict, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("Cihaz", max_length=200, blank=True)

    class Meta:
        verbose_name = "Hareket kaydı"
        verbose_name_plural = "Hareket kayıtları"
        ordering = ["-at", "-id"]
        indexes = [
            models.Index(fields=["user", "at"]),
            models.Index(fields=["kind", "at"]),
        ]

    def __str__(self):
        return f"{self.at:%d.%m.%Y %H:%M} · {self.username} · {self.action}"
