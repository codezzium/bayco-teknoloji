"""Panel erişimi, sayfa yetkileri ve para bilgisi görünürlüğü.

İki rol vardır: **Patron** her şeyi görür ve personeli yönetir. **Personel**
stoğu görür ve satış yapar; bunun ötesindeki her şey Patron'un Personel
sayfasından verdiği tiklere bağlıdır (kayıt defteri: apps/staff/access.py).

Tikler Django'nun kendi user_permissions'ında durur:
  * StaffProfile.role/bool alanları olsaydı her view'a `if user.profile...`
    saçılır, profili olmayan superuser'da patlar ve bir signal gerektirirdi.
  * is_superuser kullanmak "parayı görebilir" ile "veritabanını silebilir"i
    aynı anahtara bağlardı.

Patron olmak bir tik DEĞİLDİR: superuser ya da Patron grubu üyeliğidir ve
has_access() Patron için her anahtarı açar. Bu, Patron grubunun izinlerinin
seed_roles ile güncel tutulmasına bağımlı kalmamak içindir (deploy yalnızca
migrate çalıştırır). Personel sayfası ve hareket kayıtları yalnızca Patron'a
açıktır; böylece bir personel kendine yetki veremez.

DİKKAT — is_staff aynı zamanda /yonetim/ (Django admin) anahtarıdır. Personel
hesapları is_staff=False olmalıdır; aksi halde admin üzerinden Device
list_display'inde alış fiyatını görürler. Panel girişi bu yüzden is_staff'a
değil grup üyeliğine bağlanmıştır.
"""

from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse
from django.shortcuts import redirect

from apps.dashboard.forms import StyledModelForm
from apps.staff.access import ACCESS  # view'lar ve şablonlar tikleri buradan alır

MONEY_PERM = "stock.view_money"
MANAGE_PERM = "stock.manage_stock"

GROUP_PATRON = "Patron"
GROUP_PERSONEL = "Personel"
PANEL_GROUPS = (GROUP_PATRON, GROUP_PERSONEL)

DENIED_MESSAGE = "Bu işlem için yetkiniz yok."


def in_panel(user) -> bool:
    """Panele girebilir mi? (is_staff DEĞİL — bkz. modül docstring'i)"""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_staff:
        return True
    cached = getattr(user, "_in_panel", None)
    if cached is None:
        cached = user._in_panel = user.groups.filter(name__in=PANEL_GROUPS).exists()
    return cached


def is_patron(user) -> bool:
    """Superuser ya da Patron grubu üyesi. Maliyet görmek Patron YAPMAZ."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    cached = getattr(user, "_is_patron", None)
    if cached is None:
        cached = user._is_patron = user.groups.filter(name=GROUP_PATRON).exists()
    return cached


def has_access(user, key: str) -> bool:
    """Personel sayfasındaki `key` tikine sahip mi? Patron her tike sahiptir.

    Bilinmeyen anahtar KeyError verir: yazım hatası sessizce "yetkisiz"e
    dönüşüp bir sayfayı herkese kapatmasın.
    """
    perm = ACCESS[key].perm
    if is_patron(user):
        return True
    return in_panel(user) and user.has_perm(perm)


def can_see_money(user) -> bool:
    """Maliyet / kâr / sermaye görebilir mi?"""
    return has_access(user, "money")


def can_manage_stock(user) -> bool:
    return bool(user and user.is_authenticated
                and (user.has_perm(MANAGE_PERM) or user.is_superuser))


def deny(request, message=DENIED_MESSAGE):
    """Panel kullanıcısının yetkisiz isteği: log + mesaj + ana sayfa.

    htmx isteğinde yönlendirme verilmez: htmx 302'yi izler ve ana sayfayı
    istek hedefinin (örn. #cart) içine swap eder. 204 + HX-Refresh sayfayı
    yeniler ve mesaj görünür (crud_delete'teki kalıp).
    """
    from apps.staff.audit import log_denied

    log_denied(request)
    messages.error(request, message)
    if request.headers.get("HX-Request") == "true":
        return HttpResponse(status=204, headers={"HX-Refresh": "true"})
    return redirect("dashboard:home")


def _gate(test):
    """Panel dışındakini girişe, panel içindeki yetkisizi deny()'a yollar."""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not in_panel(request.user):
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            if not test(request.user):
                return deny(request)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def access_required(*keys):
    """Verilen tiklerin HEPSİNİ ister (ör. gider silme: "expenses", "delete")."""
    unknown = [key for key in keys if key not in ACCESS]
    if unknown:
        # Yazım hatası sessizce "herkese kapalı" sayfaya dönüşmesin: import
        # anında patlasın.
        raise KeyError(f"Tanımsız yetki anahtarı: {', '.join(unknown)}")
    return _gate(lambda user: all(has_access(user, key) for key in keys))


panel_required = _gate(lambda user: True)
patron_required = _gate(is_patron)
money_required = access_required("money")


class MoneyAwareModelForm(StyledModelForm):
    """Para alanlarını yetkisiz kullanıcı için formdan tamamen çıkarır.

    Yalnızca gizlemek yetmez: alan formda kalırsa Personel hem maliyeti
    <input> içinde görür hem de istediği değeri POST edebilir. Alanı pop
    etmek yazma yolunu da kapatır, çünkü ModelForm._post_clean var olmayan
    bir alanı yok sayar.

    PRICE_FIELDS ise satış fiyatıdır: herkes görür, ama "Kasada fiyat" tiki
    olmayan kullanıcı mevcut kaydın fiyatını değiştiremez — yoksa kasadaki
    fiyat kilidi kartı düzenleyip satarak aşılırdı. Yeni kayıtta açık kalır
    (yeni gelen mala fiyat girmek gerekir). disabled=True, POST'taki değeri
    yok sayıp instance'ın değerini kullanır.
    """

    MONEY_FIELDS: list[str] = []
    PRICE_FIELDS: list[str] = []

    def __init__(self, *args, user=None, back_url="", **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        #: Formu gösteren view'ın tam adresi. Alt formlara ("yeni model ekle")
        #: `?next=` olarak verilir; boşsa kısayol formun kendi ekleme adresine
        #: döner. Bkz. apps.dashboard.utils.define_link.
        self.back_url = back_url
        if not can_see_money(user):
            for name in self.MONEY_FIELDS:
                self.fields.pop(name, None)
        if self.instance.pk and not has_access(user, "price"):
            for name in self.PRICE_FIELDS:
                if name in self.fields:
                    self.fields[name].disabled = True
                    self.fields[name].help_text = "Fiyat değiştirme yetkiniz yok."
