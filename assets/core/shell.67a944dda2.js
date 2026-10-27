/* midicn-lib 三站共享外壳脚本（lib / mid / zip）
 *
 * 职责：**只做各页自己没做的事**，保证三站交互一致。
 *   · 主题切换（#theme）
 *   · 语言切换（#lang）：按 data-zh / data-en 属性互换文案
 *
 * 关键约定：本脚本必须放在**页面自身脚本之后**（`</body>` 前一行）。
 * 因为页面若已自行绑定（如 lib 站的各页都有自己的 applyLang / setTheme），
 * 这里会检测 `btn.onclick` 已存在而**跳过**，避免重复绑定导致「点一下切两次＝没反应」。
 */
(function () {
  'use strict';

  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };

  /* ① 主题 —— 页面没绑过才接管 */
  var themeBtn = document.getElementById('theme');
  function setTheme(v) {
    document.documentElement.dataset.theme = v;
    store.set('midicn-theme', v);
  }
  if (themeBtn && !themeBtn.onclick) {
    setTheme(store.get('midicn-theme') || 'dark');
    themeBtn.onclick = function () {
      setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    };
  }

  /* ② 语言 —— 同上；按 data-zh / data-en 互换 */
  var langBtn = document.getElementById('lang');
  if (langBtn && !langBtn.onclick) {
    var LANG = store.get('midicn-lang') || 'zh';

    function applyLang() {
      document.documentElement.lang = LANG === 'zh' ? 'zh' : 'en';
      var nodes = document.querySelectorAll('[data-zh]');
      for (var i = 0; i < nodes.length; i++) {
        var v = nodes[i].getAttribute('data-' + LANG);
        if (v != null) nodes[i].innerHTML = v;
      }
      var phs = document.querySelectorAll('[data-ph-zh]');
      for (var j = 0; j < phs.length; j++) {
        var p = phs[j].getAttribute('data-ph-' + LANG);
        if (p != null) phs[j].placeholder = p;
      }
      langBtn.textContent = LANG === 'zh' ? 'EN' : '中';
    }

    applyLang();
    langBtn.onclick = function () {
      LANG = LANG === 'zh' ? 'en' : 'zh';
      store.set('midicn-lang', LANG);
      applyLang();
      // 通知页面重渲染（若页面订阅了该事件）
      try { document.dispatchEvent(new CustomEvent('midicn:lang', { detail: LANG })); } catch (e) {}
    };

    // 暴露给页面复用
    window.midicnShell = { get lang() { return LANG; }, applyLang: applyLang };
  }
})();
