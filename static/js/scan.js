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
  function registerScanner() {
    Alpine.data("baycoScanner", function (cfg) {
      return {
        c: Object.assign({ fps: 8, sample: 720, dedupeMs: 2500, autostart: false },
                         cfg || {}),
        on: false, err: "", hint: "", ok: false, busyUi: false,
        torchable: false, torchOn: false,
        cams: [], camId: localStorage.getItem("bayco.camId") || "",
        _stream: null, _raf: 0, _busy: false, _last: "", _lastAt: 0,
        _audio: null, _canvas: null, _ctx: null, _vis: null, _hide: null,
        _armed: false, _disarm: null, _autoPaused: false,

        init: function () {
          var self = this;
          // Mobilde sekme değişimi sürekli olur. Kamerayı bırakmak ZORUNLU
          // (iOS'ta turuncu gösterge yanık kalır), ama geri dönüldüğünde
          // otomatik açma tercihi açıksa kendiliğinden geri gelmeli.
          this._vis = function () {
            if (document.hidden) {
              if (self.on) { self._autoPaused = true; self.stop(); }
            } else if (self._autoPaused) {
              self._autoPaused = false;
              if (self.c.autostart) self.start();
            }
          };
          // pagehide'da document.hidden false olabilir — ayrı tutulur, yoksa
          // sayfadan çıkarken kamerayı yeniden açmaya çalışır.
          this._hide = function () { self.stop(); };
          document.addEventListener("visibilitychange", this._vis);
          window.addEventListener("pagehide", this._hide);
          // Sunucu yanıtı geldiğinde sesli/görsel geri bildirim
          this._scanned = function (e) {
            var ok = e.detail && e.detail.ok !== false;
            self.beep(ok);
          };
          document.body.addEventListener("bayco:scanned", this._scanned);
          if (this.c.autostart) this.start(true);
        },

        destroy: function () {
          document.removeEventListener("visibilitychange", this._vis);
          window.removeEventListener("pagehide", this._hide);
          document.body.removeEventListener("bayco:scanned", this._scanned);
          if (this._disarm) {
            document.removeEventListener("pointerdown", this._disarm, true);
            document.removeEventListener("touchstart", this._disarm, true);
          }
          this.stop();
        },

        start: async function (fromAuto) {
          this.err = ""; this.hint = "";
          // http://192.168.x.x üzerinde mediaDevices TANIMSIZDIR — "hata verir"
          // değil, nesne hiç yoktur. Bu yüzden önce varlığı kontrol edilir.
          if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this.err = "Kamera yalnızca güvenli bağlantıda çalışır. Şu anki " +
                       "adres: " + location.protocol + "//" + location.host +
                       " — panele https:// ile (alan adı üzerinden) girin. " +
                       "Bu sayfada barkod okuyucuyla okutabilir veya kodu elle " +
                       "yazabilirsiniz.";
            return;
          }
          // iOS: AudioContext kullanıcı dokunuşu İÇİNDE yaratılmalı
          try {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (AC && !this._audio) this._audio = new AC();
          } catch (e) { /* sesi olmayan cihaz */ }

          var base = { width: { ideal: 1280 }, height: { ideal: 720 } };
          var video = Object.assign({}, base);
          if (this.camId) video.deviceId = { exact: this.camId };
          else video.facingMode = { ideal: "environment" };

          try {
            this._stream = await navigator.mediaDevices.getUserMedia(
              { video: video, audio: false });
          } catch (e) {
            var name = e && e.name;
            // iOS her oturumda deviceId'leri döndürür; kayıtlı kimlik bir
            // sonraki gün geçersizdir ve exact kısıtı OverconstrainedError
            // verir. Kaydı at, arka kamerayla yeniden dene.
            if (this.camId &&
                (name === "OverconstrainedError" || name === "NotFoundError")) {
              this.forgetCam();
              var retry = Object.assign({}, base);
              retry.facingMode = { ideal: "environment" };
              try {
                this._stream = await navigator.mediaDevices.getUserMedia(
                  { video: retry, audio: false });
              } catch (e2) { this.fail(e2, fromAuto); return; }
            } else {
              this.fail(e, fromAuto); return;
            }
          }

          // on=true ÖNCE: kapsayıcı x-show ile gizliyken WebKit gizli <video>
          // için kare üretmez, canvas siyah kalır ve hiçbir barkod okunmaz.
          this.on = true;
          await this.$nextTick();

          var v = this.$refs.video;
          // iOS: playsinline + muted olmazsa tam ekran oynatıcı açılır ve
          // canvas siyah kare yakalar.
          v.setAttribute("playsinline", "");
          v.setAttribute("webkit-playsinline", "");
          v.muted = true;
          v.srcObject = this._stream;
          try { await v.play(); } catch (e) { /* yoksay */ }

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

        fail: function (e, fromAuto) {
          var name = (e && e.name) || "Error";
          if (name === "NotAllowedError") {
            // Sayfa açılışındaki otomatik denemede iOS Safari izni kullanıcı
            // etkileşimi olmadan reddeder — istem bile çıkmaz. İlk dokunuşta
            // sessizce yeniden dener; kullanıcı için "kendiliğinden açıldı"
            // gibi görünür.
            if (fromAuto) {
              this.hint = "Kamerayı başlatmak için ekrana bir kez dokunun.";
              this.armGesture();
              return;
            }
            this.err = "Kamera izni reddedildi. Tarayıcı ayarlarından izin " +
                       "verin. (Instagram/WhatsApp içi tarayıcı kamerayı " +
                       "engeller — bağlantıyı Safari veya Chrome'da açın.)";
          } else if (name === "NotFoundError" || name === "OverconstrainedError") {
            this.err = "Kamera bulunamadı.";
          } else if (name === "NotReadableError") {
            // Android'de tipik: kamerayı başka bir uygulama/sekme tutuyor.
            this.err = "Kamera başka bir uygulama tarafından kullanılıyor. " +
                       "Diğer sekmeleri ve kamera uygulamalarını kapatın.";
          } else {
            this.err = "Kamera açılamadı (" + name + ").";
          }
        },

        armGesture: function () {
          if (this._armed) return;
          this._armed = true;
          var self = this;
          var once = function () {
            document.removeEventListener("pointerdown", once, true);
            document.removeEventListener("touchstart", once, true);
            self._armed = false;
            self.hint = "";
            self.start();          // fromAuto YOK: bu artık gerçek bir dokunuş
          };
          document.addEventListener("pointerdown", once, true);
          document.addEventListener("touchstart", once, true);
          this._disarm = once;
        },

        forgetCam: function () {
          this.camId = "";
          try { localStorage.removeItem("bayco.camId"); } catch (e) {}
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
  }

  // Alpine bu dosyadan SONRA yüklenmelidir (bkz. dashboard/base.html). Yine de
  // sıra bozulursa bileşen sessizce ölmesin: Alpine zaten oradaysa doğrudan
  // kaydet, DOM'u yeniden başlat.
  if (window.Alpine && window.Alpine.data) {
    registerScanner();
    if (window.Alpine.initTree) {
      document.addEventListener("DOMContentLoaded", function () {
        var els = document.querySelectorAll('[x-data^="baycoScanner"]');
        for (var i = 0; i < els.length; i++) {
          if (!els[i]._x_dataStack) Alpine.initTree(els[i]);
        }
      });
    }
  } else {
    document.addEventListener("alpine:init", registerScanner);
  }

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
