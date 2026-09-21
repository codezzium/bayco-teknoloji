"""Projeye özel middleware'ler."""

from django.conf import settings as django_settings
from whitenoise.middleware import WhiteNoiseMiddleware


class MediaWhiteNoiseMiddleware(WhiteNoiseMiddleware):
    """WhiteNoise'a statiğin yanında MEDIA_ROOT'u da tanıtır.

    Yeni sunucuda host nginx yok; /media/ altını sunacak başka bir katman
    kalmadı. config/urls.py'daki ``static()`` yardımcısı yalnızca DEBUG'ta
    devrede olduğu için üretimde panelden yüklenen her görsel (marka logosu,
    ürün kapağı, ürün görselleri) 404 dönerdi.

    Not: whitenoise 6.x tüm yapılandırmayı ``__init__`` içinde yapar;
    eski sürümlerdeki ``configure_from_settings`` kancası artık yok.
    """

    def __init__(self, get_response=None, settings=django_settings):
        # Üst sınıf STATIC_ROOT'u kendisi ekler; medyayı onun üzerine koyuyoruz.
        super().__init__(get_response, settings)

        # Bu projede MEDIA_URL = "media/" — başında / yok. ``add_files`` prefix'i
        # kendisi normalize ediyor, yine de burada açıkça düzeltiyoruz ki ayar
        # ileride "/media/" olarak değişse de davranış aynı kalsın.
        prefix = "/" + str(settings.MEDIA_URL).lstrip("/")
        self.add_files(str(settings.MEDIA_ROOT), prefix=prefix)
