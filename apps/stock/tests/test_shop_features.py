"""Aksesuar liste filtresi, bölünmüş ödeme, bilgi fişi, fiş logosu, mağaza içi
EAN-13 önerisi ve Niimbot görünümlü aksesuar etiketi."""

import io
import shutil
import tempfile
from decimal import Decimal

from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.catalog.models import Brand
from apps.sitecore.models import SiteSettings
from apps.staff.models import ActivityLog
from apps.stock import pos58, services
from apps.stock.labels import ean13_check_digit, ean13_is_valid
from apps.stock.models import Accessory, Sale
from apps.stock.niimbot import _bar_left, bar_modules, mm_to_px

from .test_views import ScreenTestCase

TL = Decimal


def png(response) -> Image.Image:
    return Image.open(io.BytesIO(response.content))


class AccessoryListFilterTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)
        self.spigen = Brand.objects.create(name="Spigen")
        self.case = Accessory.objects.create(name="Kılıf", brand=self.spigen,
                                             price=TL("300"))
        services.receive_accessory_stock(self.case, 3, user=self.patron, opening=True)
        self.accessory.refresh_from_db()   # 10 açılış − 2 satış = 8

    def listed(self, **params):
        response = self.client.get(reverse("stock:accessory_list"), params)
        self.assertEqual(response.status_code, 200)
        return response, [a.pk for a in response.context["page"]]

    def test_brand_filter(self):
        _, pks = self.listed(marka="spigen")
        self.assertEqual(pks, [self.case.pk])

    def test_brand_choices_are_only_brands_with_accessories(self):
        response, _ = self.listed()
        self.assertEqual(list(response.context["brands"]), [self.spigen])

    def test_orderings(self):
        for sirala, expected in (
                ("stock_qty", [self.case.pk, self.accessory.pk]),
                ("-stock_qty", [self.accessory.pk, self.case.pk]),
                ("name", [self.case.pk, self.accessory.pk]),           # Kılıf < Şarj
                ("-updated_at", [self.case.pk, self.accessory.pk]),
                ("-created_at", [self.case.pk, self.accessory.pk])):
            with self.subTest(sirala=sirala):
                self.assertEqual(self.listed(sirala=sirala)[1], expected)

    def test_default_is_last_activity_and_unknown_ordering_falls_back(self):
        for params in ({}, {"sirala": "cost; DROP"}):
            with self.subTest(params=params):
                response, pks = self.listed(**params)
                self.assertEqual(response.context["sirala"], "-updated_at")
        # Satış stoğu yeniden yazar: satılan ürün "Son İşlem"de başa geçer.
        services.write_off_accessory(self.accessory, 1, user=self.patron)
        self.assertEqual(self.listed()[1], [self.accessory.pk, self.case.pk])

    def test_more_button_keeps_filters(self):
        response = self.client.get(reverse("stock:accessory_list"),
                                   {"marka": "spigen", "sirala": "name"})
        self.assertIn("marka=spigen", response.context["qs"])
        self.assertIn("sirala=name", response.context["qs"])


class SplitPaymentTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)
        self.client.post(reverse("stock:scan_resolve"),
                         {"mode": "sale", "code": self.accessory.barcode})
        self.client.post(reverse("stock:cart_price", kwargs={"lid": f"a-{self.accessory.pk}"}),
                         {"price": "1.000"})

    def checkout(self, amounts, methods):
        # Sepet fiyatı karttakinden farklı (1.000 ≠ 150,90): onay kutusu işaretli.
        return self.client.post(reverse("stock:checkout"),
                                {"paid_amount": amounts, "payment_method": methods,
                                 "confirm_prices": "1"})

    def payments(self, sale):
        return [(p.method, p.amount) for p in sale.payments.order_by("paid_at", "id")]

    def test_cash_and_card_become_two_payments(self):
        response = self.checkout(["500", "500"], ["nakit", "kart"])
        sale = Sale.objects.latest("id")
        self.assertEqual(self.payments(sale), [("nakit", TL("500.00")), ("kart", TL("500.00"))])
        self.assertEqual(sale.paid_total, TL("1000.00"))
        self.assertEqual(sale.balance, TL("0.00"))
        self.assertContains(response, "Nakit 500,00 ₺ · Kredi Kartı 500,00 ₺")
        log = ActivityLog.objects.filter(view_name="stock:checkout").latest("id")
        self.assertEqual(log.detail["Ödeme"], "Nakit 500,00 ₺ + Kredi Kartı 500,00 ₺")

    def test_short_split_leaves_the_rest_as_credit(self):
        self.checkout(["300", "200"], ["nakit", "kart"])
        self.assertEqual(Sale.objects.latest("id").balance, TL("500.00"))

    def test_same_method_twice_is_merged(self):
        self.checkout(["300", "200,50"], ["nakit", "nakit"])
        sale = Sale.objects.latest("id")
        self.assertEqual(self.payments(sale), [("nakit", TL("500.50"))])

    def test_empty_and_zero_rows_are_skipped(self):
        self.checkout(["1.000", "", "0"], ["kart", "nakit", "havale"])
        self.assertEqual(self.payments(Sale.objects.latest("id")), [("kart", TL("1000.00"))])

    def test_one_unreadable_row_stops_the_whole_sale(self):
        response = self.checkout(["500", "abc"], ["nakit", "kart"])
        self.assertContains(response, "Geçersiz tahsilat tutarı.")
        self.assertFalse(Sale.objects.exclude(pk=self.sale.pk).exists())

    def test_unknown_method_in_a_row_falls_back_to_cash(self):
        self.checkout(["400", "600"], ["x" * 50, "kart"])
        self.assertEqual(self.payments(Sale.objects.latest("id")),
                         [("nakit", TL("400.00")), ("kart", TL("600.00"))])

    def test_receipt_lists_payments_in_entry_order(self):
        self.checkout(["500", "500"], ["kart", "nakit"])
        texts = [line.text for line in pos58.receipt_lines(Sale.objects.latest("id"))]
        self.assertLess(texts.index("Kredi Kartı"), texts.index("Nakit"))

    def test_pos_offers_adding_a_payment_row(self):
        body = self.client.get(reverse("stock:pos")).content.decode()
        self.assertIn("Ödeme şekli ekle", body)
        self.assertIn('x-for="(row, i) in rows"', body)


class ReceiptTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    def texts(self):
        return [line.text for line in pos58.receipt_lines(self.sale)]

    def test_info_title_sits_between_header_and_items_and_legal_note_is_last(self):
        lines = pos58.receipt_lines(self.sale)
        texts = [line.text for line in lines]
        title = texts.index("BİLGİ FİŞİ")
        self.assertEqual(lines[0].kind, "logo")
        self.assertLess(texts.index("Fiş No"), title)
        self.assertLess(title, texts.index(self.accessory.name))
        self.assertEqual(texts[-1], "Mali değeri yoktur.")
        self.assertIn("Bizi tercih ettiğiniz için teşekkürler.", texts)

    def test_items_show_quantity_imei_and_warranty_note(self):
        texts = self.texts()
        self.assertIn("2 × 150,90 ₺", texts)
        self.assertIn(f"IMEI: {self.device.imei1}", texts)
        self.assertIn(f"{self.device.label} — garanti kapsamı için bu fişi saklayınız.", texts)

    def test_open_balance_and_due_date(self):
        rows = {line.text: line.right for line in pos58.receipt_lines(self.sale)}
        self.assertEqual(rows["KALAN"], "8.801,80 ₺")
        self.assertIn("Vade", rows)

    def test_image_fits_the_print_head(self):
        response = self.client.get(reverse("stock:receipt_png", kwargs={"pk": self.sale.pk}))
        self.assertEqual(response["Content-Type"], "image/png")
        image = png(response)
        self.assertEqual(image.mode, "1")
        self.assertEqual(image.width, 384)  # 48 mm × 8 nokta
        self.assertEqual(image.getextrema(), (0, 255))

    def test_long_text_wraps_inside_the_side_margins(self):
        lines = [pos58.Line("text", "Çok " * 40),
                 pos58.Line("row", "Uzun bir açıklama " * 5, right="12.345,67 ₺"),
                 pos58.Line("center", "Ş" * 60, size="title", bold=True)]
        image = pos58.render_receipt(lines, logo=Image.new("1", (1, 1), 255))
        self.assertGreater(image.height, 200)  # sarıldı, tek satıra sıkışmadı
        for box in ((0, 0, pos58.PAD, image.height),
                    (image.width - pos58.PAD, 0, image.width, image.height)):
            self.assertEqual(image.crop(box).getextrema(), (255, 255))

    def test_image_ends_with_tear_off_space(self):
        image = pos58.receipt_image(self.sale)
        tail = mm_to_px(pos58.FEED_MM)
        self.assertEqual(image.crop((0, image.height - tail, image.width, image.height))
                         .getextrema(), (255, 255))
        # Hemen üstünde son satır ("Mali değeri yoktur.") basılı.
        self.assertEqual(image.crop((0, image.height - tail - 20, image.width,
                                     image.height - tail)).getextrema()[0], 0)

    def test_page_prints_the_image_with_the_browser(self):
        url = reverse("stock:receipt", kwargs={"pk": self.sale.pk})
        response = self.client.get(url + "?auto=1")
        self.assertContains(response, reverse("stock:receipt_png", kwargs={"pk": self.sale.pk}))
        self.assertContains(response, 'onclick="window.print()"')
        self.assertContains(response, "setTimeout(window.print, 250)")
        height = pos58.height_mm(pos58.receipt_image(self.sale))
        self.assertContains(response, f"@page {{ size: 58mm {height:.1f}mm; margin: 0; }}")
        self.assertNotContains(response, "pos58.js")
        self.assertNotContains(self.client.get(url), "setTimeout(window.print, 250)")

    def test_logo_is_one_bit_and_thermal_width(self):
        response = self.client.get(reverse("stock:receipt_logo"))
        self.assertEqual(response["Content-Type"], "image/png")
        image = png(response)
        self.assertEqual(image.mode, "1")
        self.assertEqual(image.width, mm_to_px(30))
        # Koyu zemin basılmaz (köşe beyaz), logonun kendisi basılır.
        self.assertEqual(image.getpixel((0, 0)), 255)
        self.assertEqual(image.getextrema(), (0, 255))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="bayco-test-media-"))
class UploadedReceiptLogoTests(ScreenTestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client.force_login(self.patron)
        self.site = SiteSettings.load()

    def test_uploaded_logo_is_used(self):
        buffer = io.BytesIO()
        Image.new("RGB", (100, 50), "white").save(buffer, format="PNG")
        self.site.receipt_logo.save("fis.png", ContentFile(buffer.getvalue()))
        image = png(self.client.get(reverse("stock:receipt_logo")))
        self.assertEqual(image.size, (mm_to_px(30), mm_to_px(30) // 2))

    def test_missing_upload_falls_back_to_site_logo(self):
        self.site.receipt_logo.name = "site/silinmis.png"
        self.site.save()
        response = self.client.get(reverse("stock:receipt_logo"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(png(response).width, mm_to_px(30))


class BarcodeSuggestionTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)

    @staticmethod
    def ean(body):
        return body + str(ean13_check_digit(body))

    def test_first_suggestion_is_a_valid_in_store_ean13(self):
        code = services.suggest_accessory_barcode()
        self.assertEqual(code, self.ean("200000000001"))
        self.assertTrue(ean13_is_valid(code))

    def test_suggestion_follows_the_last_in_store_code(self):
        Accessory.objects.create(name="Kılıf", barcode=self.ean("200000000041"))
        self.assertEqual(services.suggest_accessory_barcode(), self.ean("200000000042"))

    def test_suggestion_is_above_every_in_store_code(self):
        # Elle girilmiş, sağlaması tutmayan 200… kodu da sayılır; öneri hiçbir
        # kayıtlı barkodla aynı olmaz. Başka önekli/uzunluktaki kodlar etkilemez.
        Accessory.objects.create(name="A", barcode=self.ean("200000000007"))
        Accessory.objects.create(name="B", barcode="2000000000089")   # hatalı sağlama
        Accessory.objects.create(name="C", barcode="20000000009999")  # 14 hane
        code = services.suggest_accessory_barcode()
        self.assertEqual(code, self.ean("200000000009"))
        self.assertFalse(Accessory.objects.filter(barcode=code).exists())

    def test_generated_code_prints_as_a_barcode_on_niimbot(self):
        code = services.suggest_accessory_barcode()
        symbology, modules = bar_modules(code)
        self.assertEqual(symbology, "ean13")
        self.assertIsNotNone(_bar_left(symbology, modules, mm_to_px(40), mm_to_px(1.2)))

    def test_endpoint_redraws_the_barcode_field(self):
        response = self.client.get(reverse("stock:accessory_barcode"))
        self.assertContains(response, 'id="id_barcode"')
        self.assertContains(response, f'value="{self.ean("200000000001")}"')
        self.assertContains(response, "data-scan-fill")

    def test_button_only_where_there_is_no_barcode(self):
        create = self.client.get(reverse("stock:accessory_create"))
        self.assertContains(create, "EAN-13 üret")
        self.assertContains(create, reverse("stock:accessory_barcode"))
        edit = self.client.get(reverse("stock:accessory_edit", kwargs={"pk": self.accessory.pk}))
        self.assertNotContains(edit, "EAN-13 üret")


class AccessoryLabelTests(ScreenTestCase):
    def setUp(self):
        self.client.force_login(self.patron)
        self.png_url = reverse("stock:niimbot_png",
                               kwargs={"kind": "aksesuar", "pk": self.accessory.pk})

    def label_page(self, **params):
        return self.client.get(reverse("stock:label_print"), params).content.decode()

    def test_accessory_label_is_the_niimbot_image(self):
        body = self.label_page(acc=self.accessory.pk, format="a4-52x30")
        self.assertIn(f'src="{self.png_url}?fiyat=1"', body)
        self.assertNotIn("<svg", body)
        body = self.label_page(acc=self.accessory.pk, fiyat="0")
        self.assertIn(f'src="{self.png_url}?fiyat=0"', body)

    def test_roll_format_prints_at_native_niimbot_size(self):
        body = self.label_page(acc=self.accessory.pk, format="termal-40x30")
        self.assertIn("width:40mm; height:12mm", body)

    def test_device_labels_are_unchanged(self):
        body = self.label_page(ids=self.device.pk)
        self.assertIn("<svg", body)
        self.assertNotIn('class="lbl nb"', body)
