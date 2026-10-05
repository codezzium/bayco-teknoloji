"""Şablonlara `access` nesnesi: {% if access.expenses %} … {% endif %}
ve `notices.unread` (topbar'daki zilin rozeti).

Tembeldir: bir anahtar şablonda okunana kadar sorgu atılmaz. Vitrin
sitesinde (anonim ziyaretçi) hiçbir anahtar okunmaz; okunsa da False döner.
"""

from apps.stock.permissions import ACCESS, has_access, is_patron


class PanelAccess:
    def __init__(self, user):
        self._user = user
        self._cache = {}

    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        if key not in self._cache:
            if key == "patron":
                self._cache[key] = is_patron(self._user)
            elif key in ACCESS:
                self._cache[key] = has_access(self._user, key)
            else:
                raise AttributeError(key)
        return self._cache[key]


def access(request):
    return {"access": PanelAccess(getattr(request, "user", None))}


class PanelNotices:
    """Zil rozeti için okunmamış bildirim sayısı; okunana kadar sorgu yok."""

    def __init__(self, user):
        self._user = user
        self._unread = None

    @property
    def unread(self):
        if self._unread is None:
            from .models import Notification

            user = self._user
            self._unread = (Notification.objects.filter(user=user, read_at__isnull=True)
                            .count() if user is not None and user.is_authenticated else 0)
        return self._unread


def notifications(request):
    return {"notices": PanelNotices(getattr(request, "user", None))}
