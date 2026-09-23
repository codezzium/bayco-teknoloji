from io import StringIO

from django import forms
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db.models.fields.files import FieldFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.catalog.models import Brand, Product
from apps.leads.models import ContactMessage, QuoteRequest, ServiceRequest
from apps.sitecore.models import FAQ, SiteSettings, Slider, Testimonial
from apps.stock.models import Accessory, DeviceModel
from apps.stock.permissions import GROUP_PATRON, GROUP_PERSONEL

from .views import CRUD

# Create your tests here.

PASSWORD = "Gizli-sifre-2026"


def form_data(form):
    data = {}
    for name, field in form.fields.items():
        value = form[name].value()
        if isinstance(field.widget, forms.CheckboxInput):
            if value:
                data[name] = "on"
        elif value is not None and not isinstance(value, FieldFile):
            data[name] = value
    return data


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PanelTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_roles", stdout=StringIO(), stderr=StringIO())
        cls.patron = User.objects.create_user("patron", password=PASSWORD,
                                              is_staff=True, is_superuser=True)
        cls.personel = User.objects.create_user("personel", password=PASSWORD)
        cls.personel.groups.add(Group.objects.get(name=GROUP_PERSONEL))
        cls.outsider = User.objects.create_user("musteri", password=PASSWORD)
        cls.brand = Brand.objects.create(name="Apple")
        cls.product = Product.objects.create(name="iPhone 13", brand=cls.brand,
                                             price=25000)
        cls.slider = Slider.objects.create(title="Kampanya")
        cls.testimonial = Testimonial.objects.create(name="Ayşe", comment="Harika")
        cls.faq = FAQ.objects.create(question="Garanti var mı?", answer="Var")
        cls.quote = QuoteRequest.objects.create(name="Ali", phone="0532 000 00 00")
        cls.service = ServiceRequest.objects.create(name="Veli", phone="0533 000 00 00",
                                                    device="iPhone 11", issue="Ekran")
        cls.message = ContactMessage.objects.create(name="Can", message="Merhaba")

    def records(self):
        return {"duyurular": self.slider, "urunler": self.product,
                "yorumlar": self.testimonial, "sss": self.faq, "markalar": self.brand}


class LoginTests(PanelTestCase):
    def login(self, username, password=PASSWORD, next_url=""):
        url = reverse("dashboard:login")
        if next_url:
            url += f"?next={next_url}"
        return self.client.post(url, {"username": username, "password": password})

    def test_login_page_renders(self):
        self.assertEqual(self.client.get(reverse("dashboard:login")).status_code, 200)

    def test_patron_and_personel_can_log_in(self):
        for username in ("patron", "personel"):
            with self.subTest(username=username):
                self.client.logout()
                self.assertRedirects(self.login(username), reverse("dashboard:home"))

    def test_user_outside_the_panel_groups_is_refused(self):
        response = self.login("musteri")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_password_is_refused(self):
        response = self.login("patron", password="yanlis")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_nul_in_credentials_is_refused_without_error(self):
        response = self.login("pat\x00ron", password="x\x00y")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_next_cannot_leave_the_site(self):
        for target in ("//evil.example/", "https://evil.example/"):
            with self.subTest(next=target):
                self.client.logout()
                self.assertRedirects(self.login("patron", next_url=target),
                                     reverse("dashboard:home"))

    def test_next_inside_the_panel_is_followed(self):
        target = reverse("stock:pos")
        self.assertRedirects(self.login("patron", next_url=target), target)

    def test_logout_returns_to_login(self):
        self.client.force_login(self.patron)
        self.assertRedirects(self.client.get(reverse("dashboard:logout")),
                             reverse("dashboard:login"))
        self.assertNotIn("_auth_user_id", self.client.session)


class PanelPageTests(PanelTestCase):
    def panel_urls(self):
        urls = [reverse("dashboard:home"), reverse("dashboard:leads"),
                reverse("dashboard:leads") + "?tab=service",
                reverse("dashboard:settings")]
        for key, record in self.records().items():
            urls += [reverse("dashboard:crud_list", kwargs={"key": key}),
                     reverse("dashboard:crud_create", kwargs={"key": key}),
                     reverse("dashboard:crud_edit", kwargs={"key": key, "pk": record.pk})]
        return urls

    def test_every_section_is_registered(self):
        self.assertEqual(set(self.records()), set(CRUD))

    def test_all_panel_pages_render(self):
        self.client.force_login(self.patron)
        for url in self.panel_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_personel_home_hides_money(self):
        self.client.force_login(self.personel)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_money"])

    def test_anonymous_and_outsiders_are_sent_to_login(self):
        for user in (None, self.outsider):
            if user:
                self.client.force_login(user)
            for url in self.panel_urls():
                with self.subTest(user=user, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response["Location"].startswith(
                        reverse("dashboard:login")))

    def test_unknown_section_is_not_found(self):
        self.client.force_login(self.patron)
        response = self.client.get(reverse("dashboard:crud_list", kwargs={"key": "yok"}))
        self.assertEqual(response.status_code, 404)


class CrudTests(PanelTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    def test_every_section_can_be_created(self):
        payloads = {
            "duyurular": {"title": "Yeni", "subtitle": "", "badge": "", "link_url": "",
                          "order": "0", "is_active": "on"},
            "urunler": {"name": "Galaxy S24", "brand": self.brand.pk,
                        "condition": "sifir", "price": "40000", "old_price": "",
                        "storage": "256GB", "color": "", "year": "",
                        "condition_grade": "", "warranty": "", "short_desc": "",
                        "description": "", "is_active": "on", "order": "0"},
            "yorumlar": {"name": "Mehmet", "role": "", "rating": "5",
                         "comment": "Güzel", "order": "0", "is_active": "on"},
            "sss": {"question": "Taksit var mı?", "answer": "Var", "order": "0",
                    "is_active": "on"},
            "markalar": {"name": "Samsung", "order": "0"},
        }
        for key, data in payloads.items():
            with self.subTest(key=key):
                model = CRUD[key]["model"]
                before = model.objects.count()
                response = self.client.post(
                    reverse("dashboard:crud_create", kwargs={"key": key}), data)
                self.assertRedirects(response, reverse("dashboard:crud_list",
                                                       kwargs={"key": key}))
                self.assertEqual(model.objects.count(), before + 1)

    def test_every_section_can_be_saved_unchanged(self):
        for key, record in self.records().items():
            with self.subTest(key=key):
                url = reverse("dashboard:crud_edit", kwargs={"key": key, "pk": record.pk})
                response = self.client.post(url, form_data(self.client.get(url).context["form"]))
                self.assertRedirects(response, reverse("dashboard:crud_list",
                                                       kwargs={"key": key}))

    def test_toggle_flips_only_allowed_fields(self):
        url = reverse("dashboard:crud_toggle", kwargs={"key": "urunler",
                                                       "pk": self.product.pk,
                                                       "field": "is_featured"})
        self.assertEqual(self.client.post(url).status_code, 200)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_featured)
        url = reverse("dashboard:crud_toggle", kwargs={"key": "urunler",
                                                       "pk": self.product.pk,
                                                       "field": "price"})
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_unused_records_can_be_deleted(self):
        for key, record in self.records().items():
            with self.subTest(key=key):
                response = self.client.post(
                    reverse("dashboard:crud_delete", kwargs={"key": key, "pk": record.pk}),
                    HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
                self.assertFalse(type(record).objects.filter(pk=record.pk).exists())

    def test_brand_used_by_stock_is_not_deleted(self):
        DeviceModel.objects.create(brand=self.brand, name="iPhone 13")
        Accessory.objects.create(name="Kılıf", brand=self.brand)
        url = reverse("dashboard:crud_delete", kwargs={"key": "markalar",
                                                       "pk": self.brand.pk})
        response = self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")
        response = self.client.post(url)
        self.assertRedirects(response, reverse("dashboard:crud_list",
                                               kwargs={"key": "markalar"}))
        self.assertTrue(Brand.objects.filter(pk=self.brand.pk).exists())

    def test_brand_names_differing_only_in_case_can_both_be_added(self):
        for name in ("Xiaomi", "XIAOMI"):
            with self.subTest(name=name):
                response = self.client.post(
                    reverse("dashboard:crud_create", kwargs={"key": "markalar"}),
                    {"name": name, "order": "0"})
                self.assertEqual(response.status_code, 302)
        slugs = set(Brand.objects.filter(name__iexact="xiaomi").values_list("slug", flat=True))
        self.assertEqual(len(slugs), 2)

    def test_new_brand_returns_to_the_stock_form_selected(self):
        back = reverse("stock:accessory_create")
        response = self.client.post(
            reverse("dashboard:crud_create", kwargs={"key": "markalar"}) + f"?next={back}",
            {"name": "Anker", "order": "0"})
        brand = Brand.objects.get(name="Anker")
        self.assertRedirects(response, f"{back}?brand={brand.pk}")

    def test_next_outside_the_panel_is_ignored(self):
        response = self.client.post(
            reverse("dashboard:crud_create", kwargs={"key": "markalar"})
            + "?next=https://evil.example/",
            {"name": "Anker", "order": "0"})
        self.assertRedirects(response, reverse("dashboard:crud_list",
                                               kwargs={"key": "markalar"}))


class SettingsAndLeadTests(PanelTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    def test_settings_can_be_saved_unchanged(self):
        url = reverse("dashboard:settings")
        response = self.client.post(url, form_data(self.client.get(url).context["form"]))
        self.assertRedirects(response, url)

    def test_settings_change_shows_on_the_site(self):
        url = reverse("dashboard:settings")
        data = form_data(self.client.get(url).context["form"])
        data["brand_name"] = "Bayço Deneme Mağazası"
        self.client.post(url, data)
        self.assertEqual(SiteSettings.load().brand_name, "Bayço Deneme Mağazası")
        self.assertContains(self.client.get(reverse("website:home")),
                            "Bayço Deneme Mağazası")

    def test_leads_can_be_marked_and_deleted(self):
        for tip, record in (("quote", self.quote), ("service", self.service),
                            ("contact", self.message)):
            with self.subTest(tip=tip):
                toggle = reverse("dashboard:lead_toggle", kwargs={"tip": tip, "pk": record.pk})
                self.assertEqual(self.client.post(toggle).status_code, 200)
                record.refresh_from_db()
                self.assertTrue(record.is_handled)
                delete = reverse("dashboard:lead_delete", kwargs={"tip": tip, "pk": record.pk})
                self.assertEqual(self.client.post(delete).status_code, 200)
                self.assertFalse(type(record).objects.filter(pk=record.pk).exists())

    def test_unknown_lead_type_is_not_found(self):
        url = reverse("dashboard:lead_toggle", kwargs={"tip": "yok", "pk": 1})
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_manifest_and_service_worker_are_public(self):
        self.client.logout()
        manifest = self.client.get(reverse("dashboard:manifest"))
        self.assertEqual(manifest["Content-Type"], "application/manifest+json")
        self.assertEqual(manifest.json()["start_url"], reverse("dashboard:home"))
        worker = self.client.get(reverse("service_worker"))
        self.assertEqual(worker["Cache-Control"], "no-cache")


class PersonelLimitTests(PanelTestCase):
    def setUp(self):
        self.client.force_login(self.personel)

    def test_personel_cannot_delete_site_records(self):
        for key, record in self.records().items():
            with self.subTest(key=key):
                response = self.client.post(
                    reverse("dashboard:crud_delete", kwargs={"key": key, "pk": record.pk}),
                    HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 302)
                self.assertTrue(type(record).objects.filter(pk=record.pk).exists())

    def test_personel_cannot_delete_leads(self):
        for tip, record in (("quote", self.quote), ("service", self.service),
                            ("contact", self.message)):
            with self.subTest(tip=tip):
                response = self.client.post(
                    reverse("dashboard:lead_delete", kwargs={"tip": tip, "pk": record.pk}))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(type(record).objects.filter(pk=record.pk).exists())

    def test_personel_cannot_open_or_change_site_settings(self):
        url = reverse("dashboard:settings")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.post(url, {"brand_name": "Başka", "whatsapp_number": "900000000000"})
        self.assertNotEqual(SiteSettings.load().whatsapp_number, "900000000000")

    def test_personel_does_not_see_delete_buttons_or_settings(self):
        body = self.client.get(reverse("dashboard:crud_list",
                                       kwargs={"key": "urunler"})).content.decode()
        self.assertNotIn(reverse("dashboard:crud_delete",
                                 kwargs={"key": "urunler", "pk": self.product.pk}), body)
        self.assertNotIn(reverse("dashboard:settings"), body)
        body = self.client.get(reverse("dashboard:leads")).content.decode()
        self.assertNotIn(reverse("dashboard:lead_delete",
                                 kwargs={"tip": "quote", "pk": self.quote.pk}), body)

    def test_personel_can_still_add_edit_and_handle_leads(self):
        response = self.client.post(reverse("dashboard:crud_create", kwargs={"key": "markalar"}),
                                    {"name": "Anker", "order": "0"})
        self.assertEqual(response.status_code, 302)
        toggle = reverse("dashboard:crud_toggle", kwargs={"key": "urunler",
                                                          "pk": self.product.pk,
                                                          "field": "is_active"})
        self.assertEqual(self.client.post(toggle).status_code, 200)
        lead = reverse("dashboard:lead_toggle", kwargs={"tip": "quote", "pk": self.quote.pk})
        self.assertEqual(self.client.post(lead).status_code, 200)


class PatronGroupTests(PanelTestCase):
    def test_patron_group_member_has_full_access(self):
        owner = User.objects.create_user("sahip", password=PASSWORD)
        owner.groups.add(Group.objects.get(name=GROUP_PATRON))
        self.client.force_login(owner)
        self.assertEqual(self.client.get(reverse("dashboard:settings")).status_code, 200)
        body = self.client.get(reverse("dashboard:crud_list",
                                       kwargs={"key": "urunler"})).content.decode()
        delete = reverse("dashboard:crud_delete", kwargs={"key": "urunler", "pk": self.product.pk})
        self.assertIn(delete, body)
        self.assertEqual(self.client.post(delete, HTTP_HX_REQUEST="true").status_code, 200)
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())
