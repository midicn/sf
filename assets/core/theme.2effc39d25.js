/* midicn · 明暗与导航交互（全站一份）
 * 系统默认；用户按过才写 midicn-theme。初始值由各页 <head> 的三行 bootstrap 先落，
 * 避免“先亮后暗”的闪屏；本脚本只负责按钮与持久化。
 * 图标由 CSS 按 [data-theme]/prefers-color-scheme 切换，不在 JS 里换 DOM。
 */
(function () {
  'use strict';
  var btn = document.getElementById('theme');
  if (!btn) return;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function current() {
    return document.documentElement.dataset.theme || (mq && mq.matches ? 'dark' : 'light');
  }
  function label() {
    var dark = current() === 'dark';
    var zh = dark ? '切换到浅色' : '切换到深色';
    var en = dark ? 'Switch to light mode' : 'Switch to dark mode';
    var value = document.documentElement.lang.indexOf('en') === 0 ? en : zh;
    btn.setAttribute('data-zh-label', zh);
    btn.setAttribute('data-en-label', en);
    btn.setAttribute('aria-label', value);
    btn.setAttribute('title', value);
    btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
  }
  btn.addEventListener('click', function () {
    var next = current() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('midicn-theme', next); } catch (e) {}
    // cookie 才能跨子域：midicn.com 各站切换时保持同一套明暗
    try {
      // 先清掉旧版遗留的 host-only cookie，避免同名两份互相遮挡
      document.cookie = 'midicn-theme=; path=/; max-age=0';
      document.cookie = 'midicn-theme=' + next +
        '; path=/; domain=.midicn.com; max-age=31536000; SameSite=Lax';
    } catch (e) {}
    label();
  });
  if (mq && mq.addEventListener) mq.addEventListener('change', label);
  if (window.MutationObserver) new MutationObserver(label).observe(
    document.documentElement, {attributes: true, attributeFilter: ['lang', 'data-theme']});
  label();
})();

/* Navigation, keyboard access and warm-up share the same implementation on all sites. */
(function () {
  'use strict';
  var button = document.getElementById('navmenu-btn');
  var panel = document.getElementById('navmenu-panel');
  if (button && panel) {
    function close(restoreFocus) {
      panel.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      if (restoreFocus) button.focus();
    }
    button.addEventListener('click', function () {
      panel.hidden = !panel.hidden;
      button.setAttribute('aria-expanded', String(!panel.hidden));
    });
    document.addEventListener('click', function (event) {
      if (!panel.hidden && !panel.contains(event.target) && !button.contains(event.target)) close(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !panel.hidden) close(true);
    });
    panel.addEventListener('click', function (event) {
      if (event.target.closest('a')) close(false);
    });
    document.addEventListener('focusin', function (event) {
      if (!panel.hidden && !panel.contains(event.target) && event.target !== button) close(false);
    });
  }
  var warmed = new Set();
  function warm(event) {
    var connection = navigator.connection;
    if (connection && (connection.saveData || /(^|-)2g$/.test(connection.effectiveType))) return;
    var anchor = event.target.closest && event.target.closest('a');
    if (!anchor || anchor.hasAttribute('download')) return;
    var url = new URL(anchor.href, location.href);
    // Only warm our own sites, never references, downloads or third-party services.
    if (url.protocol !== 'https:' || !/(^|\.)midicn\.com$/.test(url.hostname) ||
        url.origin === location.origin || url.search || url.hash ||
        /\.[a-z0-9]+$/i.test(url.pathname) || warmed.has(url.href) || warmed.size >= 8) return;
    warmed.add(url.href);
    fetch(url.href, {mode: 'no-cors', credentials: 'omit'}).catch(function () { warmed.delete(url.href); });
  }
  document.addEventListener('pointerover', warm, {passive: true});
  document.addEventListener('pointerdown', warm, {passive: true});
  document.addEventListener('focusin', warm);
  function register() {
    if ('serviceWorker' in navigator && location.protocol === 'https:') {
      navigator.serviceWorker.register('/sw.js', {updateViaCache: 'none'}).catch(function () {});
    }
  }
  if ('requestIdleCallback' in window) requestIdleCallback(register, {timeout: 4000});
  else setTimeout(register, 2500);
})();
