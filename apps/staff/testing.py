"""Testler için: kullanıcıya Personel sayfasındaki tikleri verir."""

from django.contrib.auth.models import Permission

from apps.stock.permissions import ACCESS


def grant(user, *keys):
    for key in keys:
        app_label, codename = ACCESS[key].perm.split(".", 1)
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label=app_label, codename=codename))
    # has_perm/in_panel sonuçları kullanıcı nesnesinde önbelleklenir.
    for attr in ("_perm_cache", "_user_perm_cache", "_in_panel", "_is_patron"):
        user.__dict__.pop(attr, None)
    return user
