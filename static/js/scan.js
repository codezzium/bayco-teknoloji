/* Bayço stok tarayıcı — kamera (zxing-wasm) + HID okuyucu tek kanalda.
 *
 * Her iki kaynak da window.BaycoScan.emit() çağırır; bu da document üzerinde
 * tek bir "bayco:scan" olayı tetikler. Alpine bileşeni bir kez dinler.
 *
 * static/js/app.js panelde YÜKLENMEZ; bu dosya kendi başına çalışır.
 */
(function () {
  "use strict";

  var READER_OPTS = {
    formats: ["QRCode", "EAN13", "EAN8", "UPCA", "UPCE", "Code128", "Code39",
              "ITF", "DataMatrix"],
    tryHarder: true, tryRotate: true, tryInvert: true, tryDownscale: true,
    maxNumberOfSymbols: 1, binarizer: "LocalAverage", textMode: "Plain"
  };

  function emit(code, source) {
    document.dispatchEvent(new CustomEvent("bayco:scan", {
      detail: { code: String(code).trim(), source: source }
    }));
  }
  window.BaycoScan = { emit: emit };

  /* ------------------------------------------------------------------ */
  /* Kamera                                                              */
  /* ------------------------------------------------------------------ */
  document.addEventListener("alpine:init", function () {
    Alpine.data("baycoScanner", function (cfg) {
      return {
        c: Object.assign({ fps: 8, sample: 720, dedupeMs: 2500, autostart: false },
                         cfg || {}),
        on: false, err: "", ok: false, busyUi: false,
        torchable: false, torchOn: false,
        cams: [], camId: localStorage.getItem("bayco.camId") || "",
        _stream: null, _raf: 0, _busy: false, _last: "", _lastAt: 0,
        _audio: null, _canvas: null, _ctx: null, _vis: null,

        init: function () {
          var self = this;
          this._vis = function () { if (document.hidden && self.on) self.stop(); };
          document.addEventListener("visibilitychange", this._vis);
          window.addEventListener("pagehide", this._vis);
          // Sunucu yanıtı geldiğinde sesli/görsel geri bildirim
          this._scanned = function (e) {
            var ok = e.detail && e.detail.ok !== false;
            self.beep(ok);
          };
          document.body.addEventListener("bayco:scanned", this._scanned);
          if (this.c.autostart) this.start();
        },

        destroy: function () {
          document.removeEventListener("visibilitychange", this._vis);
          window.removeEventListener("pagehide", this._vis);
          document.body.removeEventListener("bayco:scanned", this._scanned);
          this.stop();
        },

        start: async function () {
          this.err = "";
          // http://192.168.x.x üzerinde mediaDevices TANIMSIZDIR — "hata verir"
          // değil, nesne hiç yoktur. Bu yüzden önce varlığı kontrol edilir.
          if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this.err = "Kamera yalnızca güvenli bağlantıda çalışır " +
                       "(https:// veya localhost). Barkod okuyucu ile veya " +
                       "kodu elle yazarak devam edebilirsiniz.";
            return;
          }
          // iOS: AudioContext kullanıcı dokunuşu İÇİNDE yaratılmalı
          try {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (AC && !this._audio) this._audio = new AC();
          } catch (e) { /* sesi olmayan cihaz */ }

          var video = { width: { ideal: 1280 }, height: { ideal: 720 } };
          if (this.camId) video.deviceId = { exact: this.camId };
          else video.facingMode = { ideal: "environment" };

          try {
            this._stream = await navigator.mediaDevices.getUserMedia(
              { video: video, audio: false });
          } catch (e) {
            var name = e && e.name;
            if (name === "NotAllowedError") {
              this.err = "Kamera izni reddedildi. Tarayıcı ayarlarından izin " +
                         "verin. (Instagram/WhatsApp içi tarayıcı kamerayı " +
                         "engeller — bağlantıyı Safari veya Chrome'da açın.)";
            } else if (name === "NotFoundError") {
              this.err = "Kamera bulunamadı.";
            } else {
              this.err = "Kamera açılamadı (" + name + ").";
            }
            return;
          }

          var v = this.$refs.video;
          // iOS: playsinline + muted olmazsa tam ekran oynatıcı açılır ve
          // canvas siyah kare yakalar.
          v.setAttribute("playsinline", "");
          v.setAttribute("webkit-playsinline", "");
          v.muted = true;
          v.srcObject = this._stream;
          try { await v.play(); } catch (e) { /* yoksay */ }
          this.on = true;

          var track = this._stream.getVideoTracks()[0];
          var caps = track.getCapabilities ? track.getCapabilities() : {};
          this.torchable = !!caps.torch;      // iOS Safari'de DAİMA false
          try {
            await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] });
          } catch (e) { /* desteklemiyor */ }

          if (!this.cams.length) {
            try {
              var devices = await navigator.mediaDevices.enumerateDevices();
              this.cams = devices.filter(function (d) {
                return d.kind === "videoinput";
              });
            } catch (e) { /* yoksay */ }
          }
          if (window.ZXingWASM && ZXingWASM.prepareZXingModule) {
            try { await ZXingWASM.prepareZXingModule({ fireImmediately: true }); }
            catch (e) { /* zaten hazır */ }
          }
          this._loop();
        },

        stop: function () {
          this.on = false;
          if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
          if (this._stream) {
            this._stream.getTracks().forEach(function (t) { t.stop(); });
            this._stream = null;
          }
          var v = this.$refs.video;
          // Track durdurulmazsa iOS'ta turuncu kamera göstergesi yanık kalır
          // ve sonraki sayfa açılışında kamera kilitlenebilir.
          if (v) { try { v.pause(); } catch (e) {} v.srcObject = null; }
          this.torchOn = false;
        },

        pickCam: async function (id) {
          this.camId = id;
          localStorage.setItem("bayco.camId", id);
          this.stop();
          await this.start();
        },

        toggleTorch: async function () {
          if (!this._stream) return;
          var track = this._stream.getVideoTracks()[0];
          try {
            await track.applyConstraints({ advanced: [{ torch: !this.torchOn }] });
            this.torchOn = !this.torchOn;
          } catch (e) { this.torchable = false; }
        },

        _loop: function () {
          var self = this, v = this.$refs.video;
          var period = 1000 / this.c.fps, prev = 0;
          var tick = async function (ts) {
            if (!self.on) return;
            self._raf = requestAnimationFrame(tick);
            if (ts - prev < period || self._busy) return;
            if (!v || v.readyState < 2 || !v.videoWidth) return;
            prev = ts; self._busy = true;
            try {
              var w = Math.min(self.c.sample, v.videoWidth);
              var h = Math.round(v.videoHeight * (w / v.videoWidth));
              if (!self._canvas) {
                self._canvas = document.createElement("canvas");
                self._ctx = self._canvas.getContext("2d",
                                                    { willReadFrequently: true });
              }
              if (self._canvas.width !== w) {
                self._canvas.width = w; self._canvas.height = h;
              }
              self._ctx.drawImage(v, 0, 0, w, h);
              var data = self._ctx.getImageData(0, 0, w, h);
              var res = await ZXingWASM.readBarcodesFromImageData(data, READER_OPTS);
              if (res && res.length && res[0].text) self.hit(res[0].text);
            } catch (e) {
              /* kareyi atla */
            } finally {
              self._busy = false;
            }
          };
          this._raf = requestAnimationFrame(tick);
        },

        hit: function (code) {
          var now = Date.now();
          if (code === this._last && now - this._lastAt < this.c.dedupeMs) return;
          this._last = code; this._lastAt = now;
          // Yeşil flaş BİRİNCİL geri bildirimdir: iPhone'da fiziksel sessiz
          // anahtarı açıksa WebAudio hiç duyulmaz.
          this.ok = true;
          var self = this;
          setTimeout(function () { self.ok = false; }, 260);
          if (navigator.vibrate) navigator.vibrate(40);   // iOS'ta yok
          emit(code, "camera");
        },

        fire: function (code) {
          this.$refs.code.value = code;
          window.htmx.trigger(this.$refs.form, "scan");
        },

        beep: function (good) {
          if (!this._audio) return;
          if (this._audio.state === "suspended") this._audio.resume();
          var osc = this._audio.createOscillator();
          var gain = this._audio.createGain();
          osc.type = "square";
          osc.frequency.value = good ? 1180 : 320;
          gain.gain.value = 0.06;
          osc.connect(gain); gain.connect(this._audio.destination);
          osc.start();
          osc.stop(this._audio.currentTime + (good ? 0.07 : 0.18));
        }
      };
    });
  });

  /* ------------------------------------------------------------------ */
  /* HID okuyucu (USB / Bluetooth, klavye emülasyonlu)                   */
  /* ------------------------------------------------------------------ */
  (function hid() {
    var MAX_GAP = 45;   // ms — okuyucular 5-20 ms, insan > 60 ms
    var MIN_LEN = 6;    // BYC-000123 = 10, EAN-13 = 13, IMEI = 15
    var FLUSH = 120;    // Enter göndermeyen okuyucular için
    var buffer = "", startedAt = 0, lastAt = 0, timer = 0;
    var PUNCT = { Minus: "-", Slash: "/", Period: ".", Space: " " };

    // e.key DEĞİL e.code okunur: kasa bilgisayarı Türkçe-F düzenindeyse
    // e.key harfleri karıştırır ve "BYC" bozulur.
    function charOf(e) {
      var c = e.code || "";
      if (/^Digit\d$/.test(c)) return c[5];
      if (/^Numpad\d$/.test(c)) return c[6];
      if (/^Key[A-Z]$/.test(c)) return e.shiftKey ? c[3] : c[3].toLowerCase();
      if (PUNCT[c]) return PUNCT[c];
      return (e.key && e.key.length === 1) ? e.key : "";
    }
    function reset() { buffer = ""; startedAt = 0; }
    function looksLikeScanner() {
      return buffer.length >= MIN_LEN &&
             (lastAt - startedAt) / Math.max(1, buffer.length - 1) <= MAX_GAP;
    }
    function inEditable(el) {
      return !!(el && el.closest && el.closest(
        "input,textarea,select,[contenteditable=''],[contenteditable=true]"));
    }

    document.addEventListener("keydown", function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
      // Kullanıcı bir alana yazıyorsa HİÇ karışma. Bunun güzel yan etkisi:
      // manuel giriş kutusuna okutulursa karakterler oraya düşer ve Enter
      // formu normal yoldan gönderir — aynı endpoint'e.
      if (inEditable(e.target)) return;

      var now = e.timeStamp || Date.now();
      if (e.key === "Enter" || e.key === "Tab") {
        if (looksLikeScanner()) { e.preventDefault(); emit(buffer, "hid"); }
        reset(); clearTimeout(timer);
        return;
      }
      var ch = charOf(e);
      if (!ch) return;
      if (now - lastAt > MAX_GAP * 3) reset();   // yeni patlama
      if (!buffer) startedAt = now;
      buffer += ch; lastAt = now;
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (looksLikeScanner()) emit(buffer, "hid");
        reset();
      }, FLUSH);
    }, true);
  })();
})();
