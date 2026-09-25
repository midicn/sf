#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音色站数据生成器 —— 把**台账**变成页面可直接渲染的紧凑数据。

单一真源
--------
`lib/work/docs/soundfonts.json`（由 `lib/work/tools/sf_ledger.py --build` 生成）。
本脚本**只做投影**（压缩键名、按展示需要分层），**不新增也不修改任何台账事实** ——
许可档位 / 分类 / 谁可分发，全部来自台账，页面不自己判断。

产出
----
    data/soundfonts.json   页面渲染数据（紧凑、无缩进）
    （可选）data/hosted.json 由 S2 托管步骤生成 —— 存在时自动并入 `h` 字段

用法
----
    python tools/gen_catalog.py                     # 用默认真源路径
    python tools/gen_catalog.py --ledger <path>
    python tools/gen_catalog.py --check             # 只校验产物是否最新
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent          # sf/site/tools
SITE = HERE.parent                              # sf/site
DEFAULT_LEDGER = HERE.parents[2] / "lib" / "work" / "docs" / "soundfonts.json"
OUT = SITE / "data" / "soundfonts.json"
HOSTED = SITE / "data" / "hosted.json"

MAX_NOTE = 180


def load_hosted() -> dict:
    """S2 托管清单（可选）。缺失时不影响生成。"""
    if not HOSTED.exists():
        return {}
    try:
        return json.loads(HOSTED.read_text(encoding="utf-8")).get("files") or {}
    except Exception:
        return {}


def project(led: dict, hosted: dict) -> dict:
    cat_names = led.get("cat_names") or {}
    tier_names = led.get("tier_names") or {}

    entries = []
    for r in led.get("entries", []):
        uid = r["id"]
        h = hosted.get(uid)
        entries.append({
            "i": uid,
            "n": r["name"], "a": r["author"], "s": r["source"],
            "l": r["license"], "c": r["license_code"], "t": r["tier"],
            "k": r["cat"], "f": r["formats"], "z": r["size_mb"],
            "u": r["url"],
            # ⚠️ 下载直链**只给 F1/F2** —— F3 有传染性、F4 不可分发，站点一律不给直链，
            #    台账里仍保留原始 dl_url（供审计），但投影到页面数据时按政策丢弃。
            "d": r["dl_url"] if r["tier"] in ("F1", "F2") else "",
            "o": 1 if r.get("direct_ok") else 0,
            "p": r["pack"], "y": r["downloads"], "g": r["group"],
            "e": r.get("note", "")[:MAX_NOTE],
            # h = 站内托管直链（S2 才有）；hz = **托管文件的实际体积**
            #     ⚠️ 必须与上游页面标注的体积分开：上游标的是压缩包大小，
            #     站内直下的是解包后的 .sf2，两者能差 2–3 倍。展示时以 hz 为准。
            **({"h": h.get("url"), "hz": round((h.get("bytes") or 0) / 1048576, 1)} if h else {}),
        })

    # 不收录清单：**「存疑」358 条不逐条列出**（多为商业游戏 ROM 提取，
    # 再分发几乎必然侵权 —— 我们不做这种赌，只给总数与原因）。
    gray = sum(1 for x in led.get("excluded", []) if x.get("license_code") == "gray")
    exc_items = [{
        "n": x["name"], "a": x["author"], "s": x["source"], "l": x["license"],
        "k": x["cat"], "u": x["url"], "r": x["reason"],
    } for x in led.get("excluded", []) if x.get("license_code") != "gray"]

    # 按原因聚合（页面「我们审过但不收录」小节用）
    agg: dict[str, dict] = {}
    for x in led.get("excluded", []):
        key = x["license"]
        a = agg.setdefault(key, {"l": key, "r": x["reason"], "n": 0})
        a["n"] += 1

    return {
        "schema": 1,
        "generated": date.today().isoformat(),
        "ledger_fetched": led.get("fetched"),
        "totals": {
            "all": led.get("total"),
            "redist": led.get("redistributable"),
            "tier": led.get("by_tier") or {},
            "f1_sf2": led.get("f1_sf2"),
            "hostable": led.get("hostable_f1_50mb"),
            "excluded": len(led.get("excluded", [])),
            "gray": gray,
            "hosted": len(hosted),
        },
        "sources": led.get("sources") or [],
        "cats": [{"id": k, "zh": v["zh"], "en": v["en"],
                  "red": sum(1 for e in entries if e["k"] == k)}
                 for k, v in cat_names.items()
                 if any(e["k"] == k for e in entries)],
        "tiers": tier_names,
        "entries": entries,
        "excluded_agg": sorted(agg.values(), key=lambda a: -a["n"]),
        "excluded_items": exc_items,
        "policy": {
            "ledger": "https://github.com/midicn/midi-library/blob/main/docs/SOUNDFONT-CATALOG.md",
            "ledger_json": "https://github.com/midicn/midi-library/blob/main/docs/soundfonts.json",
            "repro": "lib/work/tools/sf_crawl.py → lib/work/tools/sf_ledger.py --build → sf/site/tools/gen_catalog.py",
        },
    }


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
    doc = project(led, load_hosted())
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))

    if a.check:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        same = old == text
        print("  [%s] %s" % ("✓ 一致" if same else "需重建", OUT.name))
        return 0 if same else 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    t = doc["totals"]
    print("已生成 %s（%.1f KB · sha256 %s）" % (
        OUT, OUT.stat().st_size / 1024,
        hashlib.sha256(text.encode()).hexdigest()[:12]))
    print("  台账 %d 条 · 可分发 %d · F1 %d · 可托管(≤50MB) %d · 站内已托管 %d" % (
        t["all"], t["redist"], t["tier"].get("F1", 0), t["hostable"], t["hosted"]))
    print("  不收录 %d（其中存疑 %d 只给总数不逐条列出）· 不收录逐条清单 %d" % (
        t["excluded"], t["gray"], len(doc["excluded_items"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
