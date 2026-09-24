import importlib
from datetime import timedelta
from io import StringIO

from django.apps import apps as django_apps
from django.contrib.auth.models import Group, Permission, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.stock.models import Device, DeviceModel, Expense
from apps.stock.permissions import ACCESS, GROUP_PATRON, GROUP_PERSONEL, has_access

from .actions import LABELS, READ_ONLY
from .forms import granted_keys
from .models import ActivityLog
from .testing import grant

PASSWORD = "Gizli-sifre-2026"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class StaffTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", stdout=StringIO(), stderr=StringIO())
        cls.patron = User.objects.create_user("patron", password=PASSWORD,
                                              is_staff=True, is_superuser=True)
        cls.personel = User.objects.create_user("personel", password=PASSWORD)
        cls.personel.groups.add(Group.objects.get(name=GROUP_PERSONEL))

    def form_data(self, **overrides):
        data = {"username": "ali", "first_name": "Ali", "last_name": "Yılmaz",
                "is_active": "on", "role": "personel",
                "password1": "Kasa-sifresi-77", "password2": "Kasa-sifresi-77"}
        data.update(overrides)
        return {key: value for key, value in data.items() if value is not None}


class AccessRegistryTests(StaffTestCase):
    def test_every_tick_exists_as_a_permission(self):
        for key, item in ACCESS.items():
            app_label, codename = item.perm.split(".", 1)
            with self.subTest(key=key):
                self.assertTrue(Permission.objects.filter(
                    content_type__app_label=app_label, codename=codename).exists())

    def test_patron_group_member_has_every_tick_without_permissions(self):
        owner = User.objects.create_user("sahip")
        owner.groups.add(Group.objects.get(name=GROUP_PATRON))
        Group.objects.get(name=GROUP_PATRON).permissions.clear()
        for key in ACCESS:
            with self.subTest(key=key):
                self.assertTrue(has_access(owner, key))

    def test_plain_personel_has_no_ticks(self):
        for key in ACCESS:
            with self.subTest(key=key):
                self.assertFalse(has_access(self.personel, key))

    def test_inactive_user_has_nothing(self):
        user = grant(User.objects.create_user("eski", is_active=False), "reports")
        user.groups.add(Group.objects.get(name=GROUP_PERSONEL))
        self.assertFalse(has_access(user, "reports"))


class PanelPagesByTickTests(StaffTestCase):
    """Her sayfa tiki: tiksiz ret (htmx'te HX-Refresh), tikli 200."""

    PAGES = {
        "expenses": ("stock:expense_list", {}),
        "reports": ("stock:reports", {}),
        "content": ("dashboard:settings", {}),
        "leads": ("dashboard:leads", {}),
        "contacts": ("stock:contact_list", {}),
    }

    def test_each_page_tick(self):
        self.client.force_login(self.personel)
        for key, (name, kwargs) in self.PAGES.items():
            url = reverse(name, kwargs=kwargs)
            with self.subTest(key=key):
                self.assertRedirects(self.client.get(url), reverse("dashboard:home"),
                                     fetch_redirect_response=False)
                response = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 204)
                self.assertEqual(response["HX-Refresh"], "true")
                grant(self.personel, key)
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_denied_page_shows_a_message(self):
        self.client.force_login(self.personel)
        response = self.client.get(reverse("stock:reports"), follow=True)
        self.assertContains(response, "Bu işlem için yetkiniz yok.")


class StaffPageTests(StaffTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    def test_list_and_forms_render(self):
        for url in (reverse("staff:list"), reverse("staff:create"),
                    reverse("staff:edit", kwargs={"pk": self.personel.pk}),
                    reverse("staff:edit", kwargs={"pk": self.patron.pk}),
                    reverse("staff:logs"), reverse("staff:password")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_patron_creates_personel_with_ticks(self):
        response = self.client.post(reverse("staff:create"), self.form_data(
            perm_expenses="on", perm_revenue_today="on"))
        self.assertRedirects(response, reverse("staff:list"), fetch_redirect_response=False)
        user = User.objects.get(username="ali")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(list(user.groups.values_list("name", flat=True)), [GROUP_PERSONEL])
        self.assertEqual(granted_keys(user), {"expenses", "revenue_today"})
        self.assertTrue(user.check_password("Kasa-sifresi-77"))
        self.assertTrue(self.client.login(username="ali", password="Kasa-sifresi-77"))

    def test_weak_or_mismatched_password_is_refused(self):
        for p1, p2 in (("123", "123"), ("Kasa-sifresi-77", "Baska-sifre-88"), ("", "")):
            with self.subTest(p1=p1, p2=p2):
                response = self.client.post(reverse("staff:create"),
                                            self.form_data(password1=p1, password2=p2))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(User.objects.filter(username="ali").exists())

    def test_editing_replaces_only_panel_ticks(self):
        other = Permission.objects.get(codename="view_device")
        self.personel.user_permissions.add(other)
        grant(self.personel, "reports")
        self.client.post(reverse("staff:edit", kwargs={"pk": self.personel.pk}),
                         self.form_data(username="personel", password1="", password2="",
                                        perm_leads="on"))
        self.assertEqual(granted_keys(self.personel), {"leads"})
        self.assertTrue(self.personel.user_permissions.filter(pk=other.pk).exists())
        self.assertTrue(self.personel.check_password(PASSWORD))   # boş = değişmez

    def test_promote_to_patron_and_back(self):
        url = reverse("staff:edit", kwargs={"pk": self.personel.pk})
        self.client.post(url, self.form_data(username="personel", password1="",
                                             password2="", role="patron"))
        self.assertTrue(self.personel.groups.filter(name=GROUP_PATRON).exists())
        self.assertFalse(self.personel.groups.filter(name=GROUP_PERSONEL).exists())
        self.client.post(url, self.form_data(username="personel", password1="",
                                             password2="", role="personel"))
        self.assertFalse(self.personel.groups.filter(name=GROUP_PATRON).exists())

    def test_is_staff_is_always_cleared(self):
        self.personel.is_staff = True
        self.personel.save()
        self.client.post(reverse("staff:edit", kwargs={"pk": self.personel.pk}),
                         self.form_data(username="personel", password1="", password2=""))
        self.personel.refresh_from_db()
        self.assertFalse(self.personel.is_staff)

    def test_patron_cannot_demote_or_deactivate_self(self):
        self.client.post(reverse("staff:edit", kwargs={"pk": self.patron.pk}),
                         self.form_data(username="patron", password1="", password2="",
                                        role="personel", is_active=None))
        self.patron.refresh_from_db()
        self.assertTrue(self.patron.is_active)
        self.assertTrue(self.patron.is_superuser)

    def test_last_active_patron_cannot_be_demoted(self):
        owner = User.objects.create_user("sahip", password=PASSWORD)
        owner.groups.add(Group.objects.get(name=GROUP_PATRON))
        self.patron.is_active = False
        self.patron.save()
        second = User.objects.create_user("ortak", password=PASSWORD)
        second.groups.add(Group.objects.get(name=GROUP_PATRON))
        self.client.force_login(second)
        url = reverse("staff:edit", kwargs={"pk": owner.pk})
        # İki aktif Patron varken biri düşürülebilir…
        self.client.post(url, self.form_data(username="sahip", password1="",
                                             password2="", role="personel"))
        self.assertFalse(owner.groups.filter(name=GROUP_PATRON).exists())
        # …sonuncusu değil (kendi rolü kilitli; başka bir Patron olmadığını
        # doğrulamak için formu doğrudan kullanıyoruz).
        from .forms import StaffForm
        form = StaffForm(self.form_data(username="ortak", password1="", password2="",
                                        role="personel"),
                         instance=second, acting_user=self.patron)
        self.assertFalse(form.is_valid())

    def test_deactivated_user_is_logged_out_on_next_request(self):
        self.client.force_login(self.personel)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)
        self.personel.is_active = False
        self.personel.save()
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("dashboard:login")))

    def test_personel_cannot_manage_staff_or_see_logs(self):
        grant(self.personel, *ACCESS)   # tüm tikler bile Personel sayfasını açmaz
        self.client.force_login(self.personel)
        for url in (reverse("staff:list"), reverse("staff:create"),
                    reverse("staff:edit", kwargs={"pk": self.personel.pk}),
                    reverse("staff:logs")):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("dashboard:home"),
                                     fetch_redirect_response=False)
        self.client.post(reverse("staff:edit", kwargs={"pk": self.personel.pk}),
                         self.form_data(username="personel", role="patron"))
        self.assertFalse(self.personel.groups.filter(name=GROUP_PATRON).exists())


class PasswordChangeTests(StaffTestCase):
    def test_personel_changes_own_password_and_stays_logged_in(self):
        self.client.force_login(self.personel)
        response = self.client.post(reverse("staff:password"), {
            "old_password": PASSWORD,
            "new_password1": "Yeni-sifre-2026x", "new_password2": "Yeni-sifre-2026x"})
        self.assertRedirects(response, reverse("dashboard:home"))
        self.personel.refresh_from_db()
        self.assertTrue(self.personel.check_password("Yeni-sifre-2026x"))
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)
        log = ActivityLog.objects.get(view_name="staff:password")
        self.assertEqual(log.action, "Kendi şifresini değiştirdi")
        self.assertNotIn("Yeni-sifre", str(log.detail))
        self.assertNotIn(PASSWORD, str(log.detail))


class ActivityLogTests(StaffTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.catalog.models import Brand
        brand = Brand.objects.create(name="Apple")
        cls.model = DeviceModel.objects.create(brand=brand, name="iPhone 13")

    def test_post_is_logged_with_label_target_and_values(self):
        self.client.force_login(self.patron)
        self.client.post(reverse("stock:simple_create", kwargs={"key": "modeller"}),
                         {"brand": self.model.brand.pk, "name": "iPhone 15",
                          "kind": self.model.kind, "is_active": "on"})
        log = ActivityLog.objects.get(view_name="stock:simple_create")
        self.assertEqual(log.kind, ActivityLog.Kind.ISLEM)
        self.assertEqual(log.action, "Model ekledi")
        self.assertEqual(log.username, "patron")
        self.assertEqual(log.detail["name"], "iPhone 15")
        self.assertNotIn("csrfmiddlewaretoken", log.detail)
        self.assertTrue(log.target_url.startswith("/panel/"))

    def test_pos_actions_name_the_product_from_post_data(self):
        from apps.stock.models import Accessory
        accessory = Accessory.objects.create(name="Şarj Kablosu", price=150)
        self.client.force_login(self.patron)
        self.client.post(reverse("stock:cart_add"),
                         {"kind": "aksesuar", "id": accessory.pk, "qty": "1"},
                         HTTP_HX_REQUEST="true")
        log = ActivityLog.objects.get(view_name="stock:cart_add")
        self.assertEqual(log.action, "Sepete ürün ekledi")
        self.assertEqual(log.target, "Şarj Kablosu")

    def test_deleted_record_name_survives_in_the_log(self):
        self.client.force_login(self.patron)
        expense = Expense.objects.create(kind=Expense.Kind.choices[0][0], title="Kira Eylül",
                                         amount=5000, spent_on=timezone.localdate())
        self.client.post(reverse("stock:expense_delete", kwargs={"pk": expense.pk}))
        log = ActivityLog.objects.get(view_name="stock:expense_delete")
        self.assertEqual(log.action, "Gideri sildi")
        self.assertIn("Kira Eylül", log.target)

    def test_form_error_is_marked_as_not_saved(self):
        self.client.force_login(self.patron)
        self.client.post(reverse("stock:simple_create", kwargs={"key": "modeller"}), {})
        log = ActivityLog.objects.get(view_name="stock:simple_create")
        self.assertIn("kaydedilmedi", log.action)

    def test_staff_edit_logs_tick_changes_but_never_passwords(self):
        self.client.force_login(self.patron)
        grant(self.personel, "reports")
        self.client.post(reverse("staff:edit", kwargs={"pk": self.personel.pk}),
                         self.form_data(username="personel", perm_expenses="on",
                                        password1="Yepyeni-sifre-9", password2="Yepyeni-sifre-9"))
        log = ActivityLog.objects.get(view_name="staff:edit")
        self.assertEqual(log.target, "personel")
        self.assertEqual(log.detail["Verilen yetkiler"], "Giderler")
        self.assertEqual(log.detail["Alınan yetkiler"], "Raporlar")
        self.assertEqual(log.detail["Şifre"], "değiştirildi")
        self.assertNotIn("Yepyeni", str(log.detail))

    def test_login_logout_and_failed_login_are_logged(self):
        self.client.post(reverse("dashboard:login"),
                         {"username": "personel", "password": "yanlis"})
        self.client.post(reverse("dashboard:login"),
                         {"username": "personel", "password": PASSWORD})
        self.client.get(reverse("dashboard:logout"))
        kinds = list(ActivityLog.objects.order_by("at", "id").values_list("kind", "username"))
        self.assertEqual(kinds, [
            (ActivityLog.Kind.HATALI_GIRIS, "personel"),
            (ActivityLog.Kind.GIRIS, "personel"),
            (ActivityLog.Kind.CIKIS, "personel"),
        ])
        self.assertNotIn("yanlis", str(list(ActivityLog.objects.values())))

    def test_login_with_account_outside_the_panel_is_logged(self):
        User.objects.create_user("musteri", password=PASSWORD)
        self.client.post(reverse("dashboard:login"),
                         {"username": "musteri", "password": PASSWORD})
        log = ActivityLog.objects.get()
        self.assertEqual(log.kind, ActivityLog.Kind.YETKISIZ)
        self.assertEqual(log.username, "musteri")

    def test_denied_attempt_is_logged_once(self):
        self.client.force_login(self.personel)
        device = Device.objects.create(device_model=self.model, imei1="351234567890123")
        self.client.post(reverse("stock:device_delete", kwargs={"pk": device.pk}))
        self.client.get(reverse("stock:reports"))
        # force_login da bir "giriş" kaydı yazar; burada yalnızca denemeler.
        logs = list(ActivityLog.objects.exclude(kind=ActivityLog.Kind.GIRIS).order_by("id"))
        self.assertEqual([log.kind for log in logs], [ActivityLog.Kind.YETKISIZ] * 2)
        self.assertEqual(logs[0].action, "Cihazı sildi")
        self.assertIn(device.stock_code, logs[0].target)
        self.assertEqual(logs[1].action, "Raporlar")

    def test_reads_are_not_logged(self):
        self.client.force_login(self.patron)
        self.client.get(reverse("stock:device_list"))
        self.client.get(reverse("dashboard:home"))
        self.assertFalse(ActivityLog.objects.exclude(kind=ActivityLog.Kind.GIRIS).exists())

    def test_log_list_filters_and_csv(self):
        ActivityLog.objects.create(user=self.personel, username="personel",
                                   action="Satışı tamamladı", target="S-000001",
                                   detail={"paid_amount": "1.500"})
        ActivityLog.objects.create(user=self.patron, username="patron",
                                   action="Site ayarlarını değiştirdi")
        self.client.force_login(self.patron)
        url = reverse("staff:logs")
        body = self.client.get(url, {"kullanici": self.personel.pk}).content.decode()
        self.assertIn("Satışı tamamladı", body)
        self.assertIn("Tahsil edilen", body)       # alan adının Türkçesi
        self.assertNotIn("Site ayarlarını değiştirdi", body)

        response = self.client.get(url, {"kullanici": self.personel.pk, "format": "csv"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        content = b"".join(response.streaming_content).decode("utf-8")
        self.assertTrue(content.startswith("﻿"))
        lines = content.lstrip("﻿").strip().splitlines()
        self.assertEqual(lines[0].split(";")[:4], ["Zaman", "Kullanıcı", "Tür", "İşlem"])
        self.assertEqual(len(lines), 2)
        self.assertIn("Tahsil edilen: 1.500", lines[1])

    def test_old_logs_are_pruned_on_login(self):
        old = ActivityLog.objects.create(username="x", action="eski")
        ActivityLog.objects.filter(pk=old.pk).update(at=timezone.now() - timedelta(days=400))
        recent = ActivityLog.objects.create(username="x", action="yeni")
        self.client.post(reverse("dashboard:login"),
                         {"username": "patron", "password": PASSWORD})
        self.assertFalse(ActivityLog.objects.filter(pk=old.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(pk=recent.pk).exists())

    def test_prune_command(self):
        old = ActivityLog.objects.create(username="x", action="eski")
        ActivityLog.objects.filter(pk=old.pk).update(at=timezone.now() - timedelta(days=40))
        call_command("prune_activity_log", "--days", "30", stdout=StringIO())
        self.assertFalse(ActivityLog.objects.exists())


class ActionRegistryTests(TestCase):
    def test_every_panel_route_is_labelled_or_marked_read_only(self):
        """Yeni bir view eklenince buraya düşer: ya LABELS'a (POST işlemi) ya
        READ_ONLY'ye eklenmeli; aksi halde log ekranında ham view adı çıkar."""
        missing = []

        def walk(patterns, namespace):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    walk(pattern.url_patterns, pattern.namespace or namespace)
                elif isinstance(pattern, URLPattern) and namespace in (
                        "stock", "dashboard", "staff") and pattern.name:
                    name = f"{namespace}:{pattern.name}"
                    if name not in LABELS and name not in READ_ONLY:
                        missing.append(name)

        walk(get_resolver().url_patterns, None)
        self.assertEqual(missing, [])


class PreservePersonelAccessMigrationTests(TestCase):
    def test_existing_personel_keeps_todays_access(self):
        call_command("seed_roles", stdout=StringIO(), stderr=StringIO())
        personel = User.objects.create_user("eski_personel")
        personel.groups.add(Group.objects.get(name=GROUP_PERSONEL))
        migration = importlib.import_module(
            "apps.staff.migrations.0002_preserve_personel_access")
        migration.grant(django_apps, None)
        self.assertEqual(granted_keys(personel), {"leads", "contacts", "content", "price"})
