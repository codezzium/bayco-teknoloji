from django.conf import settings

from .models import SiteSettings


def site_globals(request):
    """Her şablona site ayarlarını (iletişim, WhatsApp, sosyal medya) enjekte eder."""
    return {"site": SiteSettings.load(), "plausible_script": settings.PLAUSIBLE_SCRIPT}
