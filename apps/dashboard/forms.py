from django import forms

from apps.catalog.models import Brand, Product
from apps.sitecore.models import FAQ, SiteSettings, Slider, Testimonial

from .numbers import format_decimal_input, normalize_decimal_input


class MoneyInput(forms.TextInput):
    """Tutar alanı: yazarken binlik noktası konur (static/js/fields.js).

    type="number" kullanılamaz: noktalı değeri kabul etmez ve kendi okları çıkar.
    """

    def __init__(self, attrs=None, decimals=2):
        self.decimals = decimals
        base = {"inputmode": "decimal" if decimals else "numeric", "autocomplete": "off",
                "data-money": str(decimals)}
        super().__init__({**base, **(attrs or {})})

    def format_value(self, value):
        return format_decimal_input(value, self.decimals) or None


class MoneyField(forms.DecimalField):
    """"18.500" → 18500, "18.500,90" → 18500.90 (apps.dashboard.numbers)."""

    widget = MoneyInput

    def __init__(self, *, max_digits=None, decimal_places=None, **kwargs):
        kwargs.setdefault("widget", MoneyInput(decimals=decimal_places or 0))
        super().__init__(max_digits=max_digits, decimal_places=decimal_places, **kwargs)

    def to_python(self, value):
        if value not in self.empty_values:
            value = normalize_decimal_input(value)
        return super().to_python(value)

    def widget_attrs(self, widget):
        # DecimalField'ın step/min/max'ı yalnızca number input içindir.
        return {}


class QtyInput(forms.TextInput):
    """Adet alanı: − / + düğmeli sayaç (static/js/fields.js); input'un kendi okları yok.

    Sınırlar alanın min_value / max_value'sundan _style() ile data-min/max'a yazılır.
    """

    def __init__(self, attrs=None):
        base = {"inputmode": "numeric", "autocomplete": "off", "data-qty": "1"}
        super().__init__({**base, **(attrs or {})})


def _style(fields):
    """Form alanlarına tasarım sistemi sınıflarını uygular."""
    for name, field in fields.items():
        w = field.widget
        cls = "input"
        if isinstance(w, forms.Textarea):
            cls = "textarea"
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            cls = "select"
        elif isinstance(w, forms.CheckboxInput):
            cls = "toggle-check"
        elif isinstance(w, QtyInput):
            for bound, attr in (("min_value", "data-min"), ("max_value", "data-max")):
                if getattr(field, bound, None) is not None:
                    w.attrs.setdefault(attr, str(getattr(field, bound)))
        existing = w.attrs.get("class", "")
        w.attrs["class"] = f"{existing} {cls}".strip()


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class SliderForm(StyledModelForm):
    class Meta:
        model = Slider
        fields = ["title", "subtitle", "badge", "image", "link_url", "order", "is_active"]


class ProductForm(StyledModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "brand", "condition", "price", "old_price", "storage", "color",
            "year", "condition_grade", "warranty", "short_desc", "description",
            "cover", "is_featured", "is_active", "order",
        ]
        field_classes = {"price": MoneyField, "old_price": MoneyField}
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class TestimonialForm(StyledModelForm):
    class Meta:
        model = Testimonial
        fields = ["name", "role", "rating", "comment", "avatar", "order", "is_active"]
        widgets = {"comment": forms.Textarea(attrs={"rows": 3})}


class FAQForm(StyledModelForm):
    class Meta:
        model = FAQ
        fields = ["question", "answer", "order", "is_active"]
        widgets = {"answer": forms.Textarea(attrs={"rows": 3})}


class BrandForm(StyledModelForm):
    class Meta:
        model = Brand
        fields = ["name", "logo", "order"]


class SiteSettingsForm(StyledModelForm):
    class Meta:
        model = SiteSettings
        exclude = []
        widgets = {
            "hero_subtitle": forms.Textarea(attrs={"rows": 2}),
            "footer_about": forms.Textarea(attrs={"rows": 3}),
            "maps_embed": forms.Textarea(attrs={"rows": 2}),
        }
