#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""布局探针 —— 用真实浏览器量「有没有横向溢出 / 元素是否越界」。

为什么不用肉眼看截图：
  「横向溢出」是移动端最常见的硬伤，而它是**可判定**的：
  `documentElement.scrollWidth > clientWidth + 1` 即溢出，越界元素也能逐个列出来。
  量出来比看截图更硬，也能进 CI。

用法（**推荐同源模式**）
--------------------
    # 1) 在 sf/site 下起本地静态服务器
    python -m http.server 8792 --bind 127.0.0.1
    # 2) 同源测量（临时探针页写进站点目录，测完即删）
    python tools/_layout_probe.py --url http://127.0.0.1:8792/f1/ \
        --width 360 --serve-dir . --port 8792

⚠️ 三个会让人得出**假结论**的坑（都踩过，已全部处理）
--------------------------------------------------
1. **必须同源**。被测页若落在 temp 目录（`file://`），CSS 与 JS 都会失效 →
   量到的是「没排版的裸 HTML」，会报出根本不存在的溢出。→ `--serve-dir` 模式解决。
2. **本机代理会拦 127.0.0.1**（实测 502）。→ 取页面对 localhost 绕开代理，
   并给 Chrome 加 `--no-proxy-server`。
3. **探针必须自检**：量之前先确认样式真的生效（`.srow` 的 `display === 'flex'`）与
   条目真的渲染出来了。任一条不成立就**拒绝出结论** —— 否则「验收脚本本身」
   就成了假通过的来源。

另外：headless 的最小窗口宽是 518px，测真机 360px 要套一层同源 iframe 精确设定视口。
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (compatible; midicn-layout-probe/1.0)"

CHROME_CANDS = [
    Path.home() / "AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe",
    Path.home() / "AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe",
]

# ⚠️ 测量脚本**只有一份**，靠参数指向被测文档（本页 or iframe 内容）——
#    避免上次那种「改了一段、漏了另一段」造成的假结论。
MEASURE_JS = r"""
function midicnMeasure(doc, label) {
  var de = doc.documentElement, win = doc.defaultView;
  var over = [];
  doc.querySelectorAll('body *').forEach(function (el) {
    var r = el.getBoundingClientRect();
    if (r.width > 0 && (r.right > de.clientWidth + 1 || r.left < -1)) {
      var tag = el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '');
      if (over.length < 12) over.push(tag + '@' + Math.round(r.left) + '..' + Math.round(r.right));
    }
  });
  var row = doc.querySelector('.srow');
  var meta = doc.querySelector('.sr-meta');
  var nav = doc.querySelector('.nav, .kb-switch');
  return {
    url: label,
    viewport: de.clientWidth,
    scrollWidth: de.scrollWidth,
    hOverflow: de.scrollWidth - de.clientWidth,
    overEls: over,
    cssApplied: row ? win.getComputedStyle(row).display === 'flex' : false,
    rowDisplay: row ? win.getComputedStyle(row).display : '(无 .srow)',
    metaDisplay: meta ? win.getComputedStyle(meta).display : '(无 .sr-meta)',
    sheets: doc.styleSheets.length,
    navItems: doc.querySelectorAll('.nav a, .kb-switch a').length,
    navHeight: nav ? Math.round(nav.getBoundingClientRect().height) : 0,
    rows: doc.querySelectorAll('.srow').length,
    buttons: doc.querySelectorAll('.act').length,
    rowH: row ? Math.round(row.getBoundingClientRect().height) : 0,
    title: doc.title
  };
}
/* 等客户端渲染出条目再量（首页目录是 JS 渲染的），最多等 8 秒；
   到期仍无 .srow 也照量 —— 由 rows 字段如实反映，不猜。 */
function midicnWaitThen(doc, label, done) {
  var t0 = Date.now();
  (function poll() {
    if (doc.querySelector('.srow') || Date.now() - t0 > 8000) { done(midicnMeasure(doc, label)); return; }
    setTimeout(poll, 150);
  })();
}
"""

OUTER_TMPL = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0}iframe{border:0;display:block;width:%(w)dpx;height:%(h)dpx}
</style></head><body>
<iframe id="fr" src="%(inner)s"></iframe>
<script>
%(measure)s
window.addEventListener('load', function () {
  var fr = document.getElementById('fr');
  midicnWaitThen(fr.contentDocument, '%(label)s', function (r) {
    var x = document.createElement('div');
    x.id = 'PROBE_RESULT';
    x.textContent = JSON.stringify(r);
    document.body.appendChild(x);
  });
});
</script></body></html>"""

INNER_APPEND = """
<script>
%(measure)s
window.addEventListener('load', function () {
  midicnWaitThen(document, '%(label)s', function (r) {
    var x = document.createElement('div');
    x.id = 'PROBE_RESULT';
    x.textContent = JSON.stringify(r);
    document.body.appendChild(x);
  });
});
</script>
"""


def fetch(url: str, base: str, local: bool) -> str:
    opener = (urllib.request.build_opener(
        urllib.request.ProxyHandler({}),                      # ⚠️ localhost 绕开代理
        urllib.request.HTTPSHandler(context=CTX)) if local else
        urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX)))
    with opener.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    if not local:
        # 远端页在 file:// 下根相对/相对资源都会失配 → 一律改写为绝对地址。
        # ⚠️ 替换串必须带等号（`\1="`），否则会生成 `href"https://…` 这种畸形标签，
        #    于是 <link> 全部失效、样式表一张都不加载（踩过）。
        html = re.sub(r'(?:\.\./)+assets/', f"{base}/assets/", html)
        html = re.sub(r'(href|src)="assets/', r'\1="' + f"{base}/assets/", html)
        html = re.sub(r'(href|src)="/assets/', r'\1="' + f"{base}/assets/", html)
    return html


def chrome_bin() -> Path | None:
    for p in CHROME_CANDS:
        if p.exists():
            return p
    found = shutil.which("chrome") or shutil.which("chromium")
    return Path(found) if found else None


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--width", type=int, default=430)
    ap.add_argument("--height", type=int, default=1400)
    ap.add_argument("--serve-dir", default="", help="本地静态服务器根目录（同源模式）")
    ap.add_argument("--port", type=int, default=0, help="同源模式下的服务器端口")
    a = ap.parse_args(argv[1:])

    chrome = chrome_bin()
    if not chrome:
        print("✗ 找不到 chromium", file=sys.stderr)
        return 2

    local = bool(re.match(r'https?://(127\.0\.0\.1|localhost)', a.url))
    if local and not a.serve_dir:
        print("✗ 本地地址请同时给 --serve-dir（同源模式）", file=sys.stderr)
        return 2
    base = a.url.rsplit("/", 3)[0]
    html = fetch(a.url, base, local)

    tag = secrets.token_hex(4)
    root = Path(a.serve_dir) if a.serve_dir else Path(tempfile.mkdtemp())
    made: list[Path] = []
    try:
        if a.width < 500:
            # headless 最小窗口宽 518px → 套同源 iframe 精确设定视口
            inner = f"_probe_inner_{tag}.html"
            (root / inner).write_text(html, encoding="utf-8")
            made.append(root / inner)
            page = OUTER_TMPL % dict(w=a.width, h=a.height, inner=inner,
                                     measure=MEASURE_JS, label=a.url)
            extra = [f"--window-size={a.width + 40},{a.height + 120}"]
        else:
            page = html.replace("</body>", INNER_APPEND % dict(measure=MEASURE_JS, label=a.url))
            extra = [f"--window-size={a.width},{a.height}"]
        outer = f"_probe_{tag}.html"
        (root / outer).write_text(page, encoding="utf-8")
        made.append(root / outer)
        load = (f"http://127.0.0.1:{a.port}/{outer}" if a.serve_dir
                else (root / outer).as_uri())
        cmd = [str(chrome), "--headless=new", "--disable-gpu", "--no-proxy-server",
               "--hide-scrollbars", *extra,
               "--virtual-time-budget=12000", "--dump-dom", load]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=240).stdout or ""
    finally:
        for f in made:                       # 临时探针页用完即删（别留在站点目录里）
            try:
                f.unlink()
            except OSError:
                pass

    m = re.search(r'id="PROBE_RESULT">(\{.*?\})</div>', out, re.S)
    if not m:
        print("✗ 探针没回结果（页面可能 JS 报错）", file=sys.stderr)
        return 1
    r = json.loads(m.group(1))
    print("══ 布局探针 · 目标宽 %d ══" % a.width)
    print("  URL        %s" % r["url"])
    if r["rows"] == 0:
        print("  ✗ 页面没有条目行（渲染失败？）—— 结论无效")
        return 3
    if not r["cssApplied"]:
        print("  ✗ 样式没生效（.srow display=%s，应为 flex）—— 结论无效" % r["rowDisplay"])
        return 3
    print("  样式已生效 · 样式表 %d 张 · .sr-meta display=%s" % (r["sheets"], r["metaDisplay"]))
    print("  视口/scroll %d / %d → 横向溢出 **%d px**%s"
          % (r["viewport"], r["scrollWidth"], r["hOverflow"],
             " ✓" if r["hOverflow"] <= 1 else "  ✗ 有溢出！"))
    print("  导航 %d 项 · 高 %d px ｜ 条目 %d 行 · 行高 %d px ｜ 按钮 %d 个"
          % (r["navItems"], r["navHeight"], r["rows"], r["rowH"], r["buttons"]))
    if r["overEls"]:
        print("  ⚠️ 越界元素：")
        for e in r["overEls"]:
            print("     " + e)
    return 0 if r["hOverflow"] <= 1 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
