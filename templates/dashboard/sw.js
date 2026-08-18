/* Bayço panel service worker — /sw.js (apps/dashboard/views.py:service_worker)
 *
 * HİÇBİR ŞEY ÖNBELLEĞE ALINMAZ. Bu bir kasa/stok paneli: önbellekten dönen
 * eski bir sayfa yanlış stok adedi, yanlış fiyat veya çoktan kapanmış bir fiş
 * gösterir. Bir barkod okutmasının "14 adet" demesi ile gerçeğin 3 olması
 * arasındaki fark, çevrimdışı çalışabilmenin değerinden çok daha pahalıdır.
 *
 * O hâlde bu dosya neden var? Chrome bir siteyi ancak fetch işleyicisi olan
 * bir service worker kayıtlıysa "kurulabilir" sayar ve beforeinstallprompt'u
 * o zaman tetikler. Buradaki işleyici yalnızca ağ hatasını yakalayıp anlamlı
 * bir sayfa gösterir — araya girip veri saklamaz.
 */

self.addEventListener("install", function () {
  // Bekleyen eski sürüm varsa hemen devral: panelde iki sekme açık kalması
  // olağan ve kullanıcı güncellemeyi beklemesin.
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

var OFFLINE = [
  '<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">',
  '<meta name="viewport" content="width=device-width, initial-scale=1">',
  "<title>Bağlantı yok</title><style>",
  "body{margin:0;min-height:100vh;display:grid;place-items:center;",
  "background:#150c22;color:#f4eefb;font-family:system-ui,sans-serif;padding:24px}",
  ".b{max-width:22rem;text-align:center}h1{font-size:1.25rem;margin:0 0 .5rem}",
  "p{color:#b9a9cf;line-height:1.5;margin:0 0 1.25rem}",
  "button{border:0;border-radius:999px;padding:12px 26px;color:#fff;font-size:1rem;",
  "background:linear-gradient(135deg,#7a3ea6,#b4357f 52%,#e23a48)}",
  "</style></head><body><div class=b><div style=font-size:2.5rem>📴</div>",
  "<h1>Bağlantı yok</h1><p>Panel sunucuya ulaşamıyor. Wi-Fi veya mobil veri ",
  "bağlantınızı kontrol edip tekrar deneyin.</p>",
  "<button onclick=location.reload()>Yeniden dene</button>",
  "</div></body></html>",
].join("");

self.addEventListener("fetch", function (event) {
  // Yalnızca sayfa gezinmeleri. Diğer her istek (htmx parçaları, statikler,
  // POST'lar) doğrudan ağa gider — respondWith çağrılmazsa tarayıcı isteği
  // kendi normal yolundan yürütür.
  if (event.request.mode !== "navigate") return;

  event.respondWith(
    fetch(event.request).catch(function () {
      return new Response(OFFLINE, {
        status: 503,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    })
  );
});
