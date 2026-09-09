/* Bayço stok tarayıcı — kamera (zxing-wasm) + HID okuyucu tek kanalda.
 *
 * Her iki kaynak da window.BaycoScan.emit() çağırır; bu da document üzerinde
 * tek bir "bayco:scan" olayı tetikler. Alpine bileşeni bir kez dinler.
 *
 * static/js/app.js panelde YÜKLENMEZ; bu dosya kendi başına çalışır.
 */
(function () {
  "use strict";

  var FORMATS = ["QRCode", "EAN13", "EAN8", "UPCA", "UPCE", "Code128", "Code39",
                 "ITF", "DataMatrix"];

  // Nişangâh (ROI) geçişi: kare zaten TAM çözünürlükte ve küçük bir dikdörtgen.
  // tryDownscale yalnızca çok iri barkodlarda işe yarar (eşik 500 px, faktör 3);
  // dar modüllü IMEI Code128'inde her karede boşa bir geçiş demektir. tryInvert
  // de perakende kutularında pratikte gereksiz.
  var ROI_OPTS = {
    formats: FORMATS,
    tryHarder: true, tryRotate: true, tryInvert: false, tryDownscale: false,
    maxNumberOfSymbols: 1, binarizer: "LocalAverage", textMode: "Plain"
  };
  // Emniyet supabı: nişangâhın DIŞINDA kalan barkodu da yakalar; bugünkü
  // davranışın birebir aynısı. Böylece değişiklik en kötü ihtimalle mevcut
  // başarı oranını korur, düşüremez. Kare burada küçültüldüğü için pahalı
  // seçenekler açık kalabilir.
  var FULL_OPTS = Object.assign({}, ROI_OPTS,
                                { tryInvert: true, tryDownscale: true });
  var FULL_EVERY = 6;   // 6 karede bir tam kare (12 fps'te saniyede ~2 kez)

  // minLineCount'a DOKUNULMAZ (varsayılan 2). Burası POS/stok sistemi; yanlış
  // okuma stoğu bozar. Hassasiyeti gevşeterek değil, PİKSEL VEREREK çözüyoruz.

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
        // capture: istenen yakalama genişliği (4:3). Küçük barkodun okunabilmesi
        // modül başına ~3 piksele bağlıdır ve 1280 bunun altında kalıyordu.
        // roiMax nişangâhı tavanladığı için 1920 üstüne çıkmak yalnızca video
        // çözme maliyeti ekler, decoder'a giden pikseli artırmaz.
        // roiMax = capture: varsayılan yakalamada nişangâh HİÇ küçültülmez.
        // roiMaxH yalnızca dikey KIRPMA sınırı — 1D barkodda önemli olan eksen
        // yataydır, 480 satırın üstü tarama satırı israfıdır ve dikey sınırı
        // ölçekleyerek uygulamak yatay çözünürlükten çalardı.
        c: Object.assign({ fps: 12, capture: 1920, roiMax: 1920, roiMaxH: 480,
                           sample: 720, dedupeMs: 2500, autostart: false },
                         cfg || {}),
        on: false, err: "", hint: "", ok: false, busyUi: false,
        torchable: false, torchOn: false, dark: false,
        res: "", lowRes: false,
        zoomable: false, zoomHw: false, zoom: 1, zoomMax: 1,
        focusable: false, fixedFocus: false, focusPt: null,
        cams: [], camId: localStorage.getItem("bayco.camId") || "",
        _zoomMin: 1, _zoomStep: 0.1, _adv: null, _refoc: 0,
        _rect: null, _period: 0, _ro: null, _onres: null, _frame: 0,
        _stream: null, _raf: 0, _busy: false, _last: "", _lastAt: 0,
        _audio: null, _cRoi: null, _xRoi: null, _cFull: null, _xFull: null,
        _vis: null, _hide: null, _armed: false, _disarm: null,
        _autoPaused: false,

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
          // Nişangâh ölçüsü yalnızca kutu BOYUTU değişince geçersizdir (yön
          // değişimi, tarayıcı çubuğunun gizlenmesi, kolon genişliği).
          // htmx swap'ları kutuyu yalnızca KAYDIRIR; matematik kutuya göreli
          // olduğu için kaydırma önemsizdir.
          if (window.ResizeObserver) {
            this._ro = new ResizeObserver(function () { self._rect = null; });
          } else {
            this._onres = function () { self._rect = null; };
            window.addEventListener("resize", this._onres);
            window.addEventListener("orientationchange", this._onres);
          }
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
          if (this._onres) {
            window.removeEventListener("resize", this._onres);
            window.removeEventListener("orientationchange", this._onres);
          }
          clearTimeout(this._refoc);
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

          // 4:3 İSTENİR, 16:9 DEĞİL. Telefon sensörü zaten 4:3'tür: 16:9
          // istemek sensörü üstten-alttan kırptırır, sonra önizleme kutusu
          // (aspect-ratio:4/3) object-cover ile sağdan-soldan kırpar — pikseli
          // İKİ KEZ atıyorduk ve kullanıcı o alanı görmediği hâlde decoder
          // tarıyordu. 4:3 hem sensörün tamamını verir hem kutuyla birebir
          // örtüşür. 'ideal' olduğu için desteklemeyen cihaz sessizce en
          // yakınına düşer, OverconstrainedError ÜRETMEZ.
          var base = { width: { ideal: this.c.capture },
                       height: { ideal: Math.round(this.c.capture * 3 / 4) } };
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
          var st = track.getSettings ? track.getSettings() : {};
          // İstenen çözünürlük her zaman verilmez. Düşük geldiyse küçük barkod
          // hiçbir ayarla okunmaz; kullanıcıya sebebini söylemek, sessizce
          // başarısız olmaktan iyidir.
          this.res = (st.width || 0) + "×" + (st.height || 0);
          this.lowRes = (st.width || 0) > 0 && st.width < 1280;
          // Torch iOS Safari'de uzun süre yoktu, 17.4+ ile geldi. Kod zaten
          // capability sürücülü: destekleyen cihazda buton kendiliğinden çıkar.
          this.torchable = !!caps.torch;

          // Sabit odaklı kamera (çoğu ultra-geniş) küçük barkodu ASLA
          // netleyemez. Hangi cihazın ultra-geniş olduğunu ÖNCEDEN bilemeyiz
          // (Android etiketleri "camera2 0, facing back" der, odak bilgisi
          // yoktur) — ama AÇILAN kamera odak kipi bildirmiyorsa söyleyebiliriz.
          var fm = caps.focusMode || [];
          this.fixedFocus = !!caps.focusMode && fm.indexOf("continuous") < 0 &&
                            fm.indexOf("single-shot") < 0;
          // Dokunarak odak pratikte YALNIZCA Chrome/Android; iOS'ta
          // pointsOfInterest yoktur, kontrol hiç gösterilmez.
          this.focusable = fm.indexOf("single-shot") >= 0 && !!caps.pointsOfInterest;

          // Zoom, küçük barkodun ASIL çözümü: kullanıcı telefonu yaklaştırmak
          // yerine 15-25 cm'de tutup yakınlaştırır. Çoğu telefonun minimum
          // odak mesafesi ~10 cm; altına inince görüntü BULANIR ve durum daha
          // kötü olur — "kamera odaklanmıyor" şikâyetinin kaynağı budur.
          if (caps.zoom && caps.zoom.max > (caps.zoom.min || 1)) {
            // Donanım zoom'u: gerçek sensör kırpması, ISP tam çözünürlükte
            // çalışır. 4× üstü barkodda işe yaramaz, sadece bulanıklığı büyütür.
            this.zoomHw = true;
            this._zoomMin = caps.zoom.min || 1;
            this._zoomStep = caps.zoom.step || 0.1;
            this.zoomMax = Math.min(caps.zoom.max, this._zoomMin * 4);
            this.zoomable = true;
          } else if ((st.width || 0) >= 1600) {
            // Dijital zoom SADECE yüksek çözünürlükte anlamlı: ROI'yi z'ye
            // bölerek kırptığımız için 1280'lik bir karede 2× zoom bugünkünden
            // DAHA AZ piksel bırakırdı. Kazanç piksel değil ERGONOMİ — barkod
            // ekranda büyük göründüğü için kullanıcı telefonu uzakta tutar.
            this.zoomHw = false;
            this._zoomMin = 1; this._zoomStep = 0.25; this.zoomMax = 2;
            this.zoomable = true;
          } else {
            // Sınırlar da sıfırlanmalı: zoom yapabilen bir kameradan
            // yapamayana geçilirse (pickCam) eski zoomMax kalır, setZoom
            // kayıtlı değeri kabul eder ve geri alınamayan bir CSS zoom'u
            // açık kalırdı.
            this.zoomable = false; this.zoomHw = false;
            this._zoomMin = 1; this.zoomMax = 1; this._zoomStep = 0.1;
          }
          await this.setZoom(+localStorage.getItem("bayco.zoom") || this._zoomMin,
                             false);
          try { await this._applyAdv({ focusMode: "continuous" }); }
          catch (e) { /* desteklemiyor */ }

          if (this._ro && this.$refs.box) this._ro.observe(this.$refs.box);
          this._rect = null;

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
          this.dark = false;
          this.zoomable = false; this.zoomHw = false; this.zoom = 1;
          this.fixedFocus = false; this.focusable = false;
          this.lowRes = false; this.res = "";
          clearTimeout(this._refoc);
          this.focusPt = null;
          this._adv = null;          // yeni stream → temiz kısıt kümesi
          if (this._ro) this._ro.disconnect();
          this._rect = null;
        },

        pickCam: async function (id) {
          this.camId = id;
          localStorage.setItem("bayco.camId", id);
          this.stop();
          await this.start();
        },

        /* applyConstraints kısıt kümesini EKLEMEZ, KOMPLE DEĞİŞTİRİR: yalnız
         * {torch:true} göndermek daha önce verilen focusMode:continuous'u
         * DÜŞÜRÜR — yani ışığı açan kullanıcı, tam da odağın en çok gerektiği
         * anda sürekli otomatik odağı kaybeder. Geçerli küme burada tutulur ve
         * her seferinde bütün olarak yeniden uygulanır.
         *
         * advanced[] içindeki HER SÖZLÜK "ya hep ya hiç" uygulanır; bu yüzden
         * her ayar AYRI sözlüktür. Odak kipi ile odak noktası yalnız birlikte
         * anlamlı olduğu için onlar birleşir, desteklenmezse diye kip tek
         * başına da bir kez daha gönderilir. */
        _applyAdv: async function (patch) {
          var t = this._stream && this._stream.getVideoTracks()[0];
          if (!t || !t.applyConstraints) return;
          var s = this._adv || (this._adv = {});
          // Reddedilen ayar kümede KALMAMALI: kalsaydı sonraki her çağrı onu
          // yeniden gönderir ve alâkasız bir ayar (örn. fener) yüzünden
          // reddedilirdi.
          var undo = {}, k;
          for (k in patch) { undo[k] = s[k]; }
          Object.assign(s, patch);
          var adv = [];
          if (s.focusMode) {
            if (s.pointsOfInterest) {
              adv.push({ focusMode: s.focusMode,
                         pointsOfInterest: s.pointsOfInterest });
            }
            adv.push({ focusMode: s.focusMode });
          }
          if (s.zoom != null) adv.push({ zoom: s.zoom });
          if (s.torch != null) adv.push({ torch: s.torch });
          try {
            await t.applyConstraints({ advanced: adv });
          } catch (e) {
            Object.assign(s, undo);
            throw e;
          }
        },

        toggleTorch: async function () {
          if (!this._stream) return;
          try {
            await this._applyAdv({ torch: !this.torchOn });
            this.torchOn = !this.torchOn;
          } catch (e) { this.torchable = false; }
        },

        // Tek arayüz, iki uygulama: donanım varsa sensörden kırpar (gerçek
        // çözünürlük kazancı), yoksa video CSS ile büyür ve _roi bunu geri
        // alır. Tercih kalıcıdır; dükkânda bir kez ayarlanır, her açılışta
        // geri gelir.
        setZoom: async function (z, save) {
          z = Math.max(this._zoomMin, Math.min(this.zoomMax, +z || 1));
          this.zoom = z;
          // Geri yüklerken KAYDETME: zoom yapamayan bir kamerada (webcam) z
          // 1'e kırpılır ve telefonda ayarlanmış tercihi silerdi.
          if (save !== false) {
            try { localStorage.setItem("bayco.zoom", String(z)); } catch (e) {}
          }
          if (!this.zoomHw) return;   // dijital: CSS + _roi() hallediyor
          try { await this._applyAdv({ zoom: z }); }
          catch (e) { this.zoomHw = false; this.zoomable = false; }
        },

        /* Dokunarak odak. POI birim koordinattadır (0..1) ve VİDEO karesine
         * göredir, ekrana göre değil: object-cover kırpması ve dijital zoom
         * geri alınmalı. */
        tapFocus: async function (ev) {
          if (!this.focusable || !this.on) return;
          var v = this.$refs.video, box = this.$refs.box;
          if (!v || !box || !v.videoWidth) return;
          var b = box.getBoundingClientRect();
          if (!b.width) return;
          var s = Math.max(b.width / v.videoWidth, b.height / v.videoHeight);
          var ox = (b.width - v.videoWidth * s) / 2;
          var oy = (b.height - v.videoHeight * s) / 2;
          var z = this.zoomHw ? 1 : (this.zoom || 1);
          var px = b.width / 2 + (ev.clientX - b.left - b.width / 2) / z;
          var py = b.height / 2 + (ev.clientY - b.top - b.height / 2) / z;
          var cl = function (n) { return Math.min(1, Math.max(0, n)); };
          var self = this;
          try {
            await this._applyAdv({ focusMode: "single-shot",
                                   pointsOfInterest: [
                                     { x: cl(((px - ox) / s) / v.videoWidth),
                                       y: cl(((py - oy) / s) / v.videoHeight) }] });
          } catch (e) { this.focusable = false; return; }
          // Halka kutunun İÇİNE çizilir ve kutu transform almaz: dokunuşun
          // ham konumu kullanılır, px/py'nin zoom'u geri alınmış hâli değil.
          this.focusPt = { x: ev.clientX - b.left, y: ev.clientY - b.top };
          setTimeout(function () { self.focusPt = null; }, 700);
          clearTimeout(this._refoc);
          // single-shot'ta KALINMAZ: kalırsa kullanıcı bir sonraki barkoda
          // geçtiğinde kamera bir daha hiç odaklanmaz.
          this._refoc = setTimeout(function () {
            self._applyAdv({ focusMode: "continuous", pointsOfInterest: null });
          }, 2500);
        },

        camLabel: function (cam, i) {
          var l = (cam.label || "").toLowerCase();
          var n = "Kamera " + (i + 1);
          if (/ultra|geniş açı|wide angle|0\.5/.test(l)) {
            return n + " — Ultra geniş (yakın odaklanmaz)";
          }
          if (/tele|telephoto|zoom/.test(l)) return n + " — Tele";
          if (/front|ön|user/.test(l)) return n + " — Ön";
          if (/back|arka|rear|environment/.test(l)) return n + " — Arka";
          return cam.label || n;
        },

        /* Nişangâhın ekrandaki yerini kutuya GÖRELİ olarak ölçer.
         *
         * Sabit oran KULLANILMAZ: nişangâh "inset-x-6 / h-24" ile, yani MUTLAK
         * piksellerle konumlanır — kapsayıcı genişledikçe oranı değişir
         * (telefonda %87, tablet kolonunda %93). Sabit oran bir cihazda doğru,
         * diğerinde yanlış olurdu ve kullanıcı çerçeveye getirdiği barkodun
         * neden okunmadığını anlayamazdı.
         *
         * Rect her karede değil, YALNIZCA kutu boyutu değişince okunur. */
        _measure: function () {
          var box = this.$refs.box, ret = this.$refs.reticle;
          if (!box || !ret) { this._rect = null; return; }
          var b = box.getBoundingClientRect(), r = ret.getBoundingClientRect();
          // x-show ile gizliyken tüm ölçüler 0'dır: ölçme, tam kareye düş.
          if (!b.width || !b.height || !r.width) { this._rect = null; return; }
          this._rect = { bw: b.width, bh: b.height,
                         rx: r.left - b.left, ry: r.top - b.top,
                         rw: r.width, rh: r.height };
        },

        /* Nişangâhı VİDEO PİKSELİNE çevirir.
         * Zincir: nişangâh → dijital zoom geri alınır → object-cover ölçeği
         * geri alınır → video pikseli.
         *
         * object-cover: video kutuyu DOLDURACAK şekilde büyütülür (s = max),
         * taşan kenarlar simetrik kırpılır. Kullanıcının GÖRMEDİĞİ o alanı
         * decoder eskiden tarıyordu. */
        _roi: function (vw, vh) {
          var m = this._rect;
          if (!m) return null;
          var s = Math.max(m.bw / vw, m.bh / vh);
          var ox = (m.bw - vw * s) / 2, oy = (m.bh - vh * s) / 2;
          var z = this.zoomHw ? 1 : (this.zoom || 1);
          var cx = m.bw / 2, cy = m.bh / 2;
          var sx = ((cx + (m.rx - cx) / z) - ox) / s;
          var sy = ((cy + (m.ry - cy) / z) - oy) / s;
          var sw = m.rw / (s * z), sh = m.rh / (s * z);
          // SESSİZ BÖLGE: 1D barkod iki YANINDA boşluk olmadan ÇÖZÜLMEZ.
          // Nişangâhı tam dolduran barkodu tam kırparsak okuma oranı DÜŞER;
          // yatay dolgu isteğe bağlı değil, zorunludur. Dikey dolgu yalnızca
          // nişan alma payı, o yüzden daha küçük.
          var px = sw * 0.12, py = sh * 0.18;
          sx -= px; sy -= py; sw += px * 2; sh += py * 2;
          // Dikey fazlalık ÖLÇEKLENEREK değil KIRPILARAK atılır: ölçeklemek
          // yatay çözünürlükten de çalardı. Kırpılan şey nişan alma payıdır,
          // sessiz bölge değil — o yatayda ve dokunulmuyor.
          if (sh > this.c.roiMaxH) {
            sy += (sh - this.c.roiMaxH) / 2; sh = this.c.roiMaxH;
          }
          if (sx < 0) { sw += sx; sx = 0; }
          if (sy < 0) { sh += sy; sy = 0; }
          if (sx + sw > vw) sw = vw - sx;
          if (sy + sh > vh) sh = vh - sy;
          if (sw < 32 || sh < 32) return null;
          return { sx: sx, sy: sy, sw: sw, sh: sh };
        },

        /* Kırpma + ölçekleme TEK drawImage ile. Kritik nokta: drawImage'in
         * maliyeti HEDEF boyutla orantılıdır, kaynakla değil (kırpma ve
         * ölçekleme GPU'da). Pahalı olan getImageData ve wasm çözme, ikisi de
         * hedef boyuta bağlı — bu yüzden ROI kırpması varken yakalamayı
         * 1920'ye çıkarmak neredeyse bedava. */
        _decode: function (v, roi) {
          var sx = roi ? roi.sx : 0, sy = roi ? roi.sy : 0;
          var sw = roi ? roi.sw : v.videoWidth;
          var sh = roi ? roi.sh : v.videoHeight;
          var cap = roi ? this.c.roiMax : this.c.sample;
          // ASLA büyütülmez: yapay piksel ZXing'e yardım etmez.
          var w = Math.min(cap, Math.round(sw));
          var h = Math.max(1, Math.round(sh * (w / sw)));
          var cv, cx;
          // İki ayrı yüzey: tek canvas'ı ROI ve tam kare arasında paylaştırmak
          // her geçişte yeniden boyutlandırma + yeniden ayırma demek olurdu.
          if (roi) {
            if (!this._cRoi) {
              this._cRoi = document.createElement("canvas");
              this._xRoi = this._cRoi.getContext("2d",
                                                 { willReadFrequently: true });
            }
            cv = this._cRoi; cx = this._xRoi;
          } else {
            if (!this._cFull) {
              this._cFull = document.createElement("canvas");
              this._xFull = this._cFull.getContext("2d",
                                                   { willReadFrequently: true });
            }
            cv = this._cFull; cx = this._xFull;
          }
          if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
          cx.drawImage(v, sx, sy, sw, sh, 0, 0, w, h);
          var data = cx.getImageData(0, 0, w, h);
          // Işık ölçümü decode bütçesinden çalmasın: saniyede ~1 kez yeter.
          // Faz 3'tür, 0 DEĞİL: 12'nin katları FULL_EVERY'nin (6) de katıdır,
          // orada roi null olur ve ölçüm hiç çalışmazdı.
          if (roi && this._frame % 12 === 3) this._light(data);
          return ZXingWASM.readBarcodesFromImageData(data,
                                                     roi ? ROI_OPTS : FULL_OPTS);
        },

        // Her 32. pikselin yeşil kanalı ≈ parlaklık. Torch parlak/laminasyonlu
        // etiketlerde parlama yapabildiği için OTOMATİK açılmaz, yalnızca
        // buton vurgulanır.
        _light: function (data) {
          var d = data.data, n = d.length, sum = 0, c = 0;
          for (var i = 1; i < n; i += 128) { sum += d[i]; c++; }
          var dark = c > 0 && (sum / c) < 55;
          if (dark !== this.dark) this.dark = dark;
        },

        _loop: function () {
          var self = this, v = this.$refs.video, prev = 0;
          this._frame = 0;
          var tick = async function (ts) {
            if (!self.on) return;
            self._raf = requestAnimationFrame(tick);
            if (ts - prev < self._period || self._busy) return;
            if (!v || v.readyState < 2 || !v.videoWidth) return;
            prev = ts; self._busy = true;
            var t0 = performance.now();
            try {
              if (!self._rect) self._measure();
              self._frame++;
              // Çoğu kare nişangâhı TAM çözünürlükte okur; her FULL_EVERY'de
              // bir tam kare taranır ki çerçeveyi ıskalayan barkod da yakalansın.
              var roi = (self._frame % FULL_EVERY)
                      ? self._roi(v.videoWidth, v.videoHeight) : null;
              var res = await self._decode(v, roi);
              if (res && res.length && res[0].text) self.hit(res[0].text);
            } catch (e) {
              /* kareyi atla */
            } finally {
              self._busy = false;
              // UYARLAMALI HIZ: ucuz bir Android'de tek çözme 150 ms sürebilir.
              // Sabit periyotta kuyruk büyür, video takılır, cihaz ısınır.
              // Periyot ölçülen süreye göre kendini ayarlar; hızlı cihaz tam
              // c.fps'e çıkar, yavaş cihaz kendini kısar.
              var dt = performance.now() - t0;
              self._period = Math.max(1000 / self.c.fps, dt * 1.6);
            }
          };
          this._period = 1000 / this.c.fps;
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
