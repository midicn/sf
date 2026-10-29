/* midicn · 明暗切换（全站一份）
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
    btn.setAttribute('aria-label', dark ? '切换浅色' : '切换深色');
    btn.setAttribute('title', dark ? '切换到浅色' : '切换到深色');
  }
  btn.addEventListener('click', function () {
    var next = current() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('midicn-theme', next); } catch (e) {}
    label();
  });
  if (mq && mq.addEventListener) mq.addEventListener('change', label);
  label();
})();
