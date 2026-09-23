from django.test import SimpleTestCase

from .models import QuoteRequest
from .utils import customer_wa, normalize_tr, quote_message, wa_link

# Create your tests here.


class PhoneTests(SimpleTestCase):
    def test_turkish_numbers_are_normalized(self):
        for raw, expected in (("0532 111 22 33", "905321112233"),
                              ("+90 532 111 22 33", "905321112233"),
                              ("532 111 22 33", "905321112233"),
                              ("", "")):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_tr(raw), expected)

    def test_whatsapp_links(self):
        self.assertEqual(customer_wa("0532 111 22 33"), "https://wa.me/905321112233")
        self.assertEqual(wa_link("+90 532", "Merhaba & hoş geldin"),
                         "https://wa.me/90532?text=Merhaba%20%26%20ho%C5%9F%20geldin")


class MessageTests(SimpleTestCase):
    def test_quote_message_lists_only_filled_rows(self):
        lead = QuoteRequest(kind=QuoteRequest.Kind.SAT, name="Ali", phone="0532",
                            brand="Apple", model="iPhone 13")
        message = quote_message(lead)
        self.assertIn("• Marka: Apple", message)
        self.assertNotIn("Hafıza", message)
