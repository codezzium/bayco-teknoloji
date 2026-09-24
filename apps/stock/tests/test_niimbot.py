"""Niimbot etiketinin nokta ızgarasına ve niim-agent kurallarına uyduğunu doğrular."""

import io
from decimal import Decimal

import barcode
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from PIL import Image

from apps.catalog.models import Brand
from apps.stock.labels import ean13_is_valid, symbology_for
from apps.stock.models import Accessory
from apps.stock.niimbot import MODULE_PX, bar_modules, render_label

VALID_EAN = "8690000010158"
BAD_CHECK_DIGIT = "8690000010154"  # python-barcode bunu ...158 olarak basardı


def bar_row(image: Image.Image) -> str:
    """Barkodun ortasından geçen satırı, 1 modül = 2 nokta varsayarak modüllere çevirir."""
    y = image.height // 2
    pixels = [image.getpixel((x, y)) for x in range(image.width)]
    first = pixels.index(0)
    last = len(pixels) - 1 - pixels[::-1].index(0)
    row = pixels[first:last + 1]
    assert len(row) % MODULE_PX == 0
    modules = []
    for i in range(0, len(row), MODULE_PX):
        pair = row[i:i + MODULE_PX]
        assert pair[0] == pair[1], "modül nokta ızgarasına oturmuyor"
        modules.append("1" if pair[0] == 0 else "0")
    return "".join(modules)


class Ean13Tests(SimpleTestCase):
    def test_check_digit(self):
        self.assertTrue(ean13_is_valid(VALID_EAN))
        self.assertTrue(ean13_is_valid("4006381333931"))
        self.assertFalse(ean13_is_valid(BAD_CHECK_DIGIT))
        self.assertFalse(ean13_is_valid("869000001015"))
        self.assertFalse(ean13_is_valid("869000001015X"))

    def test_bad_check_digit_is_printed_as_is(self):
        self.assertEqual(symbology_for(VALID_EAN), "ean13")
        self.assertEqual(symbology_for(BAD_CHECK_DIGIT), "code128")
        self.assertEqual(symbology_for("BYC-000123"), "code128")


class RenderTests(SimpleTestCase):
    def render(self, code, price="549 ₺"):
        return render_label(code, "Baseus Araç Şarjı 45W çift port", price)

    def test_size_and_margins(self):
        image = self.render(VALID_EAN)
        self.assertEqual((image.size, image.mode), ((320, 96), "1"))
        # 1.2 mm (10 nokta) kenar payı tamamen boş.
        inner = (10, 10, 310, 86)
        for x in range(320):
            for y in range(96):
                if not (inner[0] <= x < inner[2] and inner[1] <= y < inner[3]):
                    self.assertEqual(image.getpixel((x, y)), 255, (x, y))

    def test_valid_ean13_modules(self):
        expected = barcode.get("ean13", VALID_EAN).build()[0]
        self.assertEqual(bar_row(self.render(VALID_EAN)), expected.rstrip("0"))

    def test_bad_check_digit_encodes_stored_value(self):
        expected = barcode.get("code128", BAD_CHECK_DIGIT).build()[0]
        self.assertEqual(bar_row(self.render(BAD_CHECK_DIGIT)), expected.rstrip("0"))

    def test_quiet_zone(self):
        image = self.render(VALID_EAN)
        pixels = [image.getpixel((x, image.height // 2)) for x in range(image.width)]
        self.assertGreaterEqual(pixels.index(0), 11 * MODULE_PX)
        self.assertGreaterEqual(pixels[::-1].index(0), 11 * MODULE_PX)

    def test_long_code_falls_back_to_qr(self):
        # BYC-A-000015 Code128'de 145 modül = 290 nokta; sessiz bölgeyle sığmaz.
        self.assertEqual(len(bar_modules("BYC-A-000015")[1]), 145)
        image = self.render("BYC-A-000015")
        # QR solda, 3 noktalık modüllerle: bulucu desenin sol üst köşesi dolu.
        self.assertEqual(image.getpixel((10, 16)), 0)
        self.assertEqual(image.size, (320, 96))


class NiimbotViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patron = User.objects.create_user("patron", password="pw",
                                              is_staff=True, is_superuser=True)
        cls.accessory = Accessory.objects.create(
            name="Araç Şarjı", variant="45W", brand=Brand.objects.create(name="Baseus"),
            barcode=VALID_EAN, price=Decimal("549"))

    def url(self, kind="aksesuar", pk=None):
        return reverse("stock:niimbot_png", args=[kind, pk or self.accessory.pk])

    def test_png(self):
        self.client.force_login(self.patron)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        image = Image.open(io.BytesIO(response.content))
        self.assertEqual(image.size, (320, 96))

    def test_unknown_kind_and_missing_object(self):
        self.client.force_login(self.patron)
        self.assertEqual(self.client.get(self.url(kind="x")).status_code, 404)
        self.assertEqual(self.client.get(self.url(pk=999)).status_code, 404)

    def test_requires_login(self):
        self.assertNotEqual(self.client.get(self.url()).status_code, 200)

    def test_detail_page_has_bluetooth_print_button(self):
        self.client.force_login(self.patron)
        response = self.client.get(reverse("stock:accessory_detail", args=[self.accessory.pk]))
        self.assertContains(response, "js/niimbot.js")
        self.assertContains(response, f"niimbotPrint({{url: '{self.url()}'}})")
