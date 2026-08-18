from django.db import models


class SiteSettings(models.Model):
    """Site geneli ayarlar — tekil (singleton) kayıt. Panelden yönetilir."""

    brand_name = models.CharField("İşletme Adı", max_length=120, default="Bayço Teknoloji")
    tagline = models.CharField(
        "Slogan", max_length=200, blank=True,
        default="Eskişehir'in telefon ve teknoloji adresi",
    )

    # İletişim
    phone = models.CharField("Telefon", max_length=40, default="0850 000 00 00")
    whatsapp_number = models.CharField(
        "WhatsApp Numarası", max_length=20, default="905000000000",
        help_text="Ülke koduyla, sadece rakam. Örn: 905321234567",
    )
    email = models.EmailField("E-posta", blank=True, default="info@baycoteknoloji.com")
    address = models.CharField("Adres", max_length=255, blank=True,
                               default="Hoşnudiye Mah. Kızılcıklı Mahmut Pehlivan Cad. No:12, Tepebaşı / Eskişehir")
    postal_code = models.CharField("Posta Kodu", max_length=10, blank=True, default="26130",
                                   help_text="Google işletme verisi için. Örn: 26130")
    maps_embed = models.TextField(
        "Google Harita Embed URL", blank=True,
        help_text="Google Maps > Paylaş > Harita yerleştir > src bağlantısı",
    )
    working_hours = models.CharField("Çalışma Saatleri", max_length=120, blank=True,
                                     default="Hafta içi 09:00 - 20:00 · Cumartesi 10:00 - 18:00")

    # Hero
    hero_title = models.CharField("Hero Başlık", max_length=160,
                                  default="Eskişehir'de Yeni ve İkinci El Telefonun Adresi")
    hero_subtitle = models.CharField(
        "Hero Alt Metin", max_length=300, blank=True,
        default="Eskişehir Bayço Teknoloji; sıfır ve garantili ikinci el telefonlar, aksesuar "
                "ve profesyonel teknik servis. Telefonunu sat, takas et veya hemen fiyat teklifi al.",
    )
    hero_bg = models.ImageField("Hero Arka Plan (mağaza fotoğrafı)",
                                upload_to="site/", blank=True, null=True)
    hero_cta_text = models.CharField("Hero Buton Metni", max_length=40, default="Teklif Al")

    # Kampanya şeridi
    campaign_active = models.BooleanField("Kampanya şeridi aktif", default=True)
    campaign_text = models.CharField(
        "Kampanya Metni", max_length=200, blank=True,
        default="🎉 Tüm ikinci el telefonlarda 12 aya varan garanti · Ücretsiz kargo · Kapıda ödeme",
    )

    # Sosyal kanıt
    google_rating = models.DecimalField("Google Puanı", max_digits=2, decimal_places=1, default=4.9)
    google_review_count = models.PositiveIntegerField("Yorum Sayısı", default=128)
    google_review_url = models.URLField(
        "Google Yorum Linki", blank=True,
        help_text="Google işletme kaydınızın yorum bağlantısı. GİRİLMEZSE yukarıdaki puan "
                  "Google'a yapısal veri olarak bildirilmez — doğrulanamayan puan bildirmek "
                  "politika ihlalidir ve sitenin tüm zengin sonuçlarını kaybettirebilir.",
    )

    # Footer
    footer_about = models.TextField(
        "Footer Açıklama", blank=True,
        default="Eskişehir Bayço Teknoloji; sıfır ve ikinci el telefon satışı, takas, aksesuar "
                "ve teknik servis alanında Eskişehir'in güvenilir adresi.",
    )

    # Sosyal medya
    instagram = models.URLField("Instagram", blank=True)
    facebook = models.URLField("Facebook", blank=True)
    tiktok = models.URLField("TikTok", blank=True)
    youtube = models.URLField("YouTube", blank=True)

    # ---------- SEO / Google ----------
    seo_title = models.CharField(
        "SEO Başlık (ana sayfa)", max_length=70, blank=True,
        default="Eskişehir Sıfır & İkinci El Telefon, Takas | Bayço Teknoloji",
        help_text="Google'da görünen başlık. 60 karakteri geçmeyin — fazlası kırpılır.",
    )
    seo_description = models.CharField(
        "SEO Açıklama (ana sayfa)", max_length=180, blank=True,
        default="Eskişehir Bayço Teknoloji: sıfır ve ikinci el telefon satışı, telefon takas, "
                "aksesuar ve teknik servis. Eskişehir'de güvenilir, garantili telefon mağazası.",
        help_text="Arama sonuçlarındaki açıklama. 150-160 karakter ideal.",
    )
    seo_keywords = models.CharField(
        "Anahtar Kelimeler", max_length=300, blank=True,
        default="Eskişehir telefon, Eskişehir ikinci el telefon, Eskişehir sıfır telefon, "
                "telefon takas Eskişehir, telefon tamiri Eskişehir, teknik servis Eskişehir",
        help_text="Virgülle ayırın. Google sıralamada kullanmaz; diğer motorlar için tutulur.",
    )
    google_site_verification = models.CharField(
        "Google Search Console Doğrulama Kodu", max_length=120, blank=True,
        help_text="Search Console > HTML etiketi yönteminde verilen content=\"...\" değeri. "
                  "Sadece kodu yapıştırın, etiketin tamamını değil.",
    )
    google_analytics_id = models.CharField(
        "Google Analytics 4 Ölçüm Kimliği", max_length=40, blank=True,
        help_text="G- ile başlar. Örn: G-XXXXXXXXXX. Boş bırakılırsa izleme kodu eklenmez.",
    )
    latitude = models.DecimalField(
        "Enlem (latitude)", max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Google Haritalar'da mağazaya sağ tıklayınca çıkan ilk sayı. Örn: 39.776667",
    )
    longitude = models.DecimalField(
        "Boylam (longitude)", max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Google Haritalar'daki ikinci sayı. Örn: 30.520556",
    )
    price_range = models.CharField(
        "Fiyat Aralığı", max_length=10, blank=True, default="₺₺",
        help_text="Google işletme kartı için. ₺ ile ₺₺₺₺ arası.",
    )
    # Makine okunabilir çalışma saatleri. `working_hours` sitede gösterilen serbest
    # metindir; Google'ın openingHoursSpecification'ı ise "HH:MM" biçimi ister.
    hours_weekday = models.CharField(
        "Hafta içi saatleri", max_length=20, blank=True, default="09:00-20:00",
        help_text="AÇILIŞ-KAPANIŞ biçiminde. Kapalıysa boş bırakın. Örn: 09:00-20:00",
    )
    hours_saturday = models.CharField(
        "Cumartesi saatleri", max_length=20, blank=True, default="10:00-18:00",
        help_text="Kapalıysa boş bırakın.",
    )
    hours_sunday = models.CharField(
        "Pazar saatleri", max_length=20, blank=True, default="",
        help_text="Kapalıysa boş bırakın.",
    )

    class Meta:
        verbose_name = "Site Ayarı"
        verbose_name_plural = "Site Ayarları"

    def __str__(self):
        return self.brand_name

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def whatsapp_link(self):
        return f"https://wa.me/{self.whatsapp_number}"

    @property
    def social_links(self):
        """schema.org sameAs için dolu olan sosyal medya adresleri."""
        return [u for u in (self.instagram, self.facebook, self.tiktok, self.youtube) if u]

    @property
    def instagram_handle(self):
        """Instagram adresinden "@kullaniciadi". Adres yoksa/parse edilemezse boş.

        Panele tam URL giriliyor (model URLField); pop-up ve benzeri yerlerde
        gösterilecek olan ise kullanıcı adı. Sondaki eğik çizgi ve `?igsh=...`
        gibi paylaşım parametreleri temizlenir.
        """
        url = (self.instagram or "").strip()
        if not url:
            return ""
        path = url.split("?")[0].split("#")[0].rstrip("/")
        handle = path.rsplit("/", 1)[-1]
        return f"@{handle}" if handle and "." not in handle else ""

    @property
    def opening_hours_spec(self):
        """schema.org openingHoursSpecification listesi.

        Şablonda `{"...": ...}` sözlükleri kurmak JSON-LD'yi okunamaz hale
        getiriyor; gün/saat ayrıştırmasını burada yapıp hazır sözlük veriyoruz.
        Hatalı girilen saat ("akşam 8" gibi) satırı sessizce atlanır — bozuk
        yapısal veri, eksik yapısal veriden daha kötüdür.
        """
        days = [
            (self.hours_weekday, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]),
            (self.hours_saturday, ["Saturday"]),
            (self.hours_sunday, ["Sunday"]),
        ]
        spec = []
        for raw, day_names in days:
            value = (raw or "").strip()
            if "-" not in value:
                continue
            opens, _, closes = value.partition("-")
            opens, closes = opens.strip(), closes.strip()
            if not (_looks_like_time(opens) and _looks_like_time(closes)):
                continue
            spec.append({"days": day_names, "opens": opens, "closes": closes})
        return spec


def _looks_like_time(value):
    """"HH:MM" mi? Google başka biçimleri reddeder."""
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return False
    hour, minute = int(parts[0]), int(parts[1])
    return 0 <= hour <= 23 and 0 <= minute <= 59


class Slider(models.Model):
    """Hero'daki cube swiper slaytları / duyuru görselleri."""

    title = models.CharField("Başlık", max_length=120)
    subtitle = models.CharField("Alt Başlık", max_length=200, blank=True)
    badge = models.CharField("Rozet", max_length=40, blank=True,
                             help_text="Örn: YENİ, KAMPANYA")
    image = models.ImageField("Görsel", upload_to="slider/", blank=True, null=True)
    link_url = models.CharField("Bağlantı (opsiyonel)", max_length=255, blank=True)
    order = models.PositiveIntegerField("Sıra", default=0)
    is_active = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Duyuru / Slayt"
        verbose_name_plural = "Duyurular / Slaytlar"
        ordering = ["order", "-id"]

    def __str__(self):
        return self.title


class Testimonial(models.Model):
    """Müşteri yorumları."""

    name = models.CharField("Ad Soyad", max_length=120)
    role = models.CharField("Ünvan / Şehir", max_length=120, blank=True)
    rating = models.PositiveSmallIntegerField("Puan (1-5)", default=5)
    comment = models.TextField("Yorum")
    avatar = models.ImageField("Fotoğraf", upload_to="testimonials/", blank=True, null=True)
    order = models.PositiveIntegerField("Sıra", default=0)
    is_active = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Müşteri Yorumu"
        verbose_name_plural = "Müşteri Yorumları"
        ordering = ["order", "-id"]

    def __str__(self):
        return f"{self.name} ({self.rating}★)"

    @property
    def stars(self):
        return range(self.rating)

    @property
    def empty_stars(self):
        return range(5 - self.rating)


class FAQ(models.Model):
    """Sık sorulan sorular."""

    question = models.CharField("Soru", max_length=200)
    answer = models.TextField("Cevap")
    order = models.PositiveIntegerField("Sıra", default=0)
    is_active = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Sık Sorulan Soru"
        verbose_name_plural = "Sık Sorulan Sorular"
        ordering = ["order", "-id"]

    def __str__(self):
        return self.question
