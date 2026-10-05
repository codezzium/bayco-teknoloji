"""Panel bildirimleri ve ekip listeleri.

Bildirim yalnızca panel içidir (topbar'daki zil → staff:notifications).
"""

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.stock.permissions import GROUP_PATRON, PANEL_GROUPS

from .models import Notification


def panel_members():
    """Panele girebilen herkes, pasifler dahil (Personel sayfası listesi).

    Kural apps.stock.permissions.in_panel ile aynıdır: superuser, is_staff ya
    da Patron/Personel grubu üyeliği.
    """
    User = get_user_model()
    return (User.objects
            .filter(Q(is_superuser=True) | Q(is_staff=True)
                    | Q(groups__name__in=PANEL_GROUPS))
            .distinct())


def panel_users():
    """Satıcı seçilebilecek ekip: panele girebilen AKTİF kullanıcılar."""
    return panel_members().filter(is_active=True).order_by("first_name", "username")


def active_patrons():
    User = get_user_model()
    return (User.objects
            .filter(is_active=True)
            .filter(Q(is_superuser=True) | Q(groups__name=GROUP_PATRON))
            .distinct())


def display_name(user) -> str:
    if user is None:
        return "Kayıtsız"
    return user.get_full_name() or user.get_username()


def notify(users, message, url="", exclude=None):
    """`users` (kullanıcı ya da None içeren yinelenebilir) kişilerine bildirim.

    None'lar ve `exclude` (işlemi yapan kişi kendine bildirim almaz) atlanır;
    aynı kişi iki kez yazılmaz.
    """
    seen = set()
    rows = []
    for user in users:
        if user is None or user.pk in seen or (exclude is not None and user.pk == exclude.pk):
            continue
        seen.add(user.pk)
        rows.append(Notification(user=user, message=str(message)[:240], url=url[:300]))
    Notification.objects.bulk_create(rows)
    return rows
