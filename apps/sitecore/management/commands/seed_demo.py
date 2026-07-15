from django.core.management.base import BaseCommand

from apps.sitecore.models import SiteSettings, Slider, Testimonial, FAQ
from apps.catalog.models import Brand, Product
from apps.leads.models import QuoteRequest, ServiceRequest


class Command(BaseCommand):
    help = "Demo verilerini oluşturur (marka, ürün, slider, yorum, SSS, ayarlar, örnek talepler)."

    def handle(self, *args, **options):
        # --- Site ayarları ---
        s = SiteSettings.load()
        s.brand_name = "Bayço Teknoloji"
        s.phone = "0532 123 45 67"
        s.whatsapp_number = "905321234567"
        s.email = "info@baycoteknoloji.com"
        s.address = "Hoşnudiye Mah. Kızılcıklı Mahmut Pehlivan Cad. No:12, Tepebaşı / Eskişehir"
        s.instagram = "https://instagram.com/baycoteknoloji"
        s.google_review_url = "https://g.page/baycoteknoloji"
        s.save()
        self.stdout.write(self.style.SUCCESS("✓ Site ayarları"))

        # --- Markalar ---
        brands = {}
        for i, name in enumerate(["Apple", "Samsung", "Xiaomi", "Oppo", "Huawei", "Realme"]):
            b, _ = Brand.objects.get_or_create(name=name, defaults={"order": i})
            brands[name] = b
        self.stdout.write(self.style.SUCCESS(f"✓ {len(brands)} marka"))

        # --- Ürünler ---
        products = [
            # (ad, marka, durum, fiyat, eski_fiyat, hafıza, renk, yıl, kısa, öne, kozmetik, garanti)
            ("iPhone 15 Pro Max", "Apple", "sifir", 74999, 79999, "256GB", "Titanyum", 2024,
             "Apple garantili, sıfır kutusunda", True, "", "Apple Türkiye Garantili"),
            ("iPhone 13", "Apple", "ikinci_el", 27999, 31999, "128GB", "Gece Yarısı", 2021,
             "Sıfır ayarında, batarya %92", True, "Sıfır ayarında", "12 Ay Bayço Garanti"),
            ("Samsung Galaxy S24 Ultra", "Samsung", "sifir", 61999, None, "512GB", "Siyah", 2024,
             "S Pen dahil, sıfır", True, "", "Samsung Türkiye Garantili"),
            ("Samsung Galaxy S22", "Samsung", "ikinci_el", 18999, 22999, "256GB", "Yeşil", 2022,
             "Çok temiz, faturalı", False, "Çok iyi", "6 Ay Bayço Garanti"),
            ("Xiaomi 14", "Xiaomi", "sifir", 34999, None, "512GB", "Beyaz", 2024,
             "Leica kamera, sıfır kutu", True, "", "Xiaomi Türkiye Garantili"),
            ("Xiaomi Redmi Note 13 Pro", "Xiaomi", "sifir", 13999, 15999, "256GB", "Mavi", 2024,
             "Fiyat/performans şampiyonu", False, "", "Xiaomi Türkiye Garantili"),
            ("iPhone 12", "Apple", "ikinci_el", 19999, None, "64GB", "Mavi", 2020,
             "Ekonomik, sağlam cihaz", False, "İyi", "6 Ay Bayço Garanti"),
            ("Oppo Reno 11", "Oppo", "sifir", 17999, None, "256GB", "Yeşil", 2024,
             "Portre kamerası güçlü", False, "", "Oppo Türkiye Garantili"),
            ("Huawei Nova 12", "Huawei", "sifir", 15999, 17999, "256GB", "Siyah", 2024,
             "İnce tasarım, hızlı şarj", False, "", "Huawei Türkiye Garantili"),
            ("iPhone 14 Pro", "Apple", "ikinci_el", 42999, 46999, "256GB", "Mor", 2022,
             "Dynamic Island, kutulu", True, "Sıfır ayarında", "12 Ay Bayço Garanti"),
            ("Samsung Galaxy A55", "Samsung", "sifir", 19999, None, "256GB", "Lila", 2024,
             "Orta segment favori", False, "", "Samsung Türkiye Garantili"),
            ("Realme 12 Pro+", "Realme", "sifir", 21999, 23999, "512GB", "Bej", 2024,
             "Periskop kamera", False, "", "Realme Türkiye Garantili"),
        ]
        count = 0
        for i, (name, brand, cond, price, oldp, storage, color, year, short, feat, grade, wr) in enumerate(products):
            obj, created = Product.objects.get_or_create(
                name=name,
                defaults=dict(
                    brand=brands.get(brand), condition=cond, price=price, old_price=oldp,
                    storage=storage, color=color, year=year, short_desc=short,
                    is_featured=feat, condition_grade=grade, warranty=wr, order=i,
                    description=(
                        f"{name} — {storage} {color}. {short}. "
                        "Tüm ürünlerimiz faturalı ve garantilidir. Detaylı bilgi ve "
                        "güncel fiyat için WhatsApp üzerinden bize ulaşabilirsiniz."
                    ),
                ),
            )
            if created:
                count += 1
        self.stdout.write(self.style.SUCCESS(f"✓ {count} ürün"))

        # --- Slider / Duyurular ---
        sliders = [
            ("Sıfır Telefonda Kampanya", "Tüm modellerde 24 aya varan taksit fırsatı", "KAMPANYA"),
            ("Telefonunu Getir, Nakit Al", "İkinci el cihazına anında en yüksek teklif", "TAKAS"),
            ("Aynı Gün Ekran Değişimi", "Orijinal parça, 6 ay garanti ile teknik servis", "SERVİS"),
        ]
        for i, (title, sub, badge) in enumerate(sliders):
            Slider.objects.get_or_create(
                title=title, defaults={"subtitle": sub, "badge": badge, "order": i},
            )
        self.stdout.write(self.style.SUCCESS(f"✓ {len(sliders)} slider"))

        # --- Yorumlar ---
        testimonials = [
            ("Ahmet K.", "İstanbul", 5, "İkinci el aldığım telefon sıfır ayarındaydı, garanti de verdiler. Kesinlikle tavsiye ederim."),
            ("Elif D.", "Ankara", 5, "Eski telefonuma beklediğimden yüksek fiyat verdiler, işlem 10 dakikada bitti."),
            ("Murat S.", "İzmir", 5, "Ekran değişimi aynı gün yapıldı, fiyatı da çok uygundu. Teşekkürler Bayço."),
            ("Zeynep A.", "Bursa", 4, "Sipariş ettiğim aksesuar hızlıca geldi, iletişimleri çok iyi."),
        ]
        for i, (name, role, rating, comment) in enumerate(testimonials):
            Testimonial.objects.get_or_create(
                name=name, defaults={"role": role, "rating": rating, "comment": comment, "order": i},
            )
        self.stdout.write(self.style.SUCCESS(f"✓ {len(testimonials)} yorum"))

        # --- SSS ---
        faqs = [
            ("İkinci el telefonlara garanti veriyor musunuz?",
             "Evet. Tüm ikinci el cihazlarımız test edilerek satışa sunulur ve modeline göre 6-12 ay Bayço güvencesi ile garantilidir."),
            ("Taksit seçeneği var mı?",
             "Sıfır ve seçili ikinci el ürünlerde kredi kartına 24 aya varan taksit imkanı sunuyoruz. Detaylar için WhatsApp'tan yazabilirsiniz."),
            ("Telefonumu nasıl satabilirim / takas edebilirim?",
             "'Teklif Al' bölümünden cihaz bilgilerinizi girip WhatsApp üzerinden bize ulaşmanız yeterli. Size en kısa sürede en yüksek teklifi iletiriz."),
            ("Kargo ve kapıda ödeme var mı?",
             "Türkiye'nin her yerine kargo gönderiyoruz. Anlaşmalı bölgelerde kapıda ödeme seçeneği mevcuttur."),
            ("Ekran değişimi ne kadar sürer?",
             "Stokta bulunan modellerde ekran ve batarya değişimi çoğunlukla aynı gün, ortalama 30-60 dakikada tamamlanır."),
        ]
        for i, (q, a) in enumerate(faqs):
            FAQ.objects.get_or_create(question=q, defaults={"answer": a, "order": i})
        self.stdout.write(self.style.SUCCESS(f"✓ {len(faqs)} SSS"))

        # --- Örnek talepler (panel gelen kutusu dolu görünsün) ---
        if not QuoteRequest.objects.exists():
            QuoteRequest.objects.create(
                kind="sat", name="Can Yılmaz", phone="0555 111 22 33",
                brand="Apple", model="iPhone 13", year="2021", storage="128GB",
                condition="Çok iyi, çizik yok",
            )
            QuoteRequest.objects.create(
                kind="al", name="Derya Kaya", phone="0544 222 33 44",
                model="Samsung Galaxy S24 Ultra", storage="512GB", condition="Siyah",
            )
        if not ServiceRequest.objects.exists():
            ServiceRequest.objects.create(
                name="Okan Demir", phone="0533 444 55 66",
                device="iPhone 12", issue="Ekran kırık, dokunmatik çalışıyor",
            )
        self.stdout.write(self.style.SUCCESS("✓ Örnek talepler"))

        self.stdout.write(self.style.SUCCESS("\n🎉 Demo veriler hazır!"))
