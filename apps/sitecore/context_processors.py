from .models import SiteSettings


def site_globals(request):
    """Her şablona site ayarlarını (iletişim, WhatsApp, sosyal medya) enjekte eder."""
    return {"site": SiteSettings.load()}
