from django.test import TestCase

from .models import SiteSettings

# Create your tests here.


class SiteSettingsTests(TestCase):
    def test_settings_are_a_singleton(self):
        first = SiteSettings.load()
        SiteSettings(brand_name="İkinci").save()
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(SiteSettings.load().pk, first.pk)

    def test_opening_hours_skip_malformed_rows(self):
        site = SiteSettings(hours_weekday="09:00-20:00", hours_saturday="akşam 8",
                            hours_sunday="")
        self.assertEqual(site.opening_hours_spec, [{
            "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "opens": "09:00", "closes": "20:00",
        }])

    def test_instagram_handle(self):
        self.assertEqual(
            SiteSettings(instagram="https://instagram.com/bayco/?igsh=x").instagram_handle,
            "@bayco")
        self.assertEqual(SiteSettings(instagram="").instagram_handle, "")
