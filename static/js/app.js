/* Bayço Teknoloji — arayüz etkileşimleri */
(function () {
  "use strict";

  /* ---- Header scroll durumu ---- */
  function initHeader() {
    var header = document.querySelector(".site-header");
    if (!header) return;
    var onScroll = function () {
      header.classList.toggle("scrolled", window.scrollY > 24);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* ---- Scroll reveal ---- */
  function initReveal(root) {
    var els = (root || document).querySelectorAll(".reveal:not(.in)");
    if (!("IntersectionObserver" in window)) {
      els.forEach(function (el) { el.classList.add("in"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    els.forEach(function (el) { io.observe(el); });
  }

  /* ---- SSS akordeon ---- */
  function initFaq(root) {
    (root || document).querySelectorAll(".faq-q").forEach(function (q) {
      if (q.dataset.bound) return;
      q.dataset.bound = "1";
      q.addEventListener("click", function () {
        q.closest(".faq-item").classList.toggle("open");
      });
    });
  }

  /* ---- Hero cube swiper ---- */
  function initHeroCube() {
    var el = document.querySelector(".hero-cube .swiper");
    if (!el || typeof Swiper === "undefined" || el.dataset.bound) return;
    el.dataset.bound = "1";
    new Swiper(el, {
      effect: "cube",
      grabCursor: true,
      loop: true,
      speed: 900,
      autoplay: { delay: 3200, disableOnInteraction: false },
      cubeEffect: { shadow: true, slideShadows: true, shadowOffset: 24, shadowScale: 0.9 },
      pagination: { el: el.querySelector(".swiper-pagination"), clickable: true },
    });
  }

  /* ---- Genel galeri / yorum swiperları ---- */
  function initSwipers() {
    document.querySelectorAll("[data-swiper]").forEach(function (el) {
      if (el.dataset.bound || typeof Swiper === "undefined") return;
      el.dataset.bound = "1";
      var cfg = {};
      try { cfg = JSON.parse(el.dataset.swiper || "{}"); } catch (e) {}
      new Swiper(el, Object.assign({
        slidesPerView: 1,
        spaceBetween: 20,
        pagination: { el: el.querySelector(".swiper-pagination"), clickable: true },
      }, cfg));
    });
  }

  function initAll(root) {
    initReveal(root);
    initFaq(root);
    initHeroCube();
    initSwipers();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initHeader();
    initAll(document);
  });

  /* htmx ile gelen içerik için yeniden bağla */
  document.body.addEventListener("htmx:afterSwap", function (e) {
    initAll(e.target);
  });

  window.BaycoUI = { initAll: initAll };
})();
