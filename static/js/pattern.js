/* Bayço panel — ekran deseni ızgarası (teknik servis kabul formu).
 *
 * templates/service/partials/pattern_input.html: telefonun kilit ekranındaki gibi
 *   parmakla ya da fareyle noktaları birleştirerek desen çizilir; değer gizli
 *   input'a "1-5-9-6" olarak yazılır (sunucudaki eşi apps/service/models.parse_pattern).
 *
 * Her yeni çizim deseni BAŞTAN başlatır (telefondaki gibi). Eskiden mevcut desene
 *   ekleniyordu; yeniden çizmek isteyenin çizgisi eski desenin son noktasından
 *   devam ediyor ve yanlış desen kaydediliyordu.
 *
 * Nokta yakalama SEGMENT üzerinden yapılır: tarayıcı hareketi aralıklı örnekler
 *   (hızlı çizimde iki örnek arası bir nokta aralığından uzun olabilir). Yalnızca
 *   örnek noktalarına bakılsaydı 1→2→6 hızlı çizildiğinde 2 atlanır, 1→6
 *   kaydedilirdi. İki örnek arasındaki doğru parçasına yakın her nokta, parça
 *   üzerindeki sırasıyla eklenir.
 * Telefon kilidindeki gibi iki noktanın tam ortasındaki nokta (1→3 için 2)
 *   henüz kullanılmadıysa desene kendiliğinden girer.
 *
 * Alpine'dan ÖNCE yüklenmelidir (alpine:init dinleyicisi; bkz. dashboard/base.html).
 */
(function () {
  "use strict";

  // viewBox birimi (300×300 ızgara, noktalar 100 aralıklı). 40 iken eğri çizen
  // parmak komşu noktayı da yakalıyordu; 30 at hamlesi (1→6) gibi çizgilerde
  // aradaki noktaları (2, 5: ~45 uzakta) yakalamaz.
  var HIT = 30;
  var MIDDLE = {
    "1-3": 2, "4-6": 5, "7-9": 8, "1-7": 4, "2-8": 5, "3-9": 6, "1-9": 5, "3-7": 5
  };

  function pos(n) {
    return { x: 50 + ((n - 1) % 3) * 100, y: 50 + Math.floor((n - 1) / 3) * 100 };
  }

  function middle(a, b) {
    return MIDDLE[a + "-" + b] || MIDDLE[b + "-" + a] || null;
  }

  function parse(value) {
    var seq = [];
    String(value || "").split("").forEach(function (ch) {
      var n = Number(ch);
      if (n >= 1 && n <= 9 && seq.indexOf(n) < 0) seq.push(n);
    });
    return seq;
  }

  /* a→b doğru parçasına HIT'ten yakın noktalar, parça üzerindeki sırasıyla. */
  function dotsOnSegment(a, b) {
    var dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
    var hits = [];
    for (var n = 1; n <= 9; n++) {
      var c = pos(n);
      var t = len2 ? ((c.x - a.x) * dx + (c.y - a.y) * dy) / len2 : 0;
      t = Math.max(0, Math.min(1, t));
      var px = a.x + t * dx, py = a.y + t * dy;
      if ((c.x - px) * (c.x - px) + (c.y - py) * (c.y - py) <= HIT * HIT) {
        hits.push({ n: n, t: t });
      }
    }
    hits.sort(function (p, q) { return p.t - q.t; });
    return hits.map(function (h) { return h.n; });
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("baycoPattern", function (initial) {
      return {
        seq: parse(initial),
        drawing: false,
        cursor: null,

        get value() { return this.seq.join("-"); },

        get line() {
          var points = this.seq.map(pos);
          if (this.drawing && this.cursor && points.length) points.push(this.cursor);
          return points.map(function (p) { return p.x + "," + p.y; }).join(" ");
        },

        get tooShort() { return this.seq.length > 0 && this.seq.length < 4; },

        on: function (n) { return this.seq.indexOf(n) >= 0; },
        order: function (n) {
          var i = this.seq.indexOf(n);
          return i < 0 ? "" : String(i + 1);
        },

        point: function (event) {
          var box = this.$refs.pad.getBoundingClientRect();
          return { x: (event.clientX - box.left) * 300 / box.width,
                   y: (event.clientY - box.top) * 300 / box.height };
        },

        add: function (n) {
          if (this.on(n)) return;
          var last = this.seq[this.seq.length - 1];
          var mid = last ? middle(last, n) : null;
          if (mid && !this.on(mid)) this.seq.push(mid);
          this.seq.push(n);
        },

        trace: function (from, to) {
          var self = this;
          dotsOnSegment(from, to).forEach(function (n) { self.add(n); });
        },

        down: function (event) {
          this.seq = [];
          this.drawing = true;
          // Parmak ızgaranın dışına taşsa da çizim sürsün.
          try { this.$refs.pad.setPointerCapture(event.pointerId); } catch (e) { /* eski tarayıcı */ }
          this.cursor = this.point(event);
          this.trace(this.cursor, this.cursor);
        },

        move: function (event) {
          if (!this.drawing) return;
          // Birleştirilmiş olaylar (Chrome) hızlı harekette ara örnekleri de verir.
          var events = event.getCoalescedEvents ? event.getCoalescedEvents() : [];
          if (!events.length) events = [event];
          for (var i = 0; i < events.length; i++) {
            var p = this.point(events[i]);
            this.trace(this.cursor, p);
            this.cursor = p;
          }
        },

        up: function () {
          this.drawing = false;
          this.cursor = null;
        },

        clear: function () { this.seq = []; }
      };
    });
  });
})();
