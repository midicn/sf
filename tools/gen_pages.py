#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S4 · 专区页生成器 —— 生成「F2 专区」与「民族音色专项」两个静态页。

为什么**服务端渲染**（而不是像首页那样客户端渲染）
------------------------------------------------
两个专区都是**内容的呈现**：382 条 F2、23 条民族音色，每条要给出作者、许可原文、来源。
服务端渲染的好处：① 搜索引擎直接看得到（客户端渲染的列表对 SEO 等价于空页）
② 首屏不依赖 fetch，慢网下也是「一打开就有」 ③ 不需要额外的 JS 分支。
代价是 HTML 大一些（双语写成 `data-zh`/`data-en` 属性），可以接受。

数据来源
--------
`lib/work/docs/soundfonts.json`（台账，单一真源）+ `data/hosted.json`（哪些已托管）。
本脚本**只呈现事实**，不自己判定许可 —— 档位/可分发全取台账。

产出
----
    f2/index.html       F2 专区（CC BY / MIT / BSD / ISC）
    ethnic/index.html   民族 / 世界音色专项

用法
    python tools/gen_pages.py
    python tools/gen_pages.py --check     # 只校验产物是否最新
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent          # sf/site/tools
SITE = HERE.parent                              # sf/site
DEFAULT_LEDGER = HERE.parents[2] / "lib" / "work" / "docs" / "soundfonts.json"
HOSTED = SITE / "data" / "hosted.json"

SRC_NAME = {"ma": "musical-artifacts", "freepats": "FreePats", "sfz": "sfzinstruments",
            "musescore": "MuseScore"}
TAG = {"zh": 'data-zh', "en": 'data-en'}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def sz(mb, src: str = "") -> str:
    """体积展示：没有就写「未标注」而不是「—」—— 那不是零，是上游没给。"""
    if not mb:
        return "未标注"
    v = ("%.2f GB" % (mb / 1024)) if mb >= 1024 else ("%.0f MB" % mb if mb >= 10 else "%.1f MB" % mb)
    return v + ("*" if src == "head" else "")


def bi(zh: str, en: str) -> str:
    """双语属性（供外壳脚本按 data-zh/data-en 切换）"""
    return 'data-zh="%s" data-en="%s"' % (esc(zh), esc(en))


def head(title: str, desc: str, *, css_extra: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="stylesheet" href="/assets/style.css">
<link rel="stylesheet" href="/assets/site.css">
{css_extra}</head>
<body>

<header><div class="hbar">
  <a class="brand" href="/" aria-label="midicn-lib soundfonts"><b>midicn-lib</b><i>soundfonts</i></a>
  <nav class="nav" aria-label="站内与姊妹站导航"></nav>
</div></header>
"""


FOOT = """
<footer><div class="wrap">
  <div class="fbar">
    <b>midicn-lib</b><i>soundfonts</i>
    <nav class="fnav" aria-label="页脚导航"></nav>
    <span class="flic" id="footLic" data-zh="代码 MIT · 元数据 CC BY 4.0 · 素材依各来源许可" data-en="Code MIT · metadata CC BY 4.0 · material per source">代码 MIT · 元数据 CC BY 4.0 · 素材依各来源许可</span>
  </div>
  <div class="fnote"><span id="footNote"></span><span id="footLegal"></span></div>
</div></footer>
</body>
</html>
"""


def row(e: dict, hosted: dict, *, show_licence_text: bool = False, hint=None) -> str:
    """一条音色的展示行（复用首页那套 .srow 样式，视觉一致）

    ⚠️ `bi()` 产出的**是属性**，必须写在标签里（`<a %s … >中文</a>`），
       不能当内容拼 —— 否则页面会把 `data-zh="…"` 当字面文本显示出来（**真踩到过**）。
       可见文本写中文，外壳脚本按 `data-zh`/`data-en` 覆写。
    """
    h = hosted.get(e["id"])
    right = []
    if h:
        right.append('<a class="act dl" %s href="%s" download>站内直下 ↓</a>' % (
            bi("站内直下 ↓", "Download ↓"), esc(h["url"])))
        right.append('<a class="act lib play" %s href="https://lib.midicn.com/?sf=%s" '
                     'target="_blank" rel="noopener">用它试听 ↗</a>' % (
                         bi("用它试听 ↗", "Play with it ↗"), esc(e["id"])))
    else:
        if e.get("dl_url") and not e.get("dl_blocked"):
            right.append('<a class="act src" %s href="%s" target="_blank" rel="noopener">来源下载 ↗</a>' % (
                bi("来源下载 ↗", "Source ↗"), esc(e["dl_url"])))
        elif e.get("dl_url"):
            # 实测被 403 拒绝 → 不再给下载按钮，改给来源页（不把用户送到打不开的链接）
            right.append('<a class="act src" %s href="%s" target="_blank" rel="noopener" '
                         'title="上游直链拒绝直接访问（实测 403），请到来源页取">来源页 ↗</a>' % (
                bi("来源页 ↗", "Source page ↗"), esc(e["url"])))
        right.append('<a class="act lib" %s href="https://lib.midicn.com/" target="_blank" '
                     'rel="noopener">音乐库试听 ↗</a>' % bi("音乐库试听 ↗", "Try in library ↗"))
    tier = e["tier"]
    cls = "c1" if tier == "F1" else "c2" if tier == "F2" else "c3"
    note = ""
    if show_licence_text and e.get("license_raw"):
        # 署名素材：把**上游写的许可原文**摆出来（这就是「附署名」的实据）
        note = ('<span class="sr-lic">%s</span>' % esc(e["license_raw"][:180]))
    fmts = " / ".join(e.get("formats") or [])
    # hint 传 (中文, English) 二元组；同样必须走**属性位置**
    hit = ('<span class="sr-hit" %s>↳ %s</span>' % (bi(hint[0], hint[1]), esc(hint[0]))
           if hint else '')
    return (
        '<li class="srow" data-id="%s"><div class="sr-main">'
        '<a class="sr-k" href="%s" target="_blank" rel="noopener" title="%s">%s</a>'
        '<span class="sr-meta">%s · %s · %s%s</span>%s%s'
        '</div><div class="sr-side">'
        '<span class="tierbadge %s">%s</span>'
        '<span class="sr-z">%s</span>%s'
        '</div></li>' % (
            esc(e["id"]), esc(e["url"]), esc(e["name"]), esc(e["name"]),
            esc(e.get("author") or "—"), esc(SRC_NAME.get(e["source"], e["source"])),
            esc(fmts), (" in ." + esc(e["pack"])) if e.get("pack") else "",
            note, hit, cls, tier, sz(e.get("size_mb")), "".join(right))
    )


def sections(entries: list[dict], cats: dict, hosted: dict, *, show_licence_text=False) -> str:
    """按分类分组渲染（分类顺序取台账的 cat_names 顺序）"""
    order = list(cats.keys())
    by = {}
    for e in entries:
        by.setdefault(e["cat"], []).append(e)
    out = []
    for k in order:
        items = by.get(k)
        if not items:
            continue
        cn = cats[k]
        items.sort(key=lambda e: (e.get("size_mb") or 9e9, e["name"].lower()))
        out.append(
            '<details class="catsec" open><summary><h3%s>%s</h3>'
            '<span class="spacer"></span><span class="meta" %s>%d 条</span></summary>'
            '<ul class="slist">%s</ul></details>' % (
                bi(cn["zh"], cn["en"]), esc(cn["zh"]),
                bi("%d 条" % len(items), "%d items" % len(items)), len(items),
                "".join(row(e, hosted, show_licence_text=show_licence_text) for e in items)))
    return "".join(out)


# ══════════════════════════════════════════════════════════════════════
def page_f2(led: dict, hosted: dict) -> str:
    ents = [e for e in led["entries"] if e["tier"] == "F2"]
    ents.sort(key=lambda e: e["name"].lower())
    by_lic: dict[str, int] = {}
    for e in ents:
        by_lic[e["license"]] = by_lic.get(e["license"], 0) + 1
    lic_rows = "".join(
        "<tr><td>%s</td><td>%d</td></tr>" % (esc(k), v)
        for k, v in sorted(by_lic.items(), key=lambda kv: -kv[1]))

    body = f"""
<main class="doc wide">
  <p class="meta" {bi("档案 · 许可专区", "ARCHIVE · LICENCE ZONE")}>档案 · 许可专区</p>
  <h1 {bi("F2 专区 · 署名后可分发", "F2 zone · redistribution with credit")}>F2 专区 · 署名后可分发</h1>
  <p class="lede" {bi(
    "这一档的许可（CC BY / MIT / BSD / ISC）**允许你商用、也允许改作**，唯一条件是<b>署名</b>。这里把 "
    + str(len(ents)) + " 条 F2 音色逐条列出，并写明<b>该署谁的名</b>、<b>许可是怎么写的</b>、<b>去哪里取</b>。",
    "These licences (CC BY / MIT / BSD / ISC) let you use the banks commercially and remix them — the only "
    "condition is <b>attribution</b>. All " + str(len(ents)) + " F2 banks are listed below with <b>who to credit</b>, "
    "<b>what the licence actually says</b>, and <b>where to get it</b>.")}>这一档的许可允许商用、也允许改作，唯一条件是署名。</p>

  <div class="stat">
    <div><b>{len(ents)}</b><span {bi("条 F2 音色", "F2 banks")}>条 F2 音色</span></div>
    <div><b>{len(by_lic)}</b><span {bi("种许可", "licences")}>种许可</span></div>
    <div><b>{sum(1 for e in ents if e['id'] in hosted)}</b><span {bi("站内已托管", "self-hosted")}>站内已托管</span></div>
  </div>

  <div class="note" {bi(
    "<b>为什么 F2 基本不托管、只给来源</b>：两个原因，都写在明面上。"
    "① <b>体积</b> —— F2 里最值得用的几个（FluidR3_GM 124 MB、MuseScore_General 205 MB、"
    "Salamander Grand Piano 296 MB 起）都远超本站 50 MB 的托管红线；"
    "② <b>署名义务会传下去</b> —— 托管之后，每个下载的人都要自己承担署名，"
    "我们更愿意把这件事讲清楚，而不是替你打包。",
    "<b>Why almost nothing here is self-hosted</b>, stated plainly: ① <b>size</b> — the most useful F2 banks "
    "(FluidR3_GM 124 MB, MuseScore_General 205 MB, Salamander Grand Piano from 296 MB) are far past the 50 MB "
    "hosting line; ② <b>attribution travels downstream</b> — once hosted, every downloader inherits the duty, "
    "so we explain it rather than silently bundle it.")}></div>

  <div class="stitle"><h2 {bi("一 · 许可分布", "1 · Licences")}>一 · 许可分布</h2></div>
  <div class="tblwrap"><table><thead><tr>
    <th {bi("许可", "Licence")}>许可</th><th {bi("条数", "Banks")}>条数</th></tr></thead>
    <tbody>{lic_rows}</tbody></table></div>
  <div class="note" {bi(
    "署名怎么写取决于许可：<b>CC BY</b> 写「作者 + 许可名 + 来源链接」；"
    "<b>MIT / BSD / ISC</b> 要把许可原文与版权声明一并保留。每条下面都给了上游的许可原文，照抄即可。",
    "What to write depends on the licence: <b>CC BY</b> — author, licence name, source link; "
    "<b>MIT / BSD / ISC</b> — keep the licence text and copyright notice together. Each entry below carries the "
    "upstream's own licence wording; copy from there.")}></div>

  <div class="stitle"><h2 {bi("二 · 全部 F2 音色（按用途）", "2 · All F2 banks by use")}>二 · 全部 F2 音色（按用途）</h2></div>
  <div class="note" {bi(
    "点名称去来源页；下方灰字是<b>上游自己写的许可原文</b>（署名时照抄）。"
    "标注「来源下载」的可以直接取，其余请到来源页找。",
    "Click a name to open its source page; the grey line is the <b>upstream's own licence wording</b> "
    "(copy it when crediting). “Source” links download directly; otherwise look on the source page.")}></div>
  {sections(ents, led["cat_names"], hosted, show_licence_text=True)}

  <div class="stitle"><h2 {bi("三 · 怎么用", "3 · How to use")}>三 · 怎么用</h2></div>
  <ol class="steps">
    <li {bi("从来源页取回 <code>.sf2</code>（若是 <code>.7z</code>/<code>.zip</code> 先解压）。",
            "Get the <code>.sf2</code> from the source page (unzip <code>.7z</code>/<code>.zip</code> first).")}>
      从来源页取回 <code>.sf2</code>。</li>
    <li {bi("到 <a href=\"https://lib.midicn.com/\">音乐库</a>播放器的「音色」里选「选择本地音色文件…」。",
            "Open the <a href=\"https://lib.midicn.com/\">library</a> and choose “Select local sound bank…”.")}>
      到音乐库播放器里选「选择本地音色文件…」。</li>
    <li {bi("在你的成果里按上面写的许可原文署名 —— 这一步是这一档的<b>唯一</b>义务。",
            "Credit it in your work using the licence wording above — that is the <b>only</b> obligation here.")}>
      在你的成果里按许可原文署名。</li>
  </ol>
</main>
"""
    title = "F2 专区 · 署名后可分发（%d 条 CC BY / MIT / BSD / ISC 音色库）" % len(ents)
    desc = ("%d 条署名后可分发的 SoundFont：逐条给出作者、许可原文与来源地址，附署名写法与取材方式。" % len(ents))
    return head(title, desc) + body + FOOT


# ══════════════════════════════════════════════════════════════════════
# 民族 / 世界音色：库内对应的曲目规模（让「拿它弹什么」有答案）
REPERTOIRE = {
    "bagpipe": ("爱尔兰 / 苏格兰风笛曲（thesession 有 23,250 首）", "Irish & Scottish pipe tunes (23,250 in thesession)"),
    "kalimba": ("非洲拇指琴，适合民族小品与儿童曲", "African thumb piano — folk miniatures and children's tunes"),
    "jaw harp": ("口弦，欧亚民间音乐", "Jew's harp — Eurasian folk music"),
    "ukulele": ("尤克里里，民谣与岛国音乐", "Ukulele — folk and island music"),
    "world": ("世界打击乐：中国民歌、爱尔兰民谣都吃这一套", "World percussion — fits both the Chinese folk and Irish collections"),
    "recorder": ("竖笛，巴洛克与学校音乐", "Recorder — Baroque and school repertoire"),
    "ocarina": ("陶笛，民谣与游戏配乐", "Ocarina — folk tunes and game music"),
    "hang": ("手碟，冥想与即兴", "Handpan — meditative and improvised"),
    "glass": ("玻璃琴，实验与氛围", "Glass harmonica — experimental and ambient"),
    "spanish": ("西班牙古典吉他，民谣与古典", "Spanish classical guitar — folk and classical"),
    "harp": ("竖琴，巴洛克与浪漫", "Harp — Baroque and Romantic"),
}


def page_ethnic(led: dict, hosted: dict) -> str:
    ents = [e for e in led["entries"] if e["cat"] == "ethnic" and e["redistributable"]]
    ents.sort(key=lambda e: (e.get("size_mb") or 9e9, e["name"].lower()))
    hosted_n = sum(1 for e in ents if e["id"] in hosted)

    def hint(e) -> tuple:
        """库内对应曲目：返回 (中文, English)，由 row() 放进属性位置"""
        low = (e["name"] + " " + " ".join(e.get("tags") or [])).lower()
        for k, (zh, en) in REPERTOIRE.items():
            if k in low:
                return (zh, en)
        return ("民族 / 世界乐器，按体裁自行取用",
                "Ethnic / world instrument — pick a fitting repertoire")

    # 复用首页那套 row()（含 hint），不另写一份标记 —— 免得样式与双语处理各走一套
    rows = "".join(row(e, hosted, hint=hint(e)) for e in ents)

    body = f"""
<main class="doc wide">
  <p class="meta" {bi("专项 · 民族与世界", "SPECIAL · ETHNIC & WORLD")}>专项 · 民族与世界</p>
  <h1 {bi("民族 / 世界音色专项", "Ethnic &amp; world sound banks")}>民族 / 世界音色专项</h1>
  <p class="lede" {bi(
    "音乐库里有 <b>10,473 首中国民歌</b> 与 <b>23,250 首爱尔兰民谣</b> —— 用通用音色弹它们总是差点意思。"
    "这一页专门收集民族与世界乐器音色，每条还写明<b>库内哪些曲目适合拿它试</b>。",
    "The library holds <b>10,473 Chinese folk songs</b> and <b>23,250 Irish tunes</b> — a General MIDI bank always "
    "sounds a bit off on them. This page gathers ethnic and world banks, and for each one says <b>which repertoire "
    "in the library suits it</b>.")}></p>

  <div class="stat">
    <div><b>{len(ents)}</b><span {bi("可分发民族音色", "redistributable")}>可分发民族音色</span></div>
    <div><b>{hosted_n}</b><span {bi("站内已托管", "self-hosted")}>站内已托管</span></div>
    <div><b>10,473</b><span {bi("库内中国民歌", "Chinese folk")}>库内中国民歌</span></div>
    <div><b>23,250</b><span {bi("库内爱尔兰民谣", "Irish tunes")}>库内爱尔兰民谣</span></div>
  </div>

  <div class="note" {bi(
    "<b>诚实说清最大的缺口</b>：这一档只有 " + str(len(ents)) + " 条。为什么这么少？"
    "因为民族乐器的采样本身稀缺，而且**许可清晰的更稀缺** —— 我们只收录许可明确允许分发的。"
    "目前的主力来源是 <a href=\"https://freepats.zenvoid.org/\" target=\"_blank\" rel=\"noopener\">FreePats</a>"
    "（DFSG 合规、逐条写明记录人与许可），它的民族乐器多为 <b>CC0 + .sf2</b>，是本站能直接托管的那一批。",
    "<b>The biggest gap, stated honestly</b>: this tier has only " + str(len(ents)) + " entries. Ethnic instrument "
    "sampling is scarce to begin with, and banks with <i>clear</i> licences are scarcer — we only list what may "
    "legitimately be redistributed. The main source is "
    "<a href=\"https://freepats.zenvoid.org/\" target=\"_blank\" rel=\"noopener\">FreePats</a> (DFSG-compliant, "
    "credits and licence written per item); its ethnic banks are mostly <b>CC0 + .sf2</b>, which is what we can "
    "host directly.")}></div>

  <div class="stitle"><h2 {bi("一 · 全部民族 / 世界音色", "1 · All ethnic & world banks")}>一 · 全部民族 / 世界音色</h2></div>
  <div class="note" {bi(
    "「↳」后面是<b>库内对应的曲目</b>，用来判断拿它弹什么最合适。标 F1 的可站内直下、并用「用它试听」一键装进音乐库。",
    "After “↳” is the <b>matching repertoire</b> in the library. F1 entries can be downloaded here and loaded into "
    "the library in one click.")}></div>
  <ul class="slist ethnic">{rows}</ul>

  <div class="stitle"><h2 {bi("二 · 还缺什么（欢迎补充线索）", "2 · What is still missing")}>二 · 还缺什么</h2></div>
  <div class="panel"><div class="panel-bd">
    <p {bi(
      "与中国乐器对口的音色库目前<b>几乎没有</b> —— 古琴、琵琶、笛子、二胡这些，"
      "公开且许可清晰的采样极少。我们的做法是：<b>宁缺勿错</b>，不拿「听起来像」的东西顶替，"
      "也不收录来源不清的提取音色。若你知道合规的中国乐器采样库，欢迎在本站仓开 issue 告诉我们。",
      "Banks covering Chinese instruments (guqin, pipa, dizi, erhu) are <b>almost absent</b> from openly and clearly "
      "licensed material. We would rather leave the gap than substitute something that merely sounds close, or list "
      "rips of unclear origin. If you know a compliant Chinese-instrument sample library, open an issue on our repo."
    )}>与中国乐器对口的音色库目前几乎没有。</p>
    <p {bi(
      "同样缺的还有：中东（乌德琴、卡农）、印度（西塔琴、塔布拉）、非洲（科拉、说话鼓）。"
      "这些在 <a href=\"https://sf.midicn.com/\">完整目录</a>里可以按分类筛，但目前多为 F3/F4（有传染性或不可分发）。",
      "Also thin: Middle Eastern (oud, qanun), Indian (sitar, tabla) and African (kora, talking drum) banks. "
      "They can be filtered in the <a href=\"https://sf.midicn.com/\">full catalogue</a>, but most sit in F3/F4."
    )}>同样缺的还有中东、印度与非洲的乐器采样。</p>
  </div></div>
</main>
"""
    title = "民族 / 世界音色专项 · %d 条可分发（附库内对应曲目）" % len(ents)
    desc = ("%d 条可自由或署名分发的民族与世界乐器 SoundFont，逐条给出作者、许可、来源，"
            "并标注音乐库里适合用它演奏的曲目。" % len(ents))
    return head(title, desc) + body + FOOT


# ══════════════════════════════════════════════════════════════════════
MAIN_RE = re.compile(r"<main\b.*?</main>", re.S)


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv[1:])

    lp = Path(a.ledger)
    if not lp.exists():
        print("✗ 找不到台账 %s" % lp, file=sys.stderr)
        return 2
    led = json.loads(lp.read_text(encoding="utf-8"))
    hosted = json.loads(HOSTED.read_text(encoding="utf-8"))["files"] if HOSTED.exists() else {}

    pages = {"f2/index.html": page_f2(led, hosted), "ethnic/index.html": page_ethnic(led, hosted)}
    rc = 0
    for rel, text in pages.items():
        p = SITE / rel
        if a.check:
            # ⚠️ 只比对 `<main>` 块：页头/页脚/SEO 由 `_apply_site_shell.py` 注入，
            #    直接比整文件会永远「不一致」（踩过）。正文才是本脚本的产物。
            old = MAIN_RE.search(p.read_text(encoding="utf-8")).group(0) if p.exists() else ""
            want = MAIN_RE.search(text).group(0)
            same = old == want
            print("  [%s] %s" % ("✓ 一致" if same else "需重建", rel))
            if not same:
                rc = 1
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        n = text.count('class="srow"')
        print("已生成 %s（%.1f KB · %d 条）" % (p, len(text.encode()) / 1024, n))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
