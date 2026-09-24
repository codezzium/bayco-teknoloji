from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.db.models import Q

from apps.dashboard.forms import StyledModelForm, _style
from apps.stock.permissions import (
    ACCESS,
    GROUP_PATRON,
    GROUP_PERSONEL,
    PANEL_GROUPS,
    is_patron,
)

from .access import SECTIONS

User = get_user_model()

ROLE_PERSONEL = "personel"
ROLE_PATRON = "patron"
ROLE_CHOICES = [(ROLE_PERSONEL, "Personel"), (ROLE_PATRON, "Patron")]


def access_permissions() -> dict:
    """ACCESS anahtarı → Permission. Eksik izin sessizce atlanmaz: tik
    kaydedilmiş gibi görünüp hiçbir şey açmaması en kötü sonuç olurdu."""
    query = Q()
    for item in ACCESS.values():
        app_label, codename = item.perm.split(".", 1)
        query |= Q(content_type__app_label=app_label, codename=codename)
    by_label = {
        f"{perm.content_type.app_label}.{perm.codename}": perm
        for perm in Permission.objects.filter(query).select_related("content_type")
    }
    missing = [item.perm for item in ACCESS.values() if item.perm not in by_label]
    if missing:
        raise ImproperlyConfigured(
            "Panel izinleri veritabanında yok (önce `manage.py migrate`): "
            + ", ".join(missing))
    return {key: by_label[item.perm] for key, item in ACCESS.items()}


def granted_keys(user) -> set:
    """Kullanıcıya DOĞRUDAN verilmiş tikler (Patron'un örtük erişimi hariç)."""
    if user.pk is None:
        return set()
    labels = {f"{app}.{code}" for app, code in
              user.user_permissions.values_list("content_type__app_label", "codename")}
    return {key for key, item in ACCESS.items() if item.perm in labels}


def other_active_patrons(user) -> bool:
    """`user` dışında en az bir aktif Patron var mı?"""
    return (User.objects.filter(is_active=True)
            .filter(Q(is_superuser=True) | Q(groups__name=GROUP_PATRON))
            .exclude(pk=user.pk).exists())


class StaffForm(StyledModelForm):
    role = forms.ChoiceField(label="Rol", choices=ROLE_CHOICES, initial=ROLE_PERSONEL,
                             widget=forms.RadioSelect)
    password1 = forms.CharField(label="Şifre", strip=False, required=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Şifre (tekrar)", strip=False, required=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "is_active"]
        labels = {"is_active": "Hesap aktif"}
        help_texts = {
            "username": "Girişte kullanılır. Harf, rakam ve @ . + - _ olabilir.",
            "is_active": "Kapatılan hesap hemen oturumdan düşer; geçmiş kayıtları silinmez.",
        }

    def __init__(self, *args, acting_user, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        user = self.instance
        self.is_edit = user.pk is not None
        self.is_self = self.is_edit and user.pk == acting_user.pk
        self.before_role = (
            (ROLE_PATRON if is_patron(user) else ROLE_PERSONEL) if self.is_edit else None)

        granted = granted_keys(user)
        for key, item in ACCESS.items():
            self.fields[f"perm_{key}"] = forms.BooleanField(
                label=item.label, required=False, help_text=item.help,
                initial=key in granted)
        for name, field in self.fields.items():
            if name.startswith("perm_"):
                # shrink-0: açıklaması iki satıra taşan tikte kutu ezilmesin.
                field.widget.attrs["class"] = "toggle-check shrink-0 mt-0.5"
        self.fields["role"].widget.attrs["class"] = "toggle-check"

        if self.is_edit:
            self.initial["role"] = self.before_role
            self.fields["password1"].label = "Yeni şifre"
            self.fields["password1"].help_text = "Değiştirmeyecekseniz boş bırakın."
        else:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
            self.fields["password1"].help_text = password_validation.password_validators_help_text_html()

        # Superuser her zaman Patron'dur; kendi rolünü/aktifliğini değiştirmek
        # kendini panelden kilitlemenin en kısa yoludur.
        if user.is_superuser or self.is_self:
            self.fields["role"].disabled = True
            self.initial["role"] = ROLE_PATRON if user.is_superuser else self.before_role
        if self.is_self:
            self.fields["is_active"].disabled = True
            self.fields["is_active"].help_text = "Kendi hesabınızı kapatamazsınız."

    def sections(self):
        """Tikleri şablonda bölüm bölüm çizmek için: [(başlık, [alan, …]), …]."""
        return [(section, [self[f"perm_{key}"] for key, item in ACCESS.items()
                           if item.section == section])
                for section in SECTIONS]

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if (p1 or p2) and p1 != p2:
            self.add_error("password2", "Şifreler aynı değil.")

        if self.before_role == ROLE_PATRON:
            demoted = data.get("role") != ROLE_PATRON or not data.get("is_active", True)
            if demoted and not other_active_patrons(self.instance):
                raise ValidationError(
                    "Bu hesap son aktif Patron. Önce başka bir hesabı Patron yapın.")
        return data

    def _post_clean(self):
        # Şifre, kullanıcı adı/ad bilgisi instance'a işlendikten SONRA
        # doğrulanır (UserAttributeSimilarityValidator bunları kullanır).
        super()._post_clean()
        password = self.cleaned_data.get("password1")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except ValidationError as error:
                self.add_error("password1", error)

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        before_keys = granted_keys(user)

        if not user.is_superuser:
            # is_staff = /yonetim/ anahtarı; personel oradan maliyet görürdü.
            user.is_staff = False
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        user.save()

        role = self.cleaned_data.get("role") or ROLE_PERSONEL
        if not user.is_superuser:
            patron_group, _ = Group.objects.get_or_create(name=GROUP_PATRON)
            personel_group, _ = Group.objects.get_or_create(name=GROUP_PERSONEL)
            user.groups.remove(*Group.objects.filter(name__in=PANEL_GROUPS))
            user.groups.add(patron_group if role == ROLE_PATRON else personel_group)

        # Yalnızca ACCESS izinlerine dokunulur; kullanıcının başka izinleri kalır.
        perms = access_permissions()
        wanted = {key for key in ACCESS if self.cleaned_data.get(f"perm_{key}")}
        user.user_permissions.remove(*perms.values())
        user.user_permissions.add(*(perms[key] for key in wanted))

        self.changes = self._describe_changes(self.before_role, role, before_keys, wanted,
                                              password_changed=bool(password))
        return user

    def _describe_changes(self, before_role, role, before, after, password_changed):
        changes = {}
        if before_role and before_role != role and not self.instance.is_superuser:
            changes["Rol"] = f"{dict(ROLE_CHOICES)[before_role]} → {dict(ROLE_CHOICES)[role]}"
        added = [ACCESS[key].label for key in ACCESS if key in after - before]
        removed = [ACCESS[key].label for key in ACCESS if key in before - after]
        if added:
            changes["Verilen yetkiler"] = ", ".join(added)
        if removed:
            changes["Alınan yetkiler"] = ", ".join(removed)
        if "is_active" in self.changed_data:
            changes["Hesap"] = "Aktif" if self.instance.is_active else "Pasif"
        if password_changed:
            changes["Şifre"] = "değiştirildi"
        return changes


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)
