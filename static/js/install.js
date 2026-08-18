/* "Uygulama Olarak Yükle" — panel kısayolunu cihaza kurar.
 *
 * İki ayrı dünya var ve tek bir düğmenin altında birleştiriliyor:
 *
 *   Chrome / Edge  — beforeinstallprompt olayı yakalanır, düğmeye basınca
 *                    tarayıcının KENDİ "Yüklensin mi?" kutusu açılır.
 *   Safari (iOS/mac) — programatik kurulum YOKTUR. Apple böyle bir API vermez;
 *                    yapılabilecek tek şey adımları göstermektir.
 *
 * Bu yüzden düğme "kur" değil "kurulumu başlat" düğmesidir: elinde bir
 * beforeinstallprompt varsa onu kullanır, yoksa tarayıcıya özel yönergeyi açar.
 *
 * beforeinstallprompt sayfa yüklenirken ÇOK ERKEN tetiklenebilir — Alpine
 * gövdenin en sonunda yüklendiği için burada değil, dashboard/base.html'in
 * <head> kısmındaki satır içi betikte yakalanıp window.BaycoPWA.prompt'a
 * konur. Bu dosya yalnızca onu okur.
 */
(function () {
  "use strict";

  function installed() {
    return window.matchMedia("(display-mode: standalone)").matches ||
           // iOS Safari display-mode'u desteklemez, kendi bayrağını kullanır.
           window.navigator.standalone === true;
  }

  function platform() {
    var ua = navigator.userAgent;
    // iPadOS 13+ kendini masaüstü Mac gibi tanıtır; dokunma noktası sayısı ayırır.
    if (/iPad|iPhone|iPod/.test(ua) ||
        (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) {
      return "ios";
    }
    if (/Firefox/.test(ua)) return "firefox";
    // Chrome, Edge, Opera hepsi UA'sında "Safari" taşır — önce onları ele.
    if (/Safari/.test(ua) && !/Chrome|Chromium|Edg|OPR|Android/.test(ua)) {
      return "safari";
    }
    return "chromium";
  }

  function guide() {
    if (!window.isSecureContext) {
      return {
        title: "Önce güvenli bağlantı gerekiyor",
        steps: [
          "Kısayol yalnızca https:// ile açılan adreslerde kurulabilir.",
          "Şu anki adres: " + location.protocol + "//" + location.host,
          "Paneli alan adı üzerinden (https://) açıp tekrar deneyin.",
        ],
      };
    }
    switch (platform()) {
      case "ios":
        return {
          title: "iPhone / iPad — Safari",
          steps: [
            "Alt çubuktaki Paylaş simgesine dokunun (kutudan yukarı çıkan ok).",
            "Listeyi aşağı kaydırıp “Ana Ekrana Ekle”yi seçin.",
            "Sağ üstteki “Ekle”ye dokunun; simge ana ekranda belirir.",
            "iOS bu adımı otomatikleştirmeye izin vermez — Safari'de hiçbir " +
            "site kurulumu kendi başlatamaz.",
          ],
        };
      case "safari":
        return {
          title: "Mac — Safari",
          steps: [
            "Menü çubuğundan Dosya → “Dock'a Ekle”yi seçin. (Safari 17 ve üzeri)",
            "Adı onaylayıp Ekle deyin; uygulama Dock'a yerleşir.",
          ],
        };
      case "firefox":
        return {
          title: "Firefox",
          steps: [
            "Firefox masaüstünde site kurulumunu desteklemiyor.",
            "Paneli Chrome, Edge veya Safari ile açıp tekrar deneyin.",
            "Android Firefox'ta ⋮ menüsündeki “Uygulama olarak yükle” çalışır.",
          ],
        };
      default:
        return {
          title: "Chrome / Edge",
          steps: [
            "Adres çubuğunun sağındaki yükleme simgesine tıklayın.",
            "Görünmüyorsa ⋮ menüsü → “Yayınla, kaydet ve paylaş” → " +
            "“Sayfayı uygulama olarak yükle”.",
            "Uygulama zaten kuruluysa tarayıcı yeniden kurmayı önermez.",
          ],
        };
    }
  }

  function register() {
    Alpine.data("baycoInstall", function () {
      return {
        show: false, help: false, busy: false, title: "", steps: [],

        init: function () {
          if (installed()) return;      // kurulu — düğme hiç görünmesin
          this.show = true;
          var self = this;
          window.addEventListener("appinstalled", function () {
            self.show = false;
            self.help = false;
          });
        },

        start: async function () {
          var deferred = window.BaycoPWA && window.BaycoPWA.prompt;
          if (!deferred) { this.openHelp(); return; }
          this.busy = true;
          try {
            deferred.prompt();
            var choice = await deferred.userChoice;
            // Olay tek kullanımlıktır; ikinci prompt() çağrısı hata verir.
            window.BaycoPWA.prompt = null;
            if (choice && choice.outcome === "accepted") this.show = false;
          } catch (e) {
            this.openHelp();
          } finally {
            this.busy = false;
          }
        },

        openHelp: function () {
          var g = guide();
          this.title = g.title;
          this.steps = g.steps;
          this.help = true;
        },
      };
    });
  }

  // Alpine bu dosyadan SONRA yüklenir (bkz. dashboard/base.html). Sıra bozulup
  // Alpine önce başlarsa bileşen sessizce kaybolmasın.
  if (window.Alpine && window.Alpine.data) register();
  else document.addEventListener("alpine:init", register);

  /* Service worker — kurulabilirliğin ön şartı. Sayfa yüklendikten sonra
     kaydedilir ki ilk boyamayla kaynak yarışına girmesin. */
  window.addEventListener("load", function () {
    var cfg = window.BaycoPWA;
    if (!cfg || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register(cfg.sw, { scope: cfg.scope })
      .catch(function () {
        // http:// üzerinde veya gizli pencerede beklenen bir hata; düğme yine
        // çalışır, yalnızca yönerge kipine düşer.
      });
  });
})();
