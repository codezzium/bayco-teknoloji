/* Bayço panel — aranabilir seçim kutusu.
 *
 * select[data-combobox]: native <select> gizlenir, önüne bir arama kutusu
 *   çizilir. Değeri yine <select> gönderir; JS çalışmazsa alan düz seçim
 *   kutusu olarak kalır (apps.dashboard.forms.SearchableSelect). Arama Türkçe
 *   harfleri katlar ("sukru" → "Şükrü"; sunucudaki eşi apps/stock/utils.trfold)
 *   ve yazılan her kelimeyi seçeneğin etiketinde + data-search'ünde arar.
 *   data-hint (ör. telefon) sonuç satırında soluk gösterilir.
 *
 * bayco:created olayı: pop-up'ta kaydedilen kayıt (HX-Trigger ile gelir, bkz.
 *   apps.stock.views.base.created_response). detail.field id'li <select>'e
 *   seçenek eklenir ve seçilir; formun geri kalanına dokunulmaz.
 *   [data-created-field] düğmeleri aynı olayı sunucuya gitmeden tetikler
 *   (pop-up'taki "Mevcut kaydı seç").
 *
 * Liste mutlak konumlu DEĞİL, akış içinde açılır: .card overflow:hidden'dır
 * ve kartın kenarına taşan bir liste kesilirdi.
 *
 * Alpine'a bağlı değildir; htmx ile sonradan gelen içerikte de çalışır.
 */
(function () {
  "use strict";

  var LIMIT = 50;
  var FOLD = {
    "İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
    "Ü": "u", "ü": "u", "Ö": "o", "ö": "o", "Ç": "c", "ç": "c",
    "Â": "a", "â": "a", "Î": "i", "î": "i", "Û": "u", "û": "u"
  };

  // trfold ile aynı: katlama küçültmeden ÖNCE ("I".toLowerCase() "i" verir).
  function fold(text) {
    return String(text == null ? "" : text)
      .replace(/[İIıŞşĞğÜüÖöÇçÂâÎîÛû]/g, function (ch) { return FOLD[ch]; })
      .toLowerCase();
  }

  function haystack(option) {
    if (option._hay == null) {
      option._hay = fold(option.text + " " + (option.getAttribute("data-search") || ""));
    }
    return option._hay;
  }

  function matches(option, words) {
    var hay = haystack(option);
    for (var i = 0; i < words.length; i++) {
      if (hay.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function enhance(select) {
    if (select._combobox) return;

    var box = document.createElement("div");
    box.className = "combobox";
    var input = document.createElement("input");
    input.type = "text";
    input.className = "input";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.disabled = select.disabled;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    var list = document.createElement("ul");
    list.className = "combobox-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    if (select.id) {
      input.id = select.id + "_ara";
      list.id = select.id + "_liste";
      input.setAttribute("aria-controls", list.id);
      var label = document.querySelector('label[for="' + select.id + '"]');
      if (label) label.htmlFor = input.id;
    }
    // "— Kişi / firma seçin —" → "Kişi / firma seçin" (büyüteç ikonu CSS'te)
    var blank = select.querySelector('option[value=""]');
    input.placeholder = blank ? blank.text.replace(/^[\s—–-]+|[\s—–-]+$/g, "") : "Seçin";

    box.appendChild(input);
    box.appendChild(list);
    select.parentNode.insertBefore(box, select);
    select.hidden = true;  // gizli <select> yine gönderilir (disabled değil)

    var shown = [];
    var active = -1;

    function selectedLabel() {
      var option = select.options[select.selectedIndex];
      return option && option.value ? option.text : "";
    }

    // Görünür kutu her zaman <select>'in gerçek değerini yansıtır.
    function sync() { input.value = selectedLabel(); }

    function setActive(index) {
      var items = list.querySelectorAll(".combobox-option");
      if (items[active]) items[active].classList.remove("is-active");
      if (!items.length) {
        active = -1;
        input.removeAttribute("aria-activedescendant");
        return;
      }
      active = Math.max(0, Math.min(items.length - 1, index));
      items[active].classList.add("is-active");
      input.setAttribute("aria-activedescendant", items[active].id);
      items[active].scrollIntoView({ block: "nearest" });
    }

    function render(query) {
      var words = fold(query).split(/\s+/).filter(Boolean);
      var more = false;
      shown = [];
      for (var i = 0; i < select.options.length; i++) {
        var option = select.options[i];
        if (!option.value || (words.length && !matches(option, words))) continue;
        if (shown.length === LIMIT) { more = true; break; }
        shown.push(option);
      }
      list.innerHTML = "";
      active = -1;
      var start = 0;
      shown.forEach(function (option, index) {
        var item = document.createElement("li");
        item.className = "combobox-option";
        item.id = (list.id || "combobox") + "_" + index;
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", option.selected ? "true" : "false");
        item.textContent = option.text;
        var hint = option.getAttribute("data-hint");
        if (hint) {
          var small = document.createElement("span");
          small.className = "combobox-hint";
          small.textContent = hint;
          item.appendChild(small);
        }
        item.addEventListener("click", function () { choose(option); });
        list.appendChild(item);
        if (option.selected && !words.length) start = index;
      });
      if (!shown.length || more) {
        var note = document.createElement("li");
        note.className = "combobox-note";
        note.textContent = shown.length ? "İlk " + LIMIT + " sonuç gösteriliyor — aramayı daraltın."
                                        : "Sonuç yok. Listede yoksa yandaki düğmeyle ekleyin.";
        list.appendChild(note);
      }
      setActive(start);
    }

    function open() {
      if (!list.hidden) return;
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      render("");
    }

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    function choose(option) {
      if (select.value !== option.value) {
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      sync();
      close();
    }

    input.addEventListener("focus", function () {
      open();
      input.select();  // yazmaya başlamak mevcut etiketi siler
    });
    input.addEventListener("click", open);
    input.addEventListener("input", function () {
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      render(input.value);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (list.hidden) open();
        else setActive(active + (e.key === "ArrowDown" ? 1 : -1));
      } else if (e.key === "Enter") {
        // Enter hiçbir zaman arkadaki formu göndermez: burada yazılan arama metnidir.
        e.preventDefault();
        if (!list.hidden && shown[active]) choose(shown[active]);
      } else if (e.key === "Escape" && !list.hidden) {
        // Yalnızca listeyi kapatır; olay pop-up'a ulaşıp onu kapatmasın.
        e.preventDefault();
        e.stopPropagation();
        sync();
        close();
      }
    });
    // Yarım yazılmış metin değer olamaz: boşsa seçim temizlenir, değilse
    // kutu seçili kaydın adına geri döner.
    input.addEventListener("blur", function () {
      close();
      if (!input.value.trim() && select.value) {
        select.value = "";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      sync();
    });
    // Listeye (kaydırma çubuğu dahil) basmak kutunun odağını düşürmesin;
    // seçim click'te yapılır, böylece dokunmatikte kaydırmak seçim yapmaz.
    list.addEventListener("mousedown", function (e) { e.preventDefault(); });

    select._combobox = { sync: sync };
    sync();

    // htmx [autofocus]'u htmx:load'dan ÖNCE odaklar; o sırada görünen <select>
    // artık gizli olduğu için odak arama kutusuna devredilir (pop-up formları).
    if (select.hasAttribute("autofocus") || document.activeElement === select) {
      select.removeAttribute("autofocus");
      input.focus();
    }
  }

  function enhanceAll(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.matches && root.matches("select[data-combobox]")) enhance(root);
    var selects = root.querySelectorAll("select[data-combobox]");
    for (var i = 0; i < selects.length; i++) enhance(selects[i]);
  }

  document.addEventListener("DOMContentLoaded", function () { enhanceAll(document); });
  document.addEventListener("htmx:load", function (e) { enhanceAll(e.detail && e.detail.elt); });

  /* ------------------------------------------------------------------ */
  /* Pop-up'ta kaydedilen kaydı seçim kutusuna ekle                      */
  /* ------------------------------------------------------------------ */
  document.addEventListener("bayco:created", function (e) {
    var d = e.detail || {};
    var select = d.field ? document.getElementById(d.field) : null;
    if (!(select instanceof HTMLSelectElement) || d.value == null) return;
    var value = String(d.value);
    var option = null;
    for (var i = 0; i < select.options.length; i++) {
      if (select.options[i].value === value) { option = select.options[i]; break; }
    }
    if (!option) {
      option = new Option(d.label || value, value);
      if (d.search) option.setAttribute("data-search", d.search);
      if (d.hint) option.setAttribute("data-hint", d.hint);
      // Boş etiketin hemen altına: liste açıldığında yeni kayıt ilk sırada görünür.
      var first = select.options[0];
      select.add(option, first && !first.value ? 1 : 0);
    }
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    if (select._combobox) select._combobox.sync();
  });

  document.addEventListener("click", function (e) {
    var button = e.target.closest ? e.target.closest("[data-created-field]") : null;
    if (!button) return;
    button.dispatchEvent(new CustomEvent("bayco:created", {
      bubbles: true,
      detail: {
        field: button.getAttribute("data-created-field"),
        value: button.getAttribute("data-created-value"),
        label: button.getAttribute("data-created-label"),
        search: button.getAttribute("data-created-search"),
        hint: button.getAttribute("data-created-hint")
      }
    }));
  });
})();
