from django.test import TestCase

from .models import Brand, Product

# Create your tests here.


class SlugTests(TestCase):
    def test_brand_slug_is_unique_for_case_variants(self):
        first = Brand.objects.create(name="Xiaomi")
        second = Brand.objects.create(name="XIAOMI")
        self.assertEqual(first.slug, "xiaomi")
        self.assertNotEqual(first.slug, second.slug)

    def test_brand_without_latin_letters_still_gets_a_slug(self):
        first = Brand.objects.create(name="!!!")
        second = Brand.objects.create(name="???")
        self.assertTrue(first.slug)
        self.assertNotEqual(first.slug, second.slug)

    def test_brand_slug_is_kept_on_rename(self):
        brand = Brand.objects.create(name="Apple")
        brand.name = "Apple Inc"
        brand.save()
        self.assertEqual(brand.slug, "apple")

    def test_product_slug_is_unique(self):
        first = Product.objects.create(name="iPhone 13")
        second = Product.objects.create(name="iPhone 13")
        self.assertEqual((first.slug, second.slug), ("iphone-13", "iphone-13-2"))

    def test_price_display(self):
        self.assertEqual(Product(price=24999).price_display, "24.999 ₺")
        self.assertEqual(Product(price=None).price_display, "Fiyat sorunuz")
        self.assertEqual(Product(price=900, old_price=1000).discount_percent, 10)
