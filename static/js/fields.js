/* Bayço panel — tutar ve adet alanları.
 *
 * input[data-money="2"]: yazarken binlik noktası konur, virgül ondalıktır
 *   (18500 → 18.500, 18500,9 → 18.500,9). Klavyedeki nokta tuşu ondalık virgül
 *   yazar. Sunucu bu biçimi okur (apps/dashboard/numbers.py): "18.500" 18,5
 *   değil 18500'dür. data-money="0" ondalıksızdır.
 * input[data-qty]: iki yanına − / + düğmeleri eklenir (Niimbot adet sayacıyla
 *   aynı görünüm); sınırlar data-min / data-max. Yalnızca rakam kabul eder.
 *
 * Alpine'a bağlı değildir; htmx ile sonradan gelen içerikte de çalışır.
 * window.BaycoNum.parse / format Alpine ifadelerinde kullanılır (kasa ödemesi).
 */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ */
  /* Sayı biçimi (apps/dashboard/numbers.py ile aynı kurallar)           */
  /* ------------------------------------------------------------------ */
  function groupDigits(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  }

  // "18.500,90" → 18500.9; "150.90" (ham) → 150.9. Okunamazsa 0.
  function parse(text) {
    var s = String(text == null ? "" : text).replace(/[\s ₺]/g, "");
    if (s.indexOf(",") >= 0) s = s.replace(/\./g, "").replace(",", ".");
    else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, "");
    var n = parseFloat(s);
    return isFinite(n) ? n : 0;
  }

  // 18500 → "18.500", 150.9 → "150,90" (kuruş sıfırsa yazılmaz).
  function format(number, decimals) {
    if (decimals == null) decimals = 2;
    number = Number(number) || 0;
    var parts = Math.abs(number).toFixed(decimals).split(".");
    var out = groupDigits(parts[0]);
    if (parts[1] && /[1-9]/.test(parts[1])) out += "," + parts[1];
    return (number < 0 ? "-" : "") + out;
  }

  window.BaycoNum = { parse: parse, format: format };

  /* ------------------------------------------------------------------ */
  /* Tutar alanları                                                      */
  /* ------------------------------------------------------------------ */
  function decimalsOf(input) {
    return parseInt(input.getAttribute("data-money"), 10) || 0;
  }

  // Yazılan metni biçime sokar. Alandaki noktalar bizim koyduğumuz binlik
  // ayırıcılardır; kullanıcının bastığı nokta beforeinput'ta virgüle çevrilir.
  function formatTyped(text, decimals) {
    var comma = decimals > 0 ? text.indexOf(",") : -1;
    var whole = (comma >= 0 ? text.slice(0, comma) : text).replace(/\D/g, "").replace(/^0+(?=\d)/, "");
    if (comma < 0) return groupDigits(whole);
    var fraction = text.slice(comma + 1).replace(/\D/g, "").slice(0, decimals);
    return groupDigits(whole || "0") + "," + fraction;
  }

  function reformatMoney(input) {
    var decimals = decimalsOf(input);
    var old = input.value;
    var next = formatTyped(old, decimals);
    if (next === old) return;
    // İmleci, önündeki anlamlı karakter (rakam, virgül) sayısını koruyarak yerleştir.
    var caret = input.selectionStart == null ? old.length : input.selectionStart;
    var keep = old.slice(0, caret).replace(/[^\d,]/g, "").length;
    input.value = next;
    var pos = 0;
    for (var seen = 0; pos < next.length && seen < keep; pos++) {
      if (/[\d,]/.test(next[pos])) seen++;
    }
    if (document.activeElement === input) input.setSelectionRange(pos, pos);
  }

  // Nokta tuşu (ve mobil klavyedeki ondalık tuşu) ondalık virgül yazar.
  document.addEventListener("beforeinput", function (e) {
    var input = e.target;
    if (!(input instanceof HTMLInputElement) || !input.hasAttribute("data-money")) return;
    if (e.inputType !== "insertText" || (e.data !== "." && e.data !== ",")) return;
    e.preventDefault();
    var value = input.value, start = input.selectionStart, end = input.selectionEnd;
    var remaining = value.slice(0, start) + value.slice(end);
    if (!decimalsOf(input) || remaining.indexOf(",") >= 0) return;  // ondalık yok / zaten var
    input.value = value.slice(0, start) + "," + value.slice(end);
    input.setSelectionRange(start + 1, start + 1);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, true);

  /* ------------------------------------------------------------------ */
  /* Adet sayacı                                                         */
  /* ------------------------------------------------------------------ */
  var STEP_BUTTON = "btn btn-ghost btn-sm disabled:opacity-40 disabled:pointer-events-none";

  function bounds(input) {
    var min = parseInt(input.getAttribute("data-min"), 10);
    var max = parseInt(input.getAttribute("data-max"), 10);
    return { min: isNaN(min) ? 0 : min, max: isNaN(max) ? Infinity : max };
  }

  function syncQty(input) {
    var parts = input._qty;
    if (!parts) return;
    var b = bounds(input), n = parseInt(input.value, 10);
    parts.dec.disabled = input.disabled || input.readOnly || !(n > b.min);
    parts.inc.disabled = input.disabled || input.readOnly || !(isNaN(n) || n < b.max);
  }

  function stepQty(input, delta) {
    var b = bounds(input), n = parseInt(input.value, 10);
    var next = Math.min(b.max, Math.max(b.min, (isNaN(n) ? b.min : n) + delta));
    if (String(next) === input.value) return;
    input.value = String(next);
    // htmx (hx-trigger="change") ve Alpine (x-model) değişikliği görsün.
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function stepButton(label, text, onClick) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = STEP_BUTTON;
    button.style.cssText = "width:34px;height:34px;padding:0;flex:none";
    button.setAttribute("aria-label", label);
    button.textContent = text;
    button.addEventListener("click", onClick);
    return button;
  }

  function enhanceQty(input) {
    if (input._qty) return;
    var group = document.createElement("div");
    group.className = "flex items-center gap-1";
    group.setAttribute("role", "group");
    var dec = stepButton("Azalt", "−", function () { stepQty(input, -1); });
    var inc = stepButton("Arttır", "+", function () { stepQty(input, 1); });
    input.parentNode.insertBefore(group, input);
    group.appendChild(dec);
    group.appendChild(input);
    group.appendChild(inc);
    input.classList.add("text-center");
    input.style.minWidth = "0";
    if (!input.style.width) input.style.flex = "1 1 auto";  // form alanı: kalan genişlik
    input._qty = { dec: dec, inc: inc };
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        stepQty(input, e.key === "ArrowUp" ? 1 : -1);
      }
    });
    syncQty(input);
  }

  /* ------------------------------------------------------------------ */
  /* Olaylar                                                             */
  /* ------------------------------------------------------------------ */
  // Yakalama aşamasında: biçim, Alpine'ın x-model'i ve htmx değeri okumadan uygulanır.
  document.addEventListener("input", function (e) {
    var input = e.target;
    if (!(input instanceof HTMLInputElement)) return;
    if (input.hasAttribute("data-money")) {
      reformatMoney(input);
    } else if (input.hasAttribute("data-qty")) {
      var digits = input.value.replace(/\D/g, "");
      if (digits !== input.value) input.value = digits;
      syncQty(input);
    }
  }, true);

  document.addEventListener("change", function (e) {
    var input = e.target;
    if (!(input instanceof HTMLInputElement) || !input.hasAttribute("data-qty")) return;
    var b = bounds(input), n = parseInt(input.value, 10);
    if (!isNaN(n)) input.value = String(Math.min(b.max, Math.max(b.min, n)));
    syncQty(input);
  }, true);

  document.addEventListener("focusout", function (e) {
    var input = e.target;
    if (input instanceof HTMLInputElement && input.hasAttribute("data-money") &&
        /,$/.test(input.value)) {
      input.value = input.value.slice(0, -1);  // "18.500," → "18.500"
    }
  }, true);

  function enhance(root) {
    if (!root || !root.querySelectorAll) return;
    var money = root.querySelectorAll("input[data-money]");
    for (var i = 0; i < money.length; i++) {
      // Ham gelen değerleri ("18500.00") biçime sok; biçimliler aynen kalır.
      var input = money[i];
      if (input.value !== "" && !input._money) {
        input.value = format(parse(input.value), decimalsOf(input));
      }
      input._money = true;
    }
    var qty = root.querySelectorAll("input[data-qty]");
    for (var j = 0; j < qty.length; j++) enhanceQty(qty[j]);
  }

  document.addEventListener("DOMContentLoaded", function () { enhance(document); });
  // htmx ile yerleştirilen her yeni içerik (sepet, sayım listesi…)
  document.addEventListener("htmx:load", function (e) { enhance(e.detail && e.detail.elt); });
})();
