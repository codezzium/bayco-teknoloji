from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Brand, Product
from apps.leads.models import ContactMessage, QuoteRequest, ServiceRequest
from apps.sitecore.models import FAQ, Slider, Testimonial

# Create your tests here.

LONG = "Ş" * 1000


class WebsiteTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(name="Apple")
        cls.product = Product.objects.create(
            name="iPhone 13 128GB", brand=cls.brand, price=25000, storage="128GB",
            condition=Product.Condition.IKINCI_EL, is_featured=True)
        cls.hidden = Product.objects.create(name="Eski İlan", brand=cls.brand,
                                            is_active=False)
        Slider.objects.create(title="Kampanya")
        Testimonial.objects.create(name="Ayşe", comment="Çok memnun kaldım")
        FAQ.objects.create(question="Garanti var mı?", answer="Var")


class PublicPageTests(WebsiteTestCase):
    def test_public_pages_render(self):
        for url in (
            reverse("website:home"),
            reverse("website:products"),
            reverse("website:products") + "?durum=ikinci_el&marka=apple&q=iphone",
            reverse("website:product_detail", kwargs={"slug": self.product.slug}),
            reverse("website:quote"),
            reverse("website:quote") + f"?urun={self.product.pk}&mod=al",
            reverse("website:service"),
            reverse("website:contact"),
            reverse("robots"),
            reverse("sitemap"),
            reverse("service_worker"),
            reverse("dashboard:manifest"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_product_filters_only_show_active_matches(self):
        body = self.client.get(reverse("website:products"), {"q": "iphone"}).content.decode()
        self.assertIn(self.product.name, body)
        self.assertNotIn(self.hidden.name, body)

    def test_inactive_product_is_not_found(self):
        response = self.client.get(reverse("website:product_detail",
                                           kwargs={"slug": self.hidden.slug}))
        self.assertEqual(response.status_code, 404)

    def test_sitemap_lists_only_active_products(self):
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn(self.product.get_absolute_url(), body)
        self.assertNotIn(self.hidden.get_absolute_url(), body)

    def test_robots_points_to_the_sitemap(self):
        self.assertContains(self.client.get(reverse("robots")), "/sitemap.xml")

    def test_junk_query_parameters_do_not_break_pages(self):
        for url in (
            reverse("website:quote") + "?urun=abc",
            reverse("website:quote") + "?urun=11%27",
            reverse("website:quote") + "?urun=%C2%B2",
            reverse("website:quote") + "?urun=99999999999999999999999",
            reverse("website:products") + "?q=%00",
            reverse("website:products") + "?marka=%00",
            reverse("website:products") + "?durum=%00",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_quote_mode_cannot_break_the_script(self):
        body = self.client.get(reverse("website:quote"), {"mod": "\\"}).content.decode()
        self.assertNotIn("'\\'", body)


class LeadSubmissionTests(WebsiteTestCase):
    def test_quote_request_is_saved_and_links_to_whatsapp(self):
        response = self.client.post(reverse("website:quote_submit"), {
            "kind": "al", "name": "Ayşe Kaya", "phone": "0532 111 22 33",
            "brand": "Apple", "model": "iPhone 13", "year": "2021", "storage": "128GB",
            "condition": "Temiz", "note": "Kutusu var", "product_id": self.product.pk,
        })
        self.assertContains(response, "wa.me/")
        lead = QuoteRequest.objects.get()
        self.assertEqual((lead.kind, lead.product), ("al", self.product))

    def test_long_quote_request_is_saved(self):
        response = self.client.post(reverse("website:quote_submit"), {
            "kind": "sat", "name": LONG, "phone": LONG, "brand": LONG, "model": LONG,
            "year": "2021 yılında aldım, faturası var", "storage": LONG,
            "condition": LONG, "note": LONG,
        })
        self.assertContains(response, "wa.me/")
        lead = QuoteRequest.objects.get()
        self.assertEqual(lead.year, "2021 yılın")
        self.assertEqual(lead.note, LONG)

    def test_long_service_request_is_saved(self):
        response = self.client.post(reverse("website:service_submit"), {
            "name": "Mehmet", "phone": "0533 000 00 00", "device": "iPhone 12",
            "issue": LONG, "note": LONG,
        })
        self.assertContains(response, "wa.me/")
        self.assertEqual(len(ServiceRequest.objects.get().issue), 200)

    def test_long_contact_message_is_saved(self):
        response = self.client.post(reverse("website:contact_submit"), {
            "name": LONG, "phone": LONG, "email": "a" * 300 + "@ornek.com",
            "message": LONG,
        })
        self.assertContains(response, "wa.me/")
        self.assertEqual(ContactMessage.objects.get().message, LONG)

    def test_nul_characters_are_removed(self):
        self.client.post(reverse("website:contact_submit"), {
            "name": "Ali\x00", "phone": "", "email": "", "message": "Merhaba\x00",
        })
        message = ContactMessage.objects.get()
        self.assertEqual((message.name, message.message), ("Ali", "Merhaba"))

    def test_junk_product_id_is_ignored(self):
        for pid in ("abc", "1'", "²", "\x00"):
            with self.subTest(product_id=pid):
                response = self.client.post(reverse("website:quote_submit"),
                                            {"name": "Ali", "phone": "0532",
                                             "product_id": pid})
                self.assertEqual(response.status_code, 200)
        self.assertEqual(QuoteRequest.objects.filter(product__isnull=True).count(), 4)

    def test_submit_endpoints_redirect_on_get(self):
        for submit, page in (("website:quote_submit", "website:quote"),
                             ("website:service_submit", "website:service"),
                             ("website:contact_submit", "website:contact")):
            with self.subTest(submit=submit):
                self.assertRedirects(self.client.get(reverse(submit)), reverse(page))
