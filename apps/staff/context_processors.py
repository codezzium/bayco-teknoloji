"""Şablonlara `access` nesnesi: {% if access.expenses %} … {% endif %}.

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
