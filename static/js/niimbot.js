/* Bayço — Niimbot etiket yazıcısına tarayıcıdan baskı (Web Bluetooth).
 *
 * Etiket sunucuda çizilir (apps/stock/niimbot.py → 40×12 mm PNG). Bu dosya
 * PNG'yi alır, 270° döndürür ve Bluetooth ile yazıcıya gönderir; indirme yok,
 * sürücü yok, arka planda çalışan program yok.
 *
 * Protokol niim-agent'ın printer/client.py'sinden birebir taşındı ve D110_M
 * (firmware 301, protokol v4) üzerinde doğrulandı: komut sırası, bayt düzenleri
 * ve iki "yem" paketi. Değiştirmeden önce yazıcıda deneyin: yazıcı yanlış
 * diziye de "başarılı" deyip BOŞ etiket basıyor.
 *
 * Yalnızca Chrome / Edge (masaüstü ve Android). Safari ve iOS Web Bluetooth
 * desteklemez. Sayfa HTTPS (ya da localhost) üzerinden açılmalı.
 */
(function (root) {
  "use strict";

  var SERVICE = "e7810a71-73ae-499d-8c15-faa9aef0c3f2";
  var CHARACTERISTIC = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f";

  // [ad öneki, kafa genişliği (nokta), azami yoğunluk] — en uzun önek önce.
  var MODELS = [
    ["D11_H", 240, 3], ["D110", 240, 3], ["D11", 240, 3],
    ["B18", 384, 3], ["B21", 384, 5], ["B1", 384, 5],
  ];

  var C = {
    START_PRINT: 0x01, START_PAGE_PRINT: 0x03, SET_DIMENSION: 0x13,
    SET_QUANTITY: 0x15, SET_LABEL_DENSITY: 0x21, SET_LABEL_TYPE: 0x23,
    IMAGE_ROW: 0x85, GET_PRINT_STATUS: 0xA3, PRINTER_STATUS_DATA: 0xA5,
    CONNECT: 0xC1, HEARTBEAT: 0xDC, END_PAGE_PRINT: 0xE3, END_PRINT: 0xF3,
  };

  // ms. Testler rowDelay / statusPoll'u sıfırlar.
  var T = {
    command: 10000, rowDelay: 10, endPageRetry: 50, statusPoll: 100,
    printWait: 60000, idleDisconnect: 90000,
  };
  var DEFAULT_DENSITY = 3;

  function printerError(code, message) {
    var e = new Error(message);
    e.name = "PrinterError";
    e.code = code;  // "timeout" | "packet" | "unsupported" | "size" | "fetch"
    return e;
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function withTimeout(promise, ms, message) {
    var timer;
    return Promise.race([
      promise,
      new Promise(function (_, reject) {
        timer = setTimeout(function () { reject(printerError("timeout", message)); }, ms);
      }),
    ]).finally(function () { clearTimeout(timer); });
  }

  function hex(bytes) {
    return Array.from(bytes, function (b) { return ("0" + b.toString(16)).slice(-2); }).join(" ");
  }

  function hex2(n) { return ("0" + n.toString(16).toUpperCase()).slice(-2); }

  function u16(n) { return [(n >> 8) & 0xff, n & 0xff]; }

  /* ------------------------------------------------------------------ */
  /* Paket çerçevesi: 55 55 | tür | uzunluk | veri | checksum | AA AA    */
  /* ------------------------------------------------------------------ */
  function checksum(type, data) {
    var sum = type ^ data.length;
    for (var i = 0; i < data.length; i++) sum ^= data[i];
    return sum;
  }

  function encodePacket(type, data) {
    data = Array.from(data);
    var out = [0x55, 0x55, type, data.length].concat(data, [checksum(type, data), 0xAA, 0xAA]);
    if (type === C.CONNECT) out.unshift(0x03);  // tek istisna: CONNECT'in başına 0x03
    return Uint8Array.from(out);
  }

  function decodePacket(raw) {
    var n = raw.length;
    if (n < 7 || raw[0] !== 0x55 || raw[1] !== 0x55 || raw[n - 2] !== 0xAA || raw[n - 1] !== 0xAA) {
      throw printerError("packet", "Geçersiz paket: " + hex(raw));
    }
    var len = raw[3];
    if (n !== len + 7) throw printerError("packet", "Paket uzunluğu tutmuyor: " + hex(raw));
    var data = raw.slice(4, 4 + len);
    if (checksum(raw[2], data) !== raw[4 + len]) {
      throw printerError("packet", "Paket checksum hatası: " + hex(raw));
    }
    return { type: raw[2], data: data };
  }

  /* ------------------------------------------------------------------ */
  /* Görsel                                                              */
  /* ------------------------------------------------------------------ */

  // Saat yönünde 270° (= saat yönünün tersine 90°); PIL rotate(-270, expand=True).
  // bits[y * width + x] === 1 → siyah (basılır).
  function rotate270(bits, width, height) {
    var out = new Uint8Array(width * height);
    for (var y = 0; y < width; y++) {
      for (var x = 0; x < height; x++) out[y * height + x] = bits[x * width + (width - 1 - y)];
    }
    return { bits: out, width: height, height: width };
  }

  // Her satır bir IMAGE_ROW paketi. Satır baytları Python'daki
  // int(bits, 2).to_bytes(ceil(w / 8), "big") gibi sağa yaslı.
  function rowPackets(label) {
    var w = label.width, n = Math.ceil(w / 8), pad = n * 8 - w, out = [];
    for (var y = 0; y < label.height; y++) {
      var row = new Uint8Array(n);
      for (var x = 0; x < w; x++) {
        if (label.bits[y * w + x]) {
          var p = pad + x;
          row[p >> 3] |= 0x80 >> (p & 7);
        }
      }
      // satır no, 3 sayaç (hep 0), 1
      out.push(encodePacket(C.IMAGE_ROW, u16(y).concat([0, 0, 0, 1], Array.from(row))));
    }
    return out;
  }

  async function loadLabel(url) {
    var response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw printerError("fetch", "Etiket alınamadı (HTTP " + response.status + ")");
    var bitmap = await createImageBitmap(await response.blob());
    var canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    var ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0);
    var rgba = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    var bits = new Uint8Array(canvas.width * canvas.height);
    for (var i = 0; i < bits.length; i++) {
      bits[i] = rgba[i * 4] + rgba[i * 4 + 1] + rgba[i * 4 + 2] < 384 ? 1 : 0;
    }
    return rotate270(bits, canvas.width, canvas.height);
  }

  /* ------------------------------------------------------------------ */
  /* Yazıcı komutları (niim-agent printer/client.py)                     */
  /* ------------------------------------------------------------------ */
  function parseHeartbeat(d) {
    // Alanların yeri cevabın uzunluğuna göre değişiyor.
    switch (d.length) {
      case 20: return { closing: null, power: null, paper: d[18], rfid: d[19] };
      case 19: return { closing: d[15], power: d[16], paper: d[17], rfid: d[18] };
      case 13: return { closing: d[9], power: d[10], paper: d[11], rfid: d[12] };
      case 10: return { closing: d[8], power: d[9], paper: null, rfid: d[8] };
      case 9: return { closing: d[8], power: null, paper: null, rfid: null };
      default: return { closing: null, power: null, paper: null, rfid: null };
    }
  }

  function Client(transport) {
    this.t = transport;
    this.protocol = null;  // bağlantı boyunca önbellekte
  }

  Client.prototype.send = async function (code, data) {
    var raw;
    try {
      raw = await this.t.request(encodePacket(code, data), T.command);
    } catch (e) {
      if (e.code === "timeout") {
        throw printerError("timeout", "Yazıcı 0x" + hex2(code) + " komutuna cevap vermedi");
      }
      throw e;
    }
    return decodePacket(raw);
  };

  Client.prototype.write = function (code, data) {
    return this.t.write(encodePacket(code, data));
  };

  // Cevabın ilk baytı. Yazıcının "01" demesi bir şey kanıtlamaz.
  Client.prototype.command = async function (code, data) {
    var packet = await this.send(code, data);
    return packet.data.length > 0 && packet.data[0] !== 0;
  };

  // Cevap verisi; cevap yoksa ya da bozuksa boş.
  Client.prototype.optional = async function (code) {
    try {
      return (await this.send(code, [1])).data;
    } catch (e) {
      if (e.code === "timeout" || e.code === "packet") return new Uint8Array(0);
      throw e;
    }
  };

  Client.prototype.heartbeat = async function () {
    return parseHeartbeat((await this.send(C.HEARTBEAT, [1])).data);
  };

  Client.prototype.printStatus = async function () {
    var d = await this.optional(C.GET_PRINT_STATUS);
    return d.length < 4 ? null : { page: (d[0] << 8) | d[1], p1: d[2], p2: d[3] };
  };

  Client.prototype.detectProtocol = async function () {
    if (this.protocol === null) this.protocol = await this._detectProtocol();
    return this.protocol;
  };

  Client.prototype._detectProtocol = async function () {
    // İlk CONNECT'e cevap vermeyen firmware var; bir kez daha denenir.
    var reply = await this.optional(C.CONNECT);
    if (!reply.length) reply = await this.optional(C.CONNECT);
    if (!reply.length) return 1;
    if (reply[0] === 3) {  // yeni firmware, sürümünü kendisi bildiriyor
      var s = await this.optional(C.PRINTER_STATUS_DATA);
      if (s.length >= 13) {
        var fw = s[11] * 100 + s[12];
        if (fw >= 204 && fw < 300) return 3;
        if (fw >= 300 && fw < 302) return 4;  // D110_M fw 301 → 4 (doğrulandı)
        if (fw >= 302) return 5;
      }
    }
    return 1;  // reply[0] === 2: yeni firmware, eski protokol; ya da belirlenemedi
  };

  Client.prototype.print = async function (label, density, copies, onRows) {
    if ((await this.detectProtocol()) >= 4) return this._printV4(label, density, copies, onRows);
    return this._printV1(label, density, copies, onRows);
  };

  // D110_M ve yeni firmware. Donanımda doğrulandı; değerleri değiştirmeyin.
  Client.prototype._printV4 = async function (label, density, copies, onRows) {
    await this.command(C.SET_LABEL_TYPE, [1]);
    await this.command(C.SET_LABEL_DENSITY, [density]);
    // toplam sayfa, 4 ayrılmış bayt, sayfa rengi, hız, ayrılmış bayrak
    await this.command(C.START_PRINT, u16(copies).concat([0, 0, 0, 0, 0, 1, 0]));
    // Yem: yazıcı START_PRINT sonrasındaki ilk paketi yutuyor.
    await this.write(C.GET_PRINT_STATUS, [1]);
    // satır, sütun, kopya, kesim yüksekliği, kesim tipi, ayrılmış, hepsini gönder,
    // parça yüksekliği
    await this.command(C.SET_DIMENSION,
      u16(label.height).concat(u16(label.width), u16(copies), u16(0), [0, 0, 0], u16(0)));
    await this._sendRows(label, onRows);
    await this.command(C.END_PAGE_PRINT, [1]);
    await this._waitPrinted(function (page) { return page >= copies; });
    await this.command(C.END_PRINT, [1]);
    // Yem: END_PRINT sonrasındaki ilk paket de yutuluyor.
    await this.write(C.HEARTBEAT, [1]);
  };

  // Eski firmware. NiimPrintX'ten olduğu gibi; donanımda doğrulanmadı.
  Client.prototype._printV1 = async function (label, density, copies, onRows) {
    await this.command(C.SET_LABEL_DENSITY, [density]);
    await this.command(C.SET_LABEL_TYPE, [1]);
    await this.command(C.START_PRINT, [1]);
    await this.command(C.START_PAGE_PRINT, [1]);
    await this.command(C.SET_DIMENSION, u16(label.height).concat(u16(label.width)));
    await this.command(C.SET_QUANTITY, u16(copies));
    await this._sendRows(label, onRows);
    var deadline = Date.now() + T.printWait;
    while (!(await this.command(C.END_PAGE_PRINT, [1]))) {
      if (Date.now() >= deadline) throw printerError("timeout", "Yazıcı sayfa sonunu kabul etmedi");
      await sleep(T.endPageRetry);
    }
    await this._waitPrinted(function (page) { return page === copies; });
    await this.command(C.END_PRINT, [1]);
  };

  // Satırlar ATT onayı beklenmeden yazılır. Yanıtlı yazmada her satır bir
  // bağlantı aralığı bekliyor: 320 satır ~19 sn → yanıtsız ~3.6 sn. D110_M'de
  // donanımda doğrulandı (2026-09-25). 10 ms bekleme yazıcıyı zorlamamak için;
  // beklemesiz gönderim doğrulanmadı.
  Client.prototype._sendRows = async function (label, onRows) {
    var rows = rowPackets(label);
    for (var i = 0; i < rows.length; i++) {
      await this.t.writeWithoutResponse(rows[i]);
      if (onRows) onRows(i + 1, rows.length);
      if (T.rowDelay) await sleep(T.rowDelay);
    }
  };

  // Cevapsız ya da kısa tur hata sayılmaz; beklemeye devam edilir.
  Client.prototype._waitPrinted = async function (done) {
    var deadline = Date.now() + T.printWait;
    for (;;) {
      var status = await this.printStatus();
      if (status && done(status.page)) return;
      if (Date.now() >= deadline) {
        throw printerError("timeout", "Yazıcı baskının bittiğini 60 sn içinde bildirmedi");
      }
      if (T.statusPoll) await sleep(T.statusPoll);
    }
  };

  /* ------------------------------------------------------------------ */
  /* Web Bluetooth taşıyıcı                                              */
  /* ------------------------------------------------------------------ */
  function BleTransport(device) {
    this.device = device;
    this.char = null;
    this._pending = null;
  }

  BleTransport.prototype.connect = async function () {
    var server = await this.device.gatt.connect();
    var service = await server.getPrimaryService(SERVICE);
    this.char = await service.getCharacteristic(CHARACTERISTIC);
    this.char.addEventListener("characteristicvaluechanged", this._onValue.bind(this));
  };

  BleTransport.prototype._onValue = function (event) {
    var resolve = this._pending;
    if (!resolve) return;  // beklenmeyen bildirim (ör. yem cevabı) atılır
    this._pending = null;
    var v = event.target.value;
    resolve(new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength)));
  };

  // niim-agent'taki sıra: bildirimi aç → yaz → ilk bildirimi bekle → bildirimi kapat.
  // Yazma "yanıtlı": karakteristik "write" destekliyor ve doğrulanan yol bu.
  BleTransport.prototype.request = async function (bytes, timeout) {
    var self = this;
    try {
      var reply = new Promise(function (resolve) { self._pending = resolve; });
      await this.char.startNotifications();
      await this.char.writeValueWithResponse(bytes);
      return await withTimeout(reply, timeout, "Yazıcı cevap vermedi");
    } finally {
      this._pending = null;
      try { await this.char.stopNotifications(); } catch (e) { /* bağlantı koptuysa zaten kapalı */ }
    }
  };

  BleTransport.prototype.write = function (bytes) {
    return this.char.writeValueWithResponse(bytes);
  };

  BleTransport.prototype.writeWithoutResponse = function (bytes) {
    return this.char.writeValueWithoutResponse(bytes);
  };

  /* ------------------------------------------------------------------ */
  /* Oturum: yazıcıya tek kapı                                           */
  /* ------------------------------------------------------------------ */
  var state = { device: null, client: null, busy: false, idleTimer: null };

  function modelFor(name) {
    name = String(name || "").toUpperCase();
    for (var i = 0; i < MODELS.length; i++) {
      if (name.indexOf(MODELS[i][0]) === 0) {
        return { name: MODELS[i][0], width: MODELS[i][1], density: MODELS[i][2] };
      }
    }
    return { name: "?", width: 240, density: 3 };
  }

  function isSupported() {
    return !!(root.navigator && navigator.bluetooth && root.isSecureContext);
  }

  async function connect() {
    if (!isSupported()) {
      throw printerError("unsupported", "Bu tarayıcı Bluetooth ile yazdıramıyor. Chrome veya Edge kullanın.");
    }
    if (state.client && state.device.gatt.connected) return state.client;
    if (!state.device) {
      // Yazıcı seçim penceresi. Kullanıcı tıklamasının hemen ardından çağrılmalı.
      state.device = await navigator.bluetooth.requestDevice({
        filters: MODELS.map(function (m) { return { namePrefix: m[0] }; }),
        optionalServices: [SERVICE],
      });
      state.device.addEventListener("gattserverdisconnected", function () { state.client = null; });
    }
    var transport = new BleTransport(state.device);
    try {
      await transport.connect();
    } catch (e) {
      if (/unsupported device/i.test(e.message)) {
        // Bilgisayara daha önce eşleştirilmiş yazıcı, seçim penceresinde aynı adla
        // bir de "klasik Bluetooth" kaydı olarak çıkar; o kayıtla bağlanılamaz.
        state.device = null;
        throw printerError("classic",
          "Seçilen kayıt klasik Bluetooth. Tekrar basın ve listede aynı adlı diğer kaydı seçin. " +
          "Kalıcı çözüm: yazıcıyı bilgisayarın Bluetooth ayarlarından kaldırın (\"Bu Aygıtı Unut\").");
      }
      await sleep(500);  // ilk GATT bağlantısı ara sıra düşüyor; bir kez daha
      await transport.connect();
    }
    state.client = new Client(transport);
    return state.client;
  }

  function disconnect() {
    clearTimeout(state.idleTimer);
    state.client = null;
    if (state.device && state.device.gatt.connected) state.device.gatt.disconnect();
  }

  // Yazıcı kendi kendine uykuya geçiyor ve aynı anda tek bağlantı kabul ediyor;
  // boşta bağlantıyı asılı bırakma.
  function scheduleIdleDisconnect() {
    clearTimeout(state.idleTimer);
    state.idleTimer = setTimeout(disconnect, T.idleDisconnect);
  }

  async function printLabel(url, opts) {
    opts = opts || {};
    var say = opts.onStatus || function () {};
    var copies = Math.max(1, Math.min(10, parseInt(opts.copies, 10) || 1));
    if (state.busy) throw printerError("busy", "Önceki baskı sürüyor.");
    state.busy = true;
    clearTimeout(state.idleTimer);
    try {
      say("Yazıcıya bağlanılıyor…");
      var client = await connect();
      var started = Date.now();  // seçim penceresinde geçen süre sayılmaz
      var model = modelFor(state.device.name);

      say("Etiket hazırlanıyor…");
      var label = await loadLabel(url);
      if (label.width > model.width) {
        throw printerError("size", "Etiket genişliği " + label.width + " nokta; " +
                           model.name + " için sınır " + model.width + ".");
      }

      var battery = null;
      try {
        battery = (await client.heartbeat()).power;
      } catch (e) {
        if (e.code !== "timeout" && e.code !== "packet") throw e;
      }
      await client.detectProtocol();

      await client.print(label, Math.min(DEFAULT_DENSITY, model.density), copies,
        function (sent, total) { say("Gönderiliyor… %" + Math.round(sent * 100 / total)); });
      return { seconds: (Date.now() - started) / 1000, battery: battery,
               protocol: client.protocol, printer: state.device.name };
    } catch (e) {
      disconnect();  // bağlantı bozulmuş olabilir; sonraki baskı temiz başlar
      throw e;
    } finally {
      state.busy = false;
      if (state.client) scheduleIdleDisconnect();
    }
  }

  function describeError(e) {
    if (e && e.name === "NotFoundError") return "Yazıcı seçilmedi.";
    if (e && e.name === "SecurityError") return "Tarayıcı Bluetooth iznini vermedi; tekrar deneyin.";
    if (e && e.name === "NetworkError") {
      return "Yazıcıya bağlanılamadı. Açık ve yakında mı? Telefon uygulaması ya da " +
             "niim-agent yazıcıya bağlıysa kapatın.";
    }
    if (e && e.name === "PrinterError") return e.message;
    return "Baskı başarısız: " + (e && e.message ? e.message : e);
  }

  root.Niimbot = {
    printLabel: printLabel, disconnect: disconnect, isSupported: isSupported,
    describeError: describeError,
    // testler için
    _: { C: C, T: T, Client: Client, encodePacket: encodePacket, decodePacket: decodePacket,
         rotate270: rotate270, rowPackets: rowPackets, parseHeartbeat: parseHeartbeat,
         modelFor: modelFor },
  };

  if (typeof document === "undefined") return;

  root.addEventListener("pagehide", disconnect);

  function registerComponent() {
    Alpine.data("niimbotPrint", function (cfg) {
      return {
        url: cfg.url, copies: 1, busy: false, msg: "", err: false,
        supported: isSupported(),
        print: async function () {
          if (this.busy) return;
          var self = this;
          this.busy = true;
          this.err = false;
          try {
            var r = await printLabel(this.url, {
              copies: this.copies,
              onStatus: function (m) { self.msg = m; },
            });
            this.msg = "Basıldı (" + r.seconds.toFixed(0) + " sn" +
                       (r.battery !== null ? ", pil " + r.battery + "/4" : "") + ")";
          } catch (e) {
            this.err = true;
            this.msg = describeError(e);
            if (root.console) console.error("Niimbot:", e);
          } finally {
            this.busy = false;
          }
        },
      };
    });
  }

  if (root.Alpine) registerComponent();
  else document.addEventListener("alpine:init", registerComponent);
})(typeof window !== "undefined" ? window : globalThis);
