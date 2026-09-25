#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音色站（sf.midicn.com）**发布前置检查** —— 六关，红灯不可绕过。

设计：与数据三站同一套纪律（参照 `lib/library/tools/preflight.py` 与内核 `kb_preflight.py`），
但检查项按**本站的独有风险**裁剪 —— 这里最容易出错的是**许可**，不是排版。

六关
----
  ① 数据一致性   data/soundfonts.json 必须与台账**同源可复现**（跑 gen_catalog.py --check）
  ② 许可红线     F4 一条都不许出现在目录里；F3 不许有下载直链；「存疑」不许逐条列出；
                 托管直链必须只出现在 F1/F2
  ③ 外壳一致性   header/footer 两页逐字相同 · 导航顺序固定为 7 项（数据四站）· shell.js 与 lib 真源哈希相同
  ④ 死链        站内相对引用（assets/ data/ 页面）全部可达；产物必备文件在位
  ⑤ 元数据      title / description / canonical / og / twitter / JSON-LD / robots / sitemap / manifest
  ⑥ 双语与表述  data-zh / data-en 成对；无 TODO 残留；台湾/香港/澳门必须带「中国」前缀

用法
  python tools/preflight.py            # 全跑
  python tools/preflight.py --quiet
退出码：0 = 全绿；2 = 有红灯
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # sf/site/tools
SITE = HERE.parent                              # sf/site
MIDI = HERE.parents[2]                          # 工作区根（sf/site/tools → midi）
LEDGER = MIDI / "lib" / "work" / "docs" / "soundfonts.json"
LIB_SHELL = MIDI / "lib" / "site" / "assets" / "shell.js"
PY = sys.executable

# 统一导航的**唯一真源**是 `_apply_site_shell.py` 的 NAV —— 这里只做「产物 == 期望」的对账。
# ⚠️ 2026-09-26 sf 进全站导航后，数据四站（lib/mid/zip/sf）连号排在最前，再是 lib 的站内页。
NAV_EXPECT = [
    "https://lib.midicn.com/", "https://mid.midicn.com/", "https://zip.midicn.com/",
    "https://sf.midicn.com/",
    "https://lib.midicn.com/sources.html", "https://lib.midicn.com/lyrics.html",
    "https://lib.midicn.com/licenses.html",
]
RE_HEADER = re.compile(r'<header>.*?</header>', re.S)
RE_FOOTER = re.compile(r'<footer>.*?</footer>', re.S)
RE_NAV = re.compile(r'<nav class="nav"[^>]*>(.*?)</nav>', re.S)
RE_HREF = re.compile(r'href="([^"]+)"')
GEO = {
    r'(?<!中国)台湾': '台湾 → 应写「中国台湾」',
    r'(?<!中国)香港': '香港 → 应写「中国香港」',
    r'(?<!中国)澳门': '澳门 → 应写「中国澳门」',
}
WRITING_MARKS = re.compile(r'\b(TODO|FIXME|XXX|WIP)\b|待补|待写|此处省略|\?\?\?')


class Rep:
    def __init__(self):
        self.items: list[tuple[int, bool, str]] = []

    def add(self, gate: int, msg: str, severe: bool = True):
        self.items.append((gate, severe, msg))

    def ok(self, gate: int, msg: str):
        self.items.append((gate, False, '✓ ' + msg))

    @property
    def errors(self):
        return [x for x in self.items if x[1]]


# ── 关 1 · 数据一致性 ──────────────────────────────────────────────────
def gate1(rep: Rep):
    if not LEDGER.exists():
        rep.add(1, '台账缺失：%s' % LEDGER)
        return None
    led = json.loads(LEDGER.read_text(encoding='utf-8'))
    out = SITE / 'data' / 'soundfonts.json'
    if not out.exists():
        rep.add(1, '站点数据缺失：data/soundfonts.json（先跑 tools/gen_catalog.py）')
        return led
    r = subprocess.run([PY, str(HERE / 'gen_catalog.py'), '--check'],
                       capture_output=True, text=True, cwd=str(SITE))
    if r.returncode != 0:
        rep.add(1, '站点数据与台账不同步 —— 重跑 tools/gen_catalog.py（%s）'
                % (r.stdout.strip().splitlines()[-1:] or [''])[0])
    else:
        rep.ok(1, 'data/soundfonts.json 与台账同源可复现')
    r2 = subprocess.run([PY, str(HERE / 'gen_pages.py'), '--check'],
                        capture_output=True, text=True, cwd=str(SITE))
    if r2.returncode != 0:
        rep.add(1, '专区页与台账不同步 —— 重跑 tools/gen_pages.py（%s）'
                % (r2.stdout.strip().splitlines()[-1:] or [''])[0])
    else:
        rep.ok(1, '专区页（f2 / ethnic）与台账同源可复现')
    doc = json.loads(out.read_text(encoding='utf-8'))
    if doc['totals']['redist'] != led['redistributable']:
        rep.add(1, '可分发条数不一致：站点 %s vs 台账 %s'
                % (doc['totals']['redist'], led['redistributable']))
    if len(doc['entries']) != led['redistributable']:
        rep.add(1, '站点目录条数 %d ≠ 台账可分发 %d'
                % (len(doc['entries']), led['redistributable']))
    return led


# ── 关 2 · 许可红线 ────────────────────────────────────────────────────
def gate2(rep: Rep, doc: dict):
    if not doc:
        return
    ents = doc['entries']
    bad_f4 = [e['i'] for e in ents if e['t'] not in ('F1', 'F2', 'F3')]
    if bad_f4:
        rep.add(2, '目录里出现非可分发档位：%s' % '、'.join(bad_f4[:4]))
    else:
        rep.ok(2, '目录仅含 F1/F2/F3（%d 条）' % len(ents))

    # F3 只给指引：不得有任何下载直链
    f3_dl = [e['i'] for e in ents if e['t'] == 'F3' and (e.get('d') or e.get('h'))]
    if f3_dl:
        rep.add(2, 'F3（传染性许可）出现了下载直链：%s' % '、'.join(f3_dl[:4]))
    else:
        rep.ok(2, 'F3 无下载直链（只给来源页）')

    # 托管直链只允许出现在 F1/F2
    host_bad = [e['i'] for e in ents if e.get('h') and e['t'] not in ('F1', 'F2')]
    if host_bad:
        rep.add(2, '站内托管直链出现在非 F1/F2：%s' % '、'.join(host_bad[:4]))

    # 「存疑」358 条：只允许出现总数，不许逐条列出
    gi = json.dumps(doc, ensure_ascii=False)
    if '存疑' not in json.dumps(doc['excluded_agg'], ensure_ascii=False):
        rep.add(2, '不收录聚合里缺「存疑」一项 —— 必须如实列出总数')
    for it in doc['excluded_items']:
        if '存疑' in (it.get('l') or '') or '存疑' in (it.get('r') or ''):
            rep.add(2, '「存疑」条目被逐条列出（应只给总数）：%s' % it['n'][:40])
            break
    else:
        rep.ok(2, '「存疑」只给总数（%d 条），未逐条列出'
               % doc['totals']['gray'])
    if gi.count('存疑') > 6:
        rep.add(2, '页面文案里「存疑」出现次数异常（%d）' % gi.count('存疑'), severe=False)

    # 不收录条目不得带下载直链字段
    leaked = [it['n'] for it in doc['excluded_items'] if 'dl' in it or 'h' in it]
    if leaked:
        rep.add(2, '不收录条目带下载字段：%s' % leaked[0][:40])
    else:
        rep.ok(2, '不收录条目无下载字段（%d 条）' % len(doc['excluded_items']))


# ── 关 3 · 外壳一致性 ──────────────────────────────────────────────────
def gate3(rep: Rep):
    pages = sorted(p for p in SITE.rglob('*.html'))
    if not pages:
        rep.add(3, '没有页面')
        return
    hs, fs_, nv = {}, {}, {}

    def _norm(block: str) -> str:
        """去掉高亮态、品牌链接的目录前缀、空白差异后比对（页头/页脚应对各页逐字一致）。"""
        b = re.sub(r'\s*class="on"', '', block)
        # 品牌链接子目录页是 ../、根页是 ./ —— 归一成同一个占位，只关心「其余逐字相同」
        b = re.sub(r'(class="brand" href=")[^"]*"', r'\1HOME"', b)
        return re.sub(r'\s+', ' ', b).strip()

    for p in pages:
        s = p.read_text(encoding='utf-8')
        m = RE_HEADER.search(s)
        if not m:
            rep.add(3, '%s：缺 <header>' % p.name)
        else:
            hs.setdefault(_norm(m.group(0)), []).append(p.name)
        m = RE_FOOTER.search(s)
        if not m:
            rep.add(3, '%s：缺 <footer>' % p.name)
        else:
            fs_.setdefault(_norm(m.group(0)), []).append(p.name)
        m = RE_NAV.search(s)
        if m:
            nv.setdefault(tuple(RE_HREF.findall(m.group(1))), []).append(p.name)
    if len(hs) > 1:
        rep.add(3, '页头不唯一：%d 种形态' % len(hs))
    else:
        rep.ok(3, '页头逐字一致（%d 页）' % len(pages))
    if len(fs_) > 1:
        rep.add(3, '页脚不唯一：%d 种形态' % len(fs_))
    else:
        rep.ok(3, '页脚逐字一致（%d 页）' % len(pages))
    if not nv:
        rep.add(3, '未找到 .nav 导航')
    else:
        if len(nv) > 1:
            rep.add(3, '导航形态不唯一：%d 种' % len(nv))
        got = list(nv)[0]
        if got != tuple(NAV_EXPECT):
            rep.add(3, '导航顺序不符：%s' % ' → '.join(u.replace('https://', '') for u in got))
        else:
            rep.ok(3, '导航顺序固定为 7 项（数据四站 lib/mid/zip/sf + lib 三个站内页）')
    # shell.js 必须与 lib 真源逐字节相同
    a = SITE / 'assets' / 'shell.js'
    if not a.exists():
        rep.add(3, '缺 assets/shell.js')
    elif LIB_SHELL.exists():
        h1 = hashlib.sha256(a.read_bytes()).hexdigest()
        h2 = hashlib.sha256(LIB_SHELL.read_bytes()).hexdigest()
        if h1 != h2:
            rep.add(3, 'assets/shell.js 与 lib 真源不一致（跑 _apply_site_shell.py 同步）')
        else:
            rep.ok(3, 'shell.js 与 lib 真源哈希一致')
    # style.css 是 lib 复制件
    st = SITE / 'assets' / 'style.css'
    lib_st = MIDI / 'lib' / 'site' / 'assets' / 'style.css'
    if st.exists() and lib_st.exists():
        if hashlib.sha256(st.read_bytes()).hexdigest() != hashlib.sha256(lib_st.read_bytes()).hexdigest():
            rep.add(3, 'assets/style.css 与 lib 复制件不一致（这份不该改）')
        else:
            rep.ok(3, 'style.css 与 lib 复制件一致')


# ── 关 4 · 死链 ────────────────────────────────────────────────────────
RE_LOCAL = re.compile(r'(?:href|src)="(?!https?:|data:|mailto:|#|//)([^"]+)"')
RE_SCRIPT = re.compile(r'<script\b.*?</script>', re.S)


def gate4(rep: Rep):
    for must in ('index.html', '404.html', 'robots.txt', 'sitemap.xml', 'manifest.json',
                 'assets/style.css', 'assets/site.css', 'assets/shell.js', 'assets/og.png',
                 'data/soundfonts.json', 'f2/index.html', 'ethnic/index.html'):
        if not (SITE / must).exists():
            rep.add(4, '缺产物 %s' % must)
    if not (SITE / 'core.lock.json').exists():
        # 数据侧站（lib / mid / zip / sf）**不装 kb 内核** —— 外壳是 lib 的复制件，
        # 由 `_apply_site_shell.py` 分发并逐字节比对（见关 3），故这里只作提示。
        rep.add(4, '无 core.lock.json —— 数据侧站的正常状态（外壳走 lib 复制件，见关 3）',
                severe=False)
    n = 0
    for p in sorted(SITE.rglob('*.html')):
        # ⚠️ 必须剔除内联脚本再扫 —— 脚本模板里的 href="' + esc(x) + '" 不是真链接
        s = RE_SCRIPT.sub('', p.read_text(encoding='utf-8'))
        for href in RE_LOCAL.findall(s):
            t = href.split('#')[0].split('?')[0]
            if not t or t.endswith('.md'):
                continue
            n += 1
            # ⚠️ 子目录页（f2/…）里 `assets/x` 会算成 `f2/assets/x`；
            #    以 `/` 开头的绝对引用要按**站点根**解析。两种都得认。
            tgt = (SITE / t.lstrip('/')) if t.startswith('/') else (p.parent / t)
            if not tgt.exists():
                rep.add(4, '%s → 站内引用 404：%s' % (p.relative_to(SITE).as_posix(), t))
    if all(g != 4 for g, _s, _m in rep.errors):
        rep.ok(4, '站内引用全部可达（%d 处）' % n)
    # 数据里的来源地址必须是 http(s)
    d = SITE / 'data' / 'soundfonts.json'
    if d.exists():
        doc = json.loads(d.read_text(encoding='utf-8'))
        bad = [e['i'] for e in doc['entries'] if not (e['u'] or '').startswith('http')]
        if bad:
            rep.add(4, '来源地址非 http(s)：%s' % '、'.join(bad[:3]))
        else:
            rep.ok(4, '全部 %d 条来源地址均为 http(s)' % len(doc['entries']))


# ── 关 5 · 元数据 ──────────────────────────────────────────────────────
def gate5(rep: Rep):
    for p in sorted(SITE.rglob('*.html')):
        s = p.read_text(encoding='utf-8')
        is404 = p.name == '404.html'
        need = ['<title>', 'name="description"', 'rel="canonical"', 'og:title',
                'og:image', 'twitter:card', 'application/ld+json', 'assets/site.css']
        miss = [x for x in need if x not in s]
        if miss:
            rep.add(5, '%s：缺 %s' % (p.name, '、'.join(miss)))
        if not is404 and 'index,follow' not in s:
            rep.add(5, '%s：robots 不是 index,follow' % p.name)
        if is404 and 'noindex' not in s:
            rep.add(5, '%s：404 页 robots 应为 noindex' % p.name)
    sm = (SITE / 'sitemap.xml').read_text(encoding='utf-8') if (SITE / 'sitemap.xml').exists() else ''
    if 'https://sf.midicn.com/' not in sm:
        rep.add(5, 'sitemap.xml 未含首页')
    rb = (SITE / 'robots.txt').read_text(encoding='utf-8') if (SITE / 'robots.txt').exists() else ''
    if 'sf.midicn.com/sitemap.xml' not in rb:
        rep.add(5, 'robots.txt 未指向本站 sitemap')
    if not rep.errors or all(g != 5 for g, _s, _m in rep.errors):
        rep.ok(5, '页面与站点级元数据齐备')


# ── 关 6 · 双语与表述 ──────────────────────────────────────────────────
def gate6(rep: Rep):
    for p in sorted(SITE.rglob('*.html')):
        rel = p.relative_to(SITE).as_posix()
        s = p.read_text(encoding='utf-8')
        zh = len(re.findall(r'data-zh="', s))
        en = len(re.findall(r'data-en="', s))
        if zh != en:
            rep.add(6, '%s：data-zh(%d) ≠ data-en(%d)' % (rel, zh, en))
        ph_zh = len(re.findall(r'data-ph-zh="', s))
        ph_en = len(re.findall(r'data-ph-en="', s))
        if ph_zh != ph_en:
            rep.add(6, '%s：data-ph-zh ≠ data-ph-en' % rel)
        # ⚠️ 写作标记只查**我们自己写的部分**：条目行 / 许可原文是**上游数据**，
        #    里面出现 WIP / TODO 之类是上游的措辞，不是我们的未完成标记（踩过：上游音色名带 [WIP]）。
        own = re.sub(r'<li class="srow".*?</li>', '', s, flags=re.S)
        own = re.sub(r'<span class="sr-lic".*?</span>', '', own, flags=re.S)
        m = WRITING_MARKS.search(own)
        if m:
            rep.add(6, '%s：残留写作标记「%s」' % (rel, m.group(0)))
        for pat, hint in GEO.items():
            if re.search(pat, s):
                rep.add(6, '%s：%s' % (rel, hint))
    if all(g != 6 for g, _s, _m in rep.errors):
        rep.ok(6, '双语成对 · 无写作标记残留（已排除上游数据）· 地区表述合规')
    # 数据层同样查地区表述
    d = SITE / 'data' / 'soundfonts.json'
    if d.exists():
        s = d.read_text(encoding='utf-8')
        for pat, hint in GEO.items():
            if re.search(pat, s):
                rep.add(6, 'data/soundfonts.json：%s' % hint)


GATE_NAME = {1: '数据一致性', 2: '许可红线', 3: '外壳一致性', 4: '死链与产物', 5: '元数据', 6: '双语与表述'}


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv[1:])
    rep = Rep()
    led = gate1(rep)
    out = SITE / 'data' / 'soundfonts.json'
    doc = json.loads(out.read_text(encoding='utf-8')) if out.exists() else None
    gate2(rep, doc)
    gate3(rep)
    gate4(rep)
    gate5(rep)
    gate6(rep)

    errs = rep.errors
    if a.quiet:
        print('[sf preflight] 错误 %d · 提示 %d' % (len(errs), len(rep.items) - len(errs)))
        return 2 if errs else 0
    print('══ preflight · sf（sf.midicn.com）══')
    if doc:
        t = doc['totals']
        print('台账 %s 条 · 可分发 %d · 目录 %d · 站内托管 %d' % (
            t['all'], t['redist'], len(doc['entries']), t['hosted']))
    print()
    for g in sorted(GATE_NAME):
        hits = [x for x in rep.items if x[0] == g]
        sev = [x for x in hits if x[1]]
        print('%s 第 %d 关 · %-10s %s' % ('✗' if sev else '✓', g, GATE_NAME[g],
                                          '通过' if not sev else '%d 项错误' % len(sev)))
        for _g, s, m in hits:
            if s or len(hits) <= 4:
                print('      %s %s' % ('!' if s else '·', m))
    print()
    if errs:
        print('✗ 未通过：%d 项错误' % len(errs))
        return 2
    print('✓ 六关全绿')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
