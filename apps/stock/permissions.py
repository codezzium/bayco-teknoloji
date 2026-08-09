"""Panel erişimi ve para bilgisi görünürlüğü.

İki rol vardır: **Patron** her şeyi görür, **Personel** stoğu görür ve satış
yapar ama maliyet, kâr ve ciro raporlarını göremez.

Rol modeli olarak Django grupları + özel bir izin seçildi:
  * StaffProfile.role olsaydı her view'a `if user.profile.role == ...` saçılır,
    profili olmayan superuser'da patlar ve bir signal gerektirirdi.
  * is_superuser kullanmak "parayı görebilir" ile "veritabanını silebilir"i
    aynı anahtara bağlardı.

DİKKAT — is_staff aynı zamanda /yonetim/ (Django admin) anahtarıdır. Personel
hesapları is_staff=False olmalıdır; aksi halde admin üzerinden Device
list_display'inde alış fiyatını görürler. Panel girişi bu yüzden is_staff'a
değil grup üyeliğine bağlanmıştır.
"""

from django.contrib.auth.decorators import user_passes_test

from apps.dashboard.forms import StyledModelForm

MONEY_PERM = "stock.view_money"
MANAGE_PERM = "stock.manage_stock"

GROUP_PATRON = "Patron"
GROUP_PERSONEL = "Personel"
PANEL_GROUPS = (GROUP_PATRON, GROUP_PERSONEL)


def in_panel(user) -> bool:
    """Panele girebilir mi? (is_staff DEĞİL — bkz. modül docstring'i)"""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=PANEL_GROUPS).exists()


def can_see_money(user) -> bool:
    """Maliyet / kâr / ciro görebilir mi? Superuser her izni geçer."""
    return bool(user and user.is_authenticated and user.has_perm(MONEY_PERM))


def can_manage_stock(user) -> bool:
    return bool(user and user.is_authenticated
                and (user.has_perm(MANAGE_PERM) or user.is_superuser))


panel_required = user_passes_test(in_panel, login_url="dashboard:login")
money_required = user_passes_test(can_see_money, login_url="dashboard:login")


class MoneyAwareModelForm(StyledModelForm):
    """Para alanlarını yetkisiz kullanıcı için formdan tamamen çıkarır.

    Yalnızca gizlemek yetmez: alan formda kalırsa Personel hem maliyeti
    <input> içinde görür hem de istediği değeri POST edebilir. Alanı pop
    etmek yazma yolunu da kapatır, çünkü ModelForm._post_clean var olmayan
    bir alanı yok sayar.
    """

    MONEY_FIELDS: list[str] = []

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if not can_see_money(user):
            for name in self.MONEY_FIELDS:
                self.fields.pop(name, None)
