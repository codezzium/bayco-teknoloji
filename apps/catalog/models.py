from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Brand(models.Model):
    name = models.CharField("Marka", max_length=80, unique=True)
    slug = models.SlugField("Slug", max_length=90, unique=True, blank=True)
    logo = models.ImageField("Logo", upload_to="brands/", blank=True, null=True)
    order = models.PositiveIntegerField("Sıra", default=0)
    is_public = models.BooleanField(
        "Sitede Göster", default=True,
        help_text="Kapalıysa marka yalnızca stok/panelde görünür (örn. aksesuar markaları).",
    )

    class Meta:
        verbose_name = "Marka"
        verbose_name_plural = "Markalar"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "marka"
            slug = base
            i = 2
            while Brand.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Product(models.Model):
    class Condition(models.TextChoices):
        SIFIR = "sifir", "Sıfır"
        IKINCI_EL = "ikinci_el", "İkinci El"

    name = models.CharField("Ürün Adı", max_length=160)
    slug = models.SlugField("Slug", max_length=180, unique=True, blank=True)
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="products", verbose_name="Marka")
    condition = models.CharField("Durum", max_length=10, choices=Condition.choices,
                                 default=Condition.SIFIR)

    price = models.DecimalField("Fiyat (TL)", max_digits=10, decimal_places=0,
                                null=True, blank=True,
                                help_text="Boş bırakılırsa 'Fiyat sorunuz' gösterilir.")
    old_price = models.DecimalField("Eski Fiyat (TL)", max_digits=10, decimal_places=0,
                                    null=True, blank=True,
                                    help_text="İndirim göstermek için (opsiyonel).")

    storage = models.CharField("Hafıza", max_length=40, blank=True, help_text="Örn: 128GB")
    color = models.CharField("Renk", max_length=40, blank=True)
    year = models.PositiveIntegerField("Model Yılı", null=True, blank=True)
    condition_grade = models.CharField(
        "Kozmetik Durum", max_length=60, blank=True,
        help_text="İkinci el için: Sıfır ayarında / Çok iyi / İyi vb.",
    )
    warranty = models.CharField("Garanti", max_length=60, blank=True, default="")

    short_desc = models.CharField("Kısa Açıklama", max_length=200, blank=True)
    description = models.TextField("Açıklama", blank=True)
    cover = models.ImageField("Kapak Görseli", upload_to="products/", blank=True, null=True)

    is_featured = models.BooleanField("Öne Çıkan", default=False)
    is_active = models.BooleanField("Aktif (yayında)", default=True)
    order = models.PositiveIntegerField("Sıra", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ürün"
        verbose_name_plural = "Ürünler"
        ordering = ["order", "-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "urun"
            slug = base
            i = 2
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("website:product_detail", kwargs={"slug": self.slug})

    @property
    def price_display(self):
        if self.price is None:
            return "Fiyat sorunuz"
        return f"{int(self.price):,}".replace(",", ".") + " ₺"

    @property
    def old_price_display(self):
        if self.old_price is None:
            return ""
        return f"{int(self.old_price):,}".replace(",", ".") + " ₺"

    @property
    def discount_percent(self):
        if self.price and self.old_price and self.old_price > self.price:
            return round((1 - (self.price / self.old_price)) * 100)
        return 0


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField("Görsel", upload_to="products/")
    order = models.PositiveIntegerField("Sıra", default=0)

    class Meta:
        verbose_name = "Ürün Görseli"
        verbose_name_plural = "Ürün Görselleri"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.product.name} görseli"
