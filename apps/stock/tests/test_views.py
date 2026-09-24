"""Her ekranın render olduğunu ve yetki sınırlarının tuttuğunu doğrular.

Şablon hataları (NoReverseMatch, eksik filtre, yanlış değişken) yalnızca
sayfa gerçekten render edildiğinde ortaya çıkar; bu yüzden her URL çağrılır.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Brand
from apps.stock import services
from apps.stock.labels import LABEL_FORMATS
from apps.stock.models import (Accessory, Contact, Device, DeviceModel,
                               Expense, Sale)
from apps.stock.permissions import GROUP_PATRON, GROUP_PERSONEL

TL = Decimal


class ScreenTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_roles", verbosity=0)

        cls.patron = User.objects.create_user("patron", password="pw",
                                              is_staff=True, is_superuser=True)
        cls.personel = User.objects.create_user("personel", password="pw",
                                                is_staff=False)
        cls.personel.groups.add(*User.objects.none().model.groups.rel.model.objects
                                .filter(name=GROUP_PERSONEL))

        cls.brand = Brand.objects.create(name="Apple")
        cls.model = DeviceModel.objects.create(brand=cls.brand, name="iPhone 13")
        cls.contact = Contact.objects.create(full_name="Ahmet Yılmaz",
                                             phone="0532 111 22 33",
                                             is_supplier=True)
        cls.device = services.create_device(
            user=cls.patron, device_model=cls.model, imei1="351234567890123",
            purchase_price=TL("16000"), list_price=TL("18500"),
            storage="256GB", color="Grafit", warranty_months=12,
        )
        cls.accessory = Accessory.objects.create(
            name="Şarj Kablosu USB-C", barcode="8690000000017",
            cost=TL("80"), price=TL("150.90"))
        services.receive_accessory_stock(cls.accessory, 10, user=cls.patron,
                                         opening=True)
        Expense.objects.create(kind=Expense.Kind.KIRA, title="Dükkân kirası",
                               amount=TL("15000"))

        cart = {
            "customer_id": cls.contact.pk,
            "lines": [
                {"lid": "d", "kind": "cihaz", "id": cls.device.pk,
                 "name": cls.device.label, "qty": 1, "unit": "18500.00"},
                {"lid": "a", "kind": "aksesuar", "id": cls.accessory.pk,
                 "name": cls.accessory.name, "qty": 2, "unit": "150.90"},
            ],
        }
        cls.sale = services.create_sale_from_cart(
            cart, user=cls.patron, payments=[{"amount": TL("10000")}],
            due_date=timezone.localdate() - timedelta(days=1))

    def urls(self):
        return [
            reverse("stock:overview"),
            reverse("stock:scan"),
            reverse("stock:device_list"),
            reverse("stock:device_list") + "?q=iphone&durum=stokta&marka=apple",
            reverse("stock:device_create"),
            reverse("stock:device_detail", kwargs={"pk": self.device.pk}),
            reverse("stock:device_edit", kwargs={"pk": self.device.pk}),
            reverse("stock:accessory_list"),
            reverse("stock:accessory_list") + "?q=sarj&filtre=kritik",
            reverse("stock:accessory_create"),
            reverse("stock:accessory_detail", kwargs={"pk": self.accessory.pk}),
            reverse("stock:accessory_edit", kwargs={"pk": self.accessory.pk}),
            reverse("stock:simple_list", kwargs={"key": "modeller"}),
            reverse("stock:simple_create", kwargs={"key": "modeller"}),
            reverse("stock:simple_list", kwargs={"key": "kategoriler"}),
            reverse("stock:pos"),
            reverse("stock:product_search") + "?q=iphone",
            reverse("stock:contact_search") + "?q=ahmet",
            reverse("stock:sale_list"),
            reverse("stock:sale_list") + "?filtre=acik",
            reverse("stock:sale_list") + "?filtre=vadesi&q=BYC",
            reverse("stock:sale_detail", kwargs={"pk": self.sale.pk}),
            reverse("stock:receipt", kwargs={"pk": self.sale.pk}),
            reverse("stock:contact_list"),
            reverse("stock:contact_list") + "?q=ahmet&rol=musteri",
            reverse("stock:contact_create"),
            reverse("stock:contact_detail", kwargs={"pk": self.contact.pk}),
            reverse("stock:contact_edit", kwargs={"pk": self.contact.pk}),
            reverse("stock:intake"),
            reverse("stock:stocktake"),
        ]

    def money_urls(self):
        return [
            reverse("stock:reports"),
            reverse("stock:reports") + "?donem=bugun",
            reverse("stock:reports") + "?donem=ay",
            reverse("stock:reports") + "?donem=yil",
            reverse("stock:expense_list"),
            reverse("stock:expense_list") + "?tur=kira&kapsam=genel",
            reverse("stock:expense_create"),
            reverse("stock:expense_create") + f"?cihaz={self.device.pk}",
        ]


class PatronScreenTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    def test_all_screens_render(self):
        for url in self.urls() + self.money_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)

    def test_htmx_partials_render(self):
        headers = {"HTTP_HX_REQUEST": "true"}
        for url in [reverse("stock:device_list"), reverse("stock:accessory_list"),
                    reverse("stock:sale_list"), reverse("stock:contact_list"),
                    reverse("stock:expense_list")]:
            with self.subTest(url=url):
                response = self.client.get(url, **headers)
                self.assertEqual(response.status_code, 200)
                # Parça tam sayfa DEĞİL: sidebar işaretlemesi olmamalı
                self.assertNotContains(response, "<aside")

    def test_every_label_format_renders(self):
        for key in LABEL_FORMATS:
            with self.subTest(format=key):
                response = self.client.get(
                    reverse("stock:label_print"),
                    {"ids": self.device.pk, "acc": self.accessory.pk,
                     "format": key, "copies": 2})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "<svg")
                self.assertContains(response, self.device.stock_code)


class PersonelPermissionTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.personel)

    def test_personel_can_reach_operational_screens(self):
        for url in self.urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_personel_is_redirected_away_from_money_screens(self):
        for url in self.money_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302, url)
                self.assertIn("giris", response["Location"])

    def test_cost_never_reaches_personel_html(self):
        """Maliyet ne listede ne detayda ne de htmx parçasında görünmemeli."""
        for url in [reverse("stock:device_list"),
                    reverse("stock:device_detail", kwargs={"pk": self.device.pk}),
                    reverse("stock:accessory_detail", kwargs={"pk": self.accessory.pk}),
                    reverse("stock:sale_detail", kwargs={"pk": self.sale.pk})]:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("16.000", body)     # cihaz alış fiyatı
                self.assertNotIn("Maliyet", body)
                self.assertNotIn("Net Kâr", body)

    def test_cost_field_is_removed_from_device_form(self):
        response = self.client.get(reverse("stock:device_edit",
                                           kwargs={"pk": self.device.pk}))
        self.assertNotContains(response, 'name="purchase_price"')

    def test_personel_cannot_post_a_cost(self):
        """Alan formdan pop edildiği için POST edilen maliyet yok sayılmalı."""
        response = self.client.post(
            reverse("stock:device_edit", kwargs={"pk": self.device.pk}),
            {"device_model": self.model.pk, "condition": "ikinci_el",
             "imei1": "351234567890123", "imei2": "", "serial_no": "",
             "storage": "256GB", "color": "Grafit", "shelf": "", "defect_note": "",
             "purchase_date": "2026-01-01", "purchase_price": "1",
             "list_price": "18500", "warranty_months": 12},
        )
        self.assertIn(response.status_code, (200, 302))
        self.device.refresh_from_db()
        self.assertEqual(self.device.purchase_price, TL("16000.00"))

    def test_personel_is_kept_out_of_django_admin(self):
        """is_staff=False olduğu için /yonetim/ maliyeti göstermez."""
        response = self.client.get("/yonetim/")
        self.assertIn(response.status_code, (302, 403))


class AnonymousTests(ScreenTestCase):
    def test_all_stock_screens_require_login(self):
        for url in self.urls() + self.money_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302, url)


class ScanFlowTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    def test_lookup_redirects_to_detail(self):
        response = self.client.post(reverse("stock:scan_resolve"),
                                    {"mode": "lookup", "code": self.accessory.barcode})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"],
                         reverse("stock:accessory_detail", kwargs={"pk": self.accessory.pk}))

    def test_unknown_code_returns_200_not_404(self):
        """htmx 1.9 2xx dışını swap etmez; 404 dönseydi ekranda hiçbir şey olmazdı."""
        response = self.client.post(reverse("stock:scan_resolve"),
                                    {"mode": "lookup", "code": "YOKBOYLE"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bulunamadı")

    def test_scanning_into_cart_and_checkout(self):
        device = services.create_device(user=self.patron, device_model=self.model,
                                        purchase_price=TL("5000"),
                                        list_price=TL("7000"))
        response = self.client.post(reverse("stock:scan_resolve"),
                                    {"mode": "sale", "code": device.stock_code})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, device.label)
        # Cihaz sepete girdiği için müşteri alanı görünmeli
        self.assertContains(response, "Müşteri")

        self.client.post(reverse("stock:cart_customer"),
                         {"customer": self.contact.pk})
        response = self.client.post(reverse("stock:checkout"),
                                    {"paid_amount": "7000", "payment_method": "nakit"})
        self.assertEqual(response.status_code, 200)
        device.refresh_from_db()
        self.assertEqual(device.status, Device.Status.SATILDI)

    def test_accessory_only_cart_hides_customer_block(self):
        response = self.client.post(reverse("stock:scan_resolve"),
                                    {"mode": "sale", "code": self.accessory.barcode})
        self.assertNotContains(response, "Cihaz satışında zorunludur")

    def test_intake_scan_increments_stock(self):
        self.accessory.refresh_from_db()
        before = self.accessory.stock_qty
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "intake", "code": self.accessory.barcode})
        self.accessory.refresh_from_db()
        self.assertEqual(self.accessory.stock_qty, before + 1)

    def test_stocktake_scan_then_finish_applies_difference(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "count", "code": self.accessory.barcode})
        response = self.client.post(reverse("stock:stocktake_finish"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.accessory.refresh_from_db()
        # 1 adet sayıldı -> stok 1'e çekilmeli
        self.assertEqual(self.accessory.stock_qty, 1)


class CheckoutPaymentDefaultTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)
        self.accessory.refresh_from_db()

    def _fill_cart(self, qty=2):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        if qty > 1:
            self.client.post(reverse("stock:cart_qty", kwargs={"lid": f"a-{self.accessory.pk}"}),
                             {"qty": qty})
        from apps.stock import cart as cart_utils
        return cart_utils.summarize(cart_utils.get_cart(self.client), with_money=False)

    def test_paid_amount_input_is_prefilled_with_full_payable(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        body = self.client.get(reverse("stock:pos")).content.decode()
        self.assertIn('name="paid_amount"', body)
        # Tutar alanı artık type="text" ve Türkçe biçimli ("150,90"); değeri Alpine
        # x-model="paidText" ile doldurur (static/js/fields.js). Sunucu bu biçimi okur.
        self.assertIn("paidText: '150,90'", body)
        self.assertIn('x-model="paidText"', body)

    def test_decimal_values_are_never_localized_in_number_inputs(self):
        import re
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        body = self.client.get(reverse("stock:pos")).content.decode()
        for match in re.finditer(r'<input[^>]*type="number"[^>]*>', body):
            tag = match.group(0)
            value = re.search(r'value="([^"]*)"', tag)
            if value:
                self.assertNotIn(",", value.group(1), tag)

    def test_empty_paid_amount_is_treated_as_full_payment_not_debt(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.client.post(reverse("stock:checkout"), {"payment_method": "nakit"})
        sale = Sale.objects.latest("id")
        self.assertEqual(sale.paid_total, sale.payable_total)
        self.assertEqual(sale.balance, TL("0.00"))

    def test_explicit_zero_still_creates_a_credit_sale(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.client.post(reverse("stock:checkout"),
                         {"paid_amount": "0", "payment_method": "nakit"})
        sale = Sale.objects.latest("id")
        self.assertEqual(sale.paid_total, TL("0.00"))
        self.assertEqual(sale.balance, sale.payable_total)

    def test_partial_payment_is_respected(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.client.post(reverse("stock:checkout"),
                         {"paid_amount": "100", "payment_method": "nakit"})
        sale = Sale.objects.latest("id")
        self.assertEqual(sale.paid_total, TL("100.00"))
        self.assertEqual(sale.balance, TL("50.90"))

    def test_comma_decimal_input_is_accepted(self):
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.client.post(reverse("stock:checkout"),
                         {"paid_amount": "150,90", "payment_method": "nakit"})
        sale = Sale.objects.latest("id")
        self.assertEqual(sale.balance, TL("0.00"))


class SellButtonTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)
        self.spare = services.create_device(
            user=self.patron, device_model=self.model,
            purchase_price=TL("5000"), list_price=TL("7000"))

    def test_list_and_detail_show_sell_button_for_available_device(self):
        url = reverse("stock:sell_device", kwargs={"pk": self.spare.pk})
        self.assertContains(self.client.get(reverse("stock:device_list")), url)
        self.assertContains(
            self.client.get(reverse("stock:device_detail", kwargs={"pk": self.spare.pk})),
            url)

    def test_sold_device_shows_no_sell_button(self):
        url = reverse("stock:sell_device", kwargs={"pk": self.device.pk})
        self.assertNotContains(
            self.client.get(reverse("stock:device_detail", kwargs={"pk": self.device.pk})),
            url)

    def test_sell_button_adds_to_cart_and_redirects_to_pos(self):
        response = self.client.post(
            reverse("stock:sell_device", kwargs={"pk": self.spare.pk}))
        self.assertRedirects(response, reverse("stock:pos"))
        body = self.client.get(reverse("stock:pos")).content.decode()
        self.assertIn(self.spare.stock_code, body)
        self.assertIn("7000.00", body)

    def test_sell_button_refuses_unavailable_device(self):
        response = self.client.post(
            reverse("stock:sell_device", kwargs={"pk": self.device.pk}))
        self.assertRedirects(
            response, reverse("stock:device_detail", kwargs={"pk": self.device.pk}))
        from apps.stock import cart as cart_utils
        self.assertEqual(cart_utils.get_cart(self.client).get("lines"), [])

    def test_sell_then_checkout_completes_the_sale(self):
        self.client.post(reverse("stock:sell_device", kwargs={"pk": self.spare.pk}))
        self.client.post(reverse("stock:cart_customer"),
                         {"customer": self.contact.pk})
        self.client.post(reverse("stock:checkout"), {"payment_method": "nakit"})
        self.spare.refresh_from_db()
        self.assertEqual(self.spare.status, Device.Status.SATILDI)
        self.assertEqual(self.spare.sold_price, TL("7000.00"))

    def test_sell_button_requires_post(self):
        self.assertEqual(
            self.client.get(reverse("stock:sell_device",
                                    kwargs={"pk": self.spare.pk})).status_code, 405)


class DeviceProductLinkTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)
        self.spare = services.create_device(
            user=self.patron, device_model=self.model,
            purchase_price=TL("5000"), list_price=TL("7000"), storage="128GB")

    def test_publishing_creates_a_linked_catalog_product(self):
        from apps.catalog.models import Product
        product = services.publish_device_to_site(self.spare, user=self.patron)
        self.spare.refresh_from_db()
        self.assertEqual(self.spare.published_product, product)
        self.assertEqual(product.source_device, self.spare)
        self.assertTrue(product.is_active)
        self.assertEqual(Product.objects.filter(source_device=self.spare).count(), 1)

    def test_selling_deactivates_the_listing(self):
        product = services.publish_device_to_site(self.spare, user=self.patron)
        cart = {"customer_id": self.contact.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": self.spare.pk,
                           "name": self.spare.label, "qty": 1, "unit": "7000"}]}
        services.create_sale_from_cart(cart, user=self.patron, confirm_prices=True)
        product.refresh_from_db()
        self.assertFalse(product.is_active)

    def test_returning_the_device_does_not_resurrect_the_listing(self):
        product = services.publish_device_to_site(self.spare, user=self.patron)
        cart = {"customer_id": self.contact.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": self.spare.pk,
                           "name": self.spare.label, "qty": 1, "unit": "7000"}]}
        sale = services.create_sale_from_cart(cart, user=self.patron,
                                              confirm_prices=True)
        services.return_sale_item(sale.items.get(), user=self.patron)
        product.refresh_from_db()
        self.assertFalse(product.is_active)

    def test_republishing_overwrites_manual_edits(self):
        product = services.publish_device_to_site(self.spare, user=self.patron)
        product.name = "ELLE DEĞİŞTİRİLDİ"
        product.save()
        services.publish_device_to_site(self.spare, user=self.patron)
        product.refresh_from_db()
        self.assertEqual(product.name, self.spare.label)

    def test_deleting_the_listing_keeps_the_device(self):
        product = services.publish_device_to_site(self.spare, user=self.patron)
        product.delete()
        self.spare.refresh_from_db()
        self.assertIsNone(self.spare.published_product)
        self.assertEqual(self.spare.status, Device.Status.STOKTA)

    def test_only_in_stock_devices_can_be_published(self):
        services.set_device_status(self.spare, Device.Status.SERVISTE,
                                   user=self.patron)
        with self.assertRaises(services.StockError):
            services.publish_device_to_site(self.spare, user=self.patron)

    def test_panel_product_list_marks_device_sourced_listings(self):
        services.publish_device_to_site(self.spare, user=self.patron)
        response = self.client.get(reverse("dashboard:crud_list", kwargs={"key": "urunler"}))
        self.assertContains(response, self.spare.stock_code)
        self.assertContains(response, "Stoktan yönetiliyor")

    def test_website_hides_sold_device_listings(self):
        services.publish_device_to_site(self.spare, user=self.patron)
        listed = self.client.get(reverse("website:products")).content.decode()
        self.assertIn(self.spare.label, listed)
        cart = {"customer_id": self.contact.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": self.spare.pk,
                           "name": self.spare.label, "qty": 1, "unit": "7000"}]}
        services.create_sale_from_cart(cart, user=self.patron, confirm_prices=True)
        after = self.client.get(reverse("website:products")).content.decode()
        self.assertNotIn(self.spare.label, after)


class DeviceListOrderingTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)
        self.a = services.create_device(user=self.patron, device_model=self.model,
                                        purchase_price=TL("1000"), shelf="A")
        self.b = services.create_device(user=self.patron, device_model=self.model,
                                        purchase_price=TL("2000"), shelf="B")
        self.c = services.create_device(user=self.patron, device_model=self.model,
                                        purchase_price=TL("3000"), shelf="C")

    def _codes_in_order(self, params=""):
        import re
        body = self.client.get(reverse("stock:device_list") + params).content.decode()
        return re.findall(r"BYC-\d{6}", body)

    def test_newest_created_is_first_by_default(self):
        self.assertEqual(self._codes_in_order()[0], self.c.stock_code)

    def test_editing_an_old_device_moves_it_to_the_top(self):
        self.a.shelf = "Z-9"
        self.a.save()
        self.assertEqual(self._codes_in_order()[0], self.a.stock_code)

    def test_status_change_moves_device_to_the_top(self):
        services.set_device_status(self.b, Device.Status.SERVISTE, user=self.patron)
        self.assertEqual(self._codes_in_order()[0], self.b.stock_code)

    def test_selling_moves_device_to_the_top(self):
        self.a.list_price = TL("1500")
        self.a.save()
        cart = {"customer_id": self.contact.pk,
                "lines": [{"lid": "d", "kind": "cihaz", "id": self.a.pk,
                           "name": self.a.label, "qty": 1, "unit": "1500"}]}
        services.create_sale_from_cart(cart, user=self.patron, confirm_prices=True)
        self.assertEqual(self._codes_in_order()[0], self.a.stock_code)

    def test_publishing_to_site_moves_device_to_the_top(self):
        self.b.list_price = TL("2500")
        self.b.save()
        services.publish_device_to_site(self.c, user=self.patron)
        self.assertEqual(self._codes_in_order()[0], self.c.stock_code)

    def test_other_orderings_still_work(self):
        self.assertEqual(self._codes_in_order("?sirala=-created_at")[0],
                         self.c.stock_code)
        by_model = self._codes_in_order("?sirala=device_model__name")
        self.assertTrue(by_model)

    def test_unknown_ordering_falls_back_to_default(self):
        self.a.shelf = "Z-9"
        self.a.save()
        self.assertEqual(self._codes_in_order("?sirala=DROP TABLE")[0],
                         self.a.stock_code)
