/*
  Shared JS utilities — copy-to-clipboard, tab switching, theme toggle,
  focus trap for modals, and the Live Value flash/staleness helper.
  Loaded once, used by every page. No page-specific logic lives here.
*/

/* ── Icon rendering ──
   Lucide is now loaded via <script defer> (perf pass, 2026-07-12) rather
   than a blocking <head> script, so it may not be ready yet when a page's
   own bottom inline script runs (inline scripts without src ignore defer
   and execute immediately during parsing, before deferred scripts fire).
   renderIcons() retries for a couple of frames instead of silently
   no-op'ing, so first paint never ships with blank icon slots. */
function renderIcons() {
  if (window.lucide) { lucide.createIcons(); return; }
  if (!renderIcons._tries) renderIcons._tries = 0;
  if (renderIcons._tries++ < 40) setTimeout(renderIcons, 25);
}

/* ── Auth-status cache invalidation ──
   The nav's session indicator (nav.html) caches /auth/status in
   sessionStorage for 45s to avoid refetching on every navigation. Call
   this immediately before any action that changes auth state (login,
   logout) so the next page load doesn't show stale session info. */
function invalidateAuthStatusCache() {
  try { sessionStorage.removeItem('zerodha_auth_status_cache'); } catch (e) {}
}

/* ── Theme ── */
(function () {
  var KEY = "zerodha_theme";
  function apply(theme) {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }
  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) {}
  apply(stored);
  window.ZTheme = {
    get: function () { return stored; },
    set: function (theme) {
      stored = theme;
      try { localStorage.setItem(KEY, theme); } catch (e) {}
      apply(theme);
      // Lets any page-specific code (e.g. trade.html's live chart, which
      // caches colors read via getComputedStyle) react to an in-app theme
      // change without polling. See trade.html's ztheme:change listener.
      window.dispatchEvent(new CustomEvent("ztheme:change", { detail: { theme: theme } }));
    },
    toggle: function () {
      var current = stored || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      window.ZTheme.set(current === "dark" ? "light" : "dark");
    },
  };
})();

/* ── Banner show/hide — one implementation, used by trade.html and
   positions.html (was byte-identical duplicated code in both before this
   consolidation). Expects an element with class="banner ..." — see
   .banner in components.css. ── */
function showBanner(id, cls, txt) {
  var e = document.getElementById(id);
  if (!e) return;
  e.className = "banner " + cls;
  e.textContent = txt;
}
function hideBanner(id) {
  var e = document.getElementById(id);
  if (!e) return;
  e.className = "banner hidden";
}

/* ── Money formatter — signed rupee amount, used by trade.html's live
   review panel and positions.html's P&L display. ── */
function fmtMoney(v) {
  var sign = v >= 0 ? "+" : "";
  return sign + "₹" + Math.round(Math.abs(v)).toLocaleString() * (v < 0 ? -1 : 1);
}

/* ── HTML-escape a string for safe interpolation into innerHTML. ── */
function escapeHtml(s) {
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* ── Copy to clipboard — one implementation, used by every copy button. ── */
function copyToClipboard(text, btnEl, labelDefault, labelOk) {
  labelDefault = labelDefault || "Copy";
  labelOk = labelOk || "Copied!";
  navigator.clipboard.writeText(text).then(function () {
    if (!btnEl) return;
    var prev = btnEl.textContent;
    btnEl.textContent = labelOk;
    btnEl.classList.add("copied");
    setTimeout(function () {
      btnEl.textContent = prev || labelDefault;
      btnEl.classList.remove("copied");
    }, 2000);
  }).catch(function () {
    if (btnEl) { btnEl.textContent = "Failed"; setTimeout(function () { btnEl.textContent = labelDefault; }, 2000); }
  });
}

/* ── Tab switcher — one implementation for any tab group.
   groupSelector: container to scope the query within (defaults to document).
   Usage: <button onclick="switchTab(this, 'panel-id')"> inside a container
   with [data-tab-group], and panels with matching [data-tab-panel]. ── */
function switchTab(btnEl, targetId) {
  var group = btnEl.closest("[data-tab-group]") || document;
  group.querySelectorAll("[data-tab-btn]").forEach(function (b) { b.classList.remove("on"); });
  group.querySelectorAll("[data-tab-panel]").forEach(function (p) { p.classList.remove("on"); });
  btnEl.classList.add("on");
  var panel = group.querySelector('[data-tab-panel="' + targetId + '"]');
  if (panel) panel.classList.add("on");
}

/* ── Live Value — brief flash + staleness dimming for any element that
   receives streamed updates. Call on every tick; call markStale()/
   markLive() to toggle the dimmed state independent of ticks. ── */
function flashValue(el) {
  if (!el) return;
  el.classList.remove("flash");
  // restart the animation even if it's already mid-flight
  void el.offsetWidth;
  el.classList.add("flash");
}
function setStale(el, isStale) {
  if (!el) return;
  el.classList.toggle("stale", !!isStale);
}

/* ── Modal / sheet open+close with focus trap and Escape-to-close.
   Usage: openModal('modifyBackdrop'), closeModal('modifyBackdrop'). ── */
var _modalReturnFocus = {};
function openModal(id) {
  var backdrop = document.getElementById(id);
  if (!backdrop) return;
  _modalReturnFocus[id] = document.activeElement;
  backdrop.classList.add("open");
  var focusable = backdrop.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  if (focusable.length) focusable[0].focus();

  function onKeydown(e) {
    if (e.key === "Escape") { closeModal(id); return; }
    if (e.key !== "Tab" || !focusable.length) return;
    var first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  backdrop._trapHandler = onKeydown;
  backdrop.addEventListener("keydown", onKeydown);
}
function closeModal(id) {
  var backdrop = document.getElementById(id);
  if (!backdrop) return;
  backdrop.classList.remove("open");
  if (backdrop._trapHandler) backdrop.removeEventListener("keydown", backdrop._trapHandler);
  var returnTo = _modalReturnFocus[id];
  if (returnTo && typeof returnTo.focus === "function") returnTo.focus();
}
document.addEventListener("click", function (e) {
  var backdrop = e.target.closest(".modal-backdrop");
  if (backdrop && e.target === backdrop) closeModal(backdrop.id);
});

/* ── Keyboard shortcut: "/" focuses the nearest [data-symbol-search]
   input, matching the pattern from Linear/Raycast/TradingView referenced
   in docs/design/PRODUCT_DESIGN.md §9. Ignored while already typing in a field. ── */
document.addEventListener("keydown", function (e) {
  if (e.key !== "/" ) return;
  var tag = (document.activeElement && document.activeElement.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  var target = document.querySelector("[data-symbol-search]");
  if (target) { e.preventDefault(); target.focus(); }
});
