/* Bayço — POS58 fiş yazıcısına tarayıcıdan baskı (WebUSB).
 *
 * Fiş sunucuda çizilir ve ESC/POS'a çevrilir (apps/stock/pos58.py → fis.bin).
 * Bu dosya baytları alır ve USB ile yazıcıya olduğu gibi yazar; sürücü yok,
 * yazdırma penceresi yok. Kâğıt fiş boyu kadar ilerler.
 *
 * Yalnızca Chrome / Edge; sayfa HTTPS (ya da localhost) üzerinden açılmalı.
 * macOS'ta doğrudan çalışır (POS58, 2026-10-04). Windows yazıcıyı kendi
 * sürücüsüne bağlar ve tarayıcı USB arayüzünü alamaz: orada "Tarayıcıyla
 * Yazdır" kullanılır ya da yazıcının sürücüsü Zadig ile WinUSB yapılır.
 */
(function (root) {
  "use strict";

  var PRINTER_CLASS = 7;
  // Seçim penceresinde önce bu yazıcı, sonra her USB yazıcı.
  var FILTERS = [{ vendorId: 0x0416 }, { classCode: PRINTER_CLASS }];
  var CHUNK = 4096;
  // Kâğıt bitince ya da kapak açıkken yazıcı veri almayı bırakır; aktarım asılı kalır.
  var TRANSFER_TIMEOUT = 15000;

  var busy = false;

  function printerError(code, message) {
    var e = new Error(message);
    e.name = "PrinterError";
    e.code = code;  // "unsupported" | "busy" | "fetch" | "claim" | "transfer" | "timeout"
    return e;
  }

  function noop() {}

  function withTimeout(promise, ms, message) {
    var timer;
    return Promise.race([
      promise,
      new Promise(function (_, reject) {
        timer = setTimeout(function () { reject(printerError("timeout", message)); }, ms);
      }),
    ]).finally(function () { clearTimeout(timer); });
  }

  function isSupported() {
    return !!(root.navigator && navigator.usb && root.isSecureContext);
  }

  // Yazıcı sınıfındaki ilk arayüz ve onun bulk OUT ucu.
  function printerEndpoint(device) {
    var configs = device.configuration ? [device.configuration] : device.configurations;
    for (var c = 0; c < configs.length; c++) {
      var interfaces = configs[c].interfaces;
      for (var i = 0; i < interfaces.length; i++) {
        var alternates = interfaces[i].alternates;
        for (var a = 0; a < alternates.length; a++) {
          if (alternates[a].interfaceClass !== PRINTER_CLASS) continue;
          var out = alternates[a].endpoints.filter(function (e) {
            return e.direction === "out" && e.type === "bulk";
          })[0];
          if (out) {
            return { configuration: configs[c].configurationValue,
                     iface: interfaces[i].interfaceNumber,
                     alternate: alternates[a].alternateSetting,
                     endpoint: out.endpointNumber };
          }
        }
      }
    }
    return null;
  }

  // Bu sitede daha önce seçilmiş ve şu an takılı yazıcı; seçim penceresi açılmaz.
  async function pairedPrinter() {
    if (!isSupported()) return null;
    var devices = await navigator.usb.getDevices();
    return devices.filter(printerEndpoint)[0] || null;
  }

  async function send(device, bytes) {
    var target = printerEndpoint(device);
    if (!target) throw printerError("unsupported", "Seçilen aygıt bir USB yazıcı değil.");
    await device.open();
    try {
      if (!device.configuration ||
          device.configuration.configurationValue !== target.configuration) {
        await device.selectConfiguration(target.configuration);
      }
      try {
        await device.claimInterface(target.iface);
      } catch (e) {
        throw printerError("claim",
          "Yazıcının USB arayüzü başka bir sürücüde. Windows'ta \"Tarayıcıyla Yazdır\"ı kullanın.");
      }
      try {
        if (target.alternate) await device.selectAlternateInterface(target.iface, target.alternate);
        for (var i = 0; i < bytes.length; i += CHUNK) {
          var result = await withTimeout(
            device.transferOut(target.endpoint, bytes.subarray(i, i + CHUNK)),
            TRANSFER_TIMEOUT, "Yazıcı veri almıyor. Kâğıt bitmiş ya da kapak açık olabilir.");
          if (result.status !== "ok") {
            throw printerError("transfer", "Yazıcı veriyi kabul etmedi (" + result.status + ").");
          }
        }
      } finally {
        await device.releaseInterface(target.iface).catch(noop);
      }
    } finally {
      // Kapatmak asılı kalmış aktarımı da iptal eder; yazıcı diğer programlara açılır.
      await device.close().catch(noop);
    }
  }

  // device verilmezse önce eşleşmiş yazıcıya bakılır, yoksa seçim penceresi açılır
  // (o durumda kullanıcı tıklamasının hemen ardından çağrılmalı).
  async function printReceipt(url, device) {
    if (!isSupported()) {
      throw printerError("unsupported", "Bu tarayıcı USB ile yazdıramıyor. Chrome veya Edge kullanın.");
    }
    if (busy) throw printerError("busy", "Önceki baskı sürüyor.");
    busy = true;
    try {
      device = device || await pairedPrinter() ||
               await navigator.usb.requestDevice({ filters: FILTERS });
      var response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) throw printerError("fetch", "Fiş alınamadı (HTTP " + response.status + ")");
      await send(device, new Uint8Array(await response.arrayBuffer()));
    } finally {
      busy = false;
    }
  }

  function describeError(e) {
    if (e && e.name === "NotFoundError") return "Yazıcı seçilmedi ya da bağlantı koptu.";
    if (e && e.name === "SecurityError") return "Tarayıcı USB iznini vermedi; tekrar deneyin.";
    if (e && e.name === "NetworkError") return "Yazıcıya ulaşılamadı. USB kablosu takılı ve yazıcı açık mı?";
    if (e && e.name === "PrinterError") return e.message;
    return "Baskı başarısız: " + (e && e.message ? e.message : e);
  }

  root.Pos58 = {
    printReceipt: printReceipt, pairedPrinter: pairedPrinter, isSupported: isSupported,
    describeError: describeError,
    _: { printerEndpoint: printerEndpoint, FILTERS: FILTERS },  // testler için
  };

  if (typeof document === "undefined") return;

  // Fiş sayfası: <button data-pos58-print data-url="…fis.bin" [data-auto="1"]>
  //             <… data-pos58-status>
  function setup() {
    var button = document.querySelector("[data-pos58-print]");
    if (!button) return;
    var status = document.querySelector("[data-pos58-status]");

    function show(text, isError) {
      if (!status) return;
      status.textContent = text;
      status.classList.toggle("err", !!isError);
    }

    async function run(device) {
      if (busy) return;
      button.disabled = true;
      show("Yazıcıya gönderiliyor…");
      try {
        await printReceipt(button.dataset.url, device);
        show("Basıldı.");
      } catch (e) {
        show(describeError(e), true);
        if (root.console) console.error("POS58:", e);
      } finally {
        button.disabled = false;
      }
    }

    if (!isSupported()) {
      button.disabled = true;
      show("USB ile basmak için Chrome veya Edge gerekir; \"Tarayıcıyla Yazdır\"ı kullanın.");
    }
    button.addEventListener("click", function () { run(); });

    if (button.dataset.auto !== "1") return;
    // Satış biter bitmez: USB yazıcı eşleşmişse ona, yoksa eskisi gibi yazdırma penceresi.
    pairedPrinter().catch(function () { return null; }).then(function (device) {
      if (device) return run(device);
      var openDialog = function () { setTimeout(root.print, 250); };
      if (document.readyState === "complete") openDialog();
      else root.addEventListener("load", openDialog);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup);
  else setup();
})(typeof window !== "undefined" ? window : globalThis);
