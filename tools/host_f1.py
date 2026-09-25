#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 · 音色托管器 —— 把 F1 音色**取回本地、解包、校验、登记**，产出托管清单。

政策（不可绕过）
----------------
只处理台账里 **F1 + `.sf2` + ≤50 MB** 的条目：
  · F1 = CC0 / 公有领域 / WTFPL / Unlicense —— 零署名负担、零传染
  · `.sf2` = 浏览器唯一能直接载入的格式
  · ≤50 MB = 体积红线（更大的走「指引 + 自取」）
其它档位**一律拒绝**，不给 `--force` 之类的后门。

产出
----
    sf/work/_archives/     上游归档缓存（.7z / .tar.xz / .tar.bz2 …）
    sf/files/              站内托管的 .sf2（**不进站点仓**，走 Release 资产）
    sf/site/data/hosted.json   托管清单 → gen_catalog.py 并入页面数据

上传是**另一条命令**（见 --upload-hint）：本工具只负责「本地已就绪且可核」。

用法
  python tools/host_f1.py --list                 # 看候选与精选方案
  python tools/host_f1.py --apply                # 按精选方案取回（默认 curated）
  python tools/host_f1.py --apply --uid a,b,c    # 指定条目
  python tools/host_f1.py --verify               # 复核已取回文件的 sha256
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent          # sf/site/tools
SITE = HERE.parent                              # sf/site
SF = SITE.parent                                # sf
MIDI = SF.parent                                # 工作区根
LEDGER = MIDI / "lib" / "work" / "docs" / "soundfonts.json"
ARCH = SF / "work" / "_archives"
FILES = SF / "files"
HOSTED = SITE / "data" / "hosted.json"

SEVENZ = Path(r"C:\Program Files\7-Zip\7z.exe")
RELEASE_TAG = "sf-soundfonts-v1"
RELEASE_REPO = "midicn/music-soundfonts"
RELEASE_BASE = "https://github.com/%s/releases/download/%s/" % (RELEASE_REPO, RELEASE_TAG)
# ⚠️ **站点源才是对外地址**（下载直链 + 音乐库播放器取音色都用它）：
#    GitHub Release 资产**不带 `Access-Control-Allow-Origin`** → 浏览器 fetch 不到，
#    所以「选音色即播」那条路必须走本站源。`sf.midicn.com`（GitHub Pages）带 `ACAO: *` ✓。
#    Release 保留为**字节源 + 直下镜像**，由站点 CI 拉进 `_build/files/`（见 deploy.yml）。
SITE_BASE = "https://sf.midicn.com/"
SITE_FILES = "files"                      # 站点内目录名

MAX_MB = 50.0
# 精选配额：**非合成类全取**（每类都是本库用得上的：民族/钢琴/管弦/风琴/吉他/鼓），
# 合成类数量多（19 个）且同类重复度高，首批只取最小的 6 个。
QUOTA = [("ethnic", 99), ("piano", 99), ("orch", 99), ("organ", 99), ("guitar", 99),
         ("drum", 99), ("wind", 99), ("gm", 99), ("vocal", 99), ("hist", 99),
         ("synth", 6)]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (compatible; midicn-sf-host/1.0; +https://sf.midicn.com)"


def slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', (s or "").lower()).strip('-') or "x"


def load_ledger() -> dict:
    if not LEDGER.exists():
        sys.exit("✗ 找不到台账 %s（先跑 lib/work/tools/sf_ledger.py --build）" % LEDGER)
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def eligible(led: dict) -> list[dict]:
    """F1 + .sf2 + ≤50MB —— 唯一允许托管的集合。"""
    return [e for e in led["entries"]
            if e["tier"] == "F1" and e["sf2"] and e.get("size_mb")
            and e["size_mb"] <= MAX_MB and e.get("dl_url")]


def curated(cands: list[dict]) -> list[dict]:
    """按分类配额挑一批（同分类内取体积小的，便于先落地）。"""
    out, seen = [], set()
    for cat, n in QUOTA:
        got = sorted([c for c in cands if c["cat"] == cat], key=lambda c: c["size_mb"])[:n]
        for c in got:
            if c["id"] not in seen:
                seen.add(c["id"])
                out.append(c)
    return out


def fetch(url: str, dest: Path, tries: int = 5) -> bool:
    if dest.exists() and dest.stat().st_size > 1024:
        print("      · 已有缓存 %s（%.1f MB）" % (dest.name, dest.stat().st_size / 1048576))
        return True
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300, context=CTX) as r:
                data = r.read()
            if len(data) < 1024:
                raise ValueError("响应过小（%d B）" % len(data))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            print("      ↓ %.1f MB  %s" % (len(data) / 1048576, dest.name))
            return True
        except Exception as e:                                        # noqa: BLE001
            print("      ! 第 %d 次失败：%s" % (i + 1, type(e).__name__))
            time.sleep(4 * (i + 1))
    return False


def extract_sf2(archive: Path, workdir: Path) -> Path | None:
    """用 7-Zip 解包（7z / tar.xz / tar.bz2 / zip / tar 全都吃），返回其中体积最大的 .sf2。

    ⚠️ **两级解包**：`foo.tar.bz2` 第一层只解出 `foo.tar`，必须再解一次才有文件。
    只要归档名保留了完整后缀链 7-Zip 会自动串起来；但为了不依赖命名，
    这里在找不到 `.sf2` 时**再看有没有 `.tar`，有就再解一层**。
    """
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    sevenz = SEVENZ if SEVENZ.exists() else Path("7z")

    def run(arc: Path, out: Path) -> bool:
        r = subprocess.run([str(sevenz), "x", "-y", "-o" + str(out), str(arc)],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            print("      ! 解包失败：%s" % ((r.stdout or r.stderr or "")[-200:]))
            return False
        return True

    if not run(archive, workdir):
        return None
    sf2s = sorted(workdir.rglob("*.sf2"), key=lambda p: -p.stat().st_size)
    if sf2s:
        return sf2s[0]
    tars = sorted(workdir.rglob("*.tar"), key=lambda p: -p.stat().st_size)
    if tars:
        inner = workdir / "_inner"
        inner.mkdir(parents=True, exist_ok=True)
        if run(tars[0], inner):
            sf2s = sorted(inner.rglob("*.sf2"), key=lambda p: -p.stat().st_size)
            if sf2s:
                return sf2s[0]
    return None


def check_sf2(p: Path) -> tuple[bool, str]:
    """SoundFont 是 RIFF 容器，第 8..11 字节必须是 'sfbk'。"""
    with p.open("rb") as fh:
        head = fh.read(12)
    if len(head) < 12 or head[0:4] != b"RIFF":
        return False, "不是 RIFF 容器"
    if head[8:12] != b"sfbk":
        return False, "RIFF 内不是 'sfbk'（可能是 sf3 / 采样包）"
    return True, "RIFF/sfbk OK"


def http_probe(url: str, tries: int = 4, timeout: int = 60):
    """探测远端资产：先 `Range: bytes=0-0`（省流量，206 + Content-Range 给出总长），
    失败再退回 HEAD。返回 (状态码, 总字节数 or None)。"""
    for i in range(tries):
        for method, hdrs in (("GET", {"Range": "bytes=0-0"}), ("HEAD", {})):
            try:
                req = urllib.request.Request(url, method=method, headers={
                    "User-Agent": UA, **hdrs})
                with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                    cr = r.headers.get("Content-Range") or ""
                    total = r.headers.get("Content-Length")
                    if "/" in cr:
                        total = cr.rsplit("/", 1)[-1]
                    return r.status, (int(total) if (total or "").isdigit() else None)
            except urllib.error.HTTPError as e:
                if e.code in (404, 403, 401):
                    return e.code, None
            except Exception:                                        # noqa: BLE001
                pass
        time.sleep(3 * (i + 1))
    return None, None


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--verify-online", action="store_true",
                    help="核对线上直链可用且字节数一致（走 Range 探测，省流量）")
    ap.add_argument("--uid", default="", help="逗号分隔的条目 id（默认用精选方案）")
    ap.add_argument("--all", action="store_true",
                    help="取**全部**可托管集合（F1+sf2+≤50MB），忽略精选配额")
    ap.add_argument("--upload-hint", action="store_true")
    a = ap.parse_args(argv[1:])

    led = load_ledger()
    cands = eligible(led)
    picked = (cands if a.all else
              ([c for c in cands if c["id"] in set(a.uid.split(","))] if a.uid
               else curated(cands)))
    todo = [c for c in picked
            if c["id"] not in (json.loads(HOSTED.read_text(encoding="utf-8"))["files"]
                               if HOSTED.exists() else {})]

    if a.list or not (a.apply or a.verify or a.verify_online or a.upload_hint):
        print("台账 %s 条 · 可分发 %d · F1+sf2+≤50MB **可托管 %d** 条 · 已托管 %d 条" % (
            led["total"], led["redistributable"], len(cands),
            len(json.loads(HOSTED.read_text(encoding="utf-8"))["files"]) if HOSTED.exists() else 0))
        print("\n本次方案 %d 条（已托管 %d 条已跳过）· 本次新增合计 %.1f MB：" % (
            len(picked), len(picked) - len(todo), sum(c["size_mb"] for c in todo)))
        for c in sorted(todo, key=lambda c: c["cat"]):
            print("  %-9s %-40s %6.1f MB  %s" % (c["cat"], c["name"][:40], c["size_mb"], c["id"]))
        rest = [c for c in cands if c["id"] not in {x["id"] for x in picked}]
        print("\n未入选（仍可托管，下一批再取）%d 条 · 合计 %.1f MB" % (
            len(rest), sum(c["size_mb"] for c in rest)))
        return 0

    if a.upload_hint:
        if not HOSTED.exists():
            print("✗ 还没有托管清单，先跑 --apply")
            return 2
        hd = json.loads(HOSTED.read_text(encoding="utf-8"))
        print("上传（一条命令，需要 %s 的写权限）：" % RELEASE_REPO)
        print("  python lib/work/tools/_upload_release.py --repo %s --tag %s \\" % (
            RELEASE_REPO, RELEASE_TAG))
        print("      --name 'SoundFont 镜像 %s' --dir sf/files --ext .sf2" % RELEASE_TAG)
        print("\n共 %d 个文件 · %.1f MB" % (
            len(hd["files"]),
            sum(v["bytes"] for v in hd["files"].values()) / 1048576))
        print("\n⚠️ 上传后**必须**再推站点仓让 CI 把文件拉进产物（否则站点源 404）：")
        print("  python lib/work/tools/_push_via_api.py --repo sf/site --apply")
        print("  （等 CI 跑完）python tools/host_f1.py --verify-online")
        return 0

    if a.verify_online:
        if not HOSTED.exists():
            print("✗ 还没有托管清单，先跑 --apply")
            return 2
        hd = json.loads(HOSTED.read_text(encoding="utf-8"))
        print("核对线上直链（站点源 %s%s/ ← 字节源 Release %s）…" % (
            SITE_BASE, SITE_FILES, RELEASE_TAG))
        bad = []
        for i, (uid, v) in enumerate(hd["files"].items(), 1):
            st, n = http_probe(v["url"])
            okk = st in (200, 206) and n == v["bytes"]
            if not okk:
                bad.append((v["file"], st, n, v["bytes"], v["url"]))
            print("  [%2d/%2d] %s %-46s HTTP %-4s %s" % (
                i, len(hd["files"]), "✓" if okk else "✗", v["file"], st,
                ("%s B" % n) if n is not None else "—"))
        print("\n线上核对 %d 个 · 不一致 %d" % (len(hd["files"]), len(bad)))
        for f, st, n, exp, u in bad[:10]:
            print("    ✗ %s  线上 %s/%s · 期望 %s\n      %s" % (f, st, n, exp, u))
        return 2 if bad else 0

    if a.verify:
        hd = json.loads(HOSTED.read_text(encoding="utf-8")) if HOSTED.exists() else {"files": {}}
        bad = 0
        for uid, v in hd["files"].items():
            p = FILES / v["file"]
            if not p.exists():
                print("  ✗ 缺文件 %s" % v["file"]); bad += 1; continue
            b, h = p.stat().st_size, sha256(p)
            okk = (b == v["bytes"] and h == v["sha256"])
            ok2, why = check_sf2(p)
            print("  %s %-46s %8.1f MB  %s" % ("✓" if okk and ok2 else "✗",
                                               v["file"], b / 1048576,
                                               "OK" if okk and ok2 else "%s / %s" % ("哈希或字节数不符" if not okk else "", why)))
            if not (okk and ok2):
                bad += 1
        print("\n复核 %d 个 · 失败 %d" % (len(hd["files"]), bad))
        return 2 if bad else 0

    # ── --apply ──
    ARCH.mkdir(parents=True, exist_ok=True)
    FILES.mkdir(parents=True, exist_ok=True)
    tmp = SF / "work" / "_extract"
    hd = json.loads(HOSTED.read_text(encoding="utf-8")) if HOSTED.exists() else {
        "release_repo": RELEASE_REPO, "release_tag": RELEASE_TAG,
        "base": RELEASE_BASE, "site_base": SITE_BASE, "files": {}}
    hd.setdefault("site_base", SITE_BASE)
    hd.setdefault("files_dir", SITE_FILES)
    # 迁移：早期版本把 `url` 写成 Release 地址（无 CORS）→ 改成站点地址，Release 存进 `release`
    for v in hd["files"].values():
        if v.get("url", "").startswith(RELEASE_BASE) and not v.get("release"):
            v["release"] = v["url"]
            v["url"] = SITE_BASE + SITE_FILES + "/" + v["file"]
        v.setdefault("path", SITE_FILES + "/" + v["file"])
        v.setdefault("release", RELEASE_BASE + v["file"])
    print("取回 %d 个 F1 音色（合计 %.1f MB）…\n" % (
        len(todo), sum(c["size_mb"] for c in todo)))
    for i, c in enumerate(todo, 1):
        print("[%2d/%2d] %s" % (i, len(todo), c["name"][:56]))
        # 归档名**保留完整后缀链**（.tar.xz / .tar.bz2），否则 7-Zip 认不出两级压缩
        base = c["dl_url"].split("?")[0].rsplit("/", 1)[-1]
        sfx = "".join(Path(base).suffixes).lower()
        arc = ARCH / (slug(c["name"]) + (sfx or ".bin"))
        if not fetch(c["dl_url"], arc):
            print("      ✗ 放弃（下轮可续）")
            continue
        sf2 = extract_sf2(arc, tmp)
        if not sf2:
            # ⚠️ **裸 `.sf2` 直链**（musical-artifacts 很多是这样）：下载下来的就是音色本体，
            #    不是归档 —— 用 7-Zip 解会失败。这里先按「本身就是 SoundFont」认一次。
            okc, why = check_sf2(arc)
            if okc:
                sf2 = arc
                print("      · 直链即 .sf2（无需解包）")
            else:
                print("      ✗ 包里没有 .sf2，且直链也不是 SoundFont（%s）" % why)
                continue
        okc, why = check_sf2(sf2)
        if not okc:
            print("      ✗ 校验不过：%s" % why)
            continue
        h = sha256(sf2)
        name = "%s-%s.sf2" % (slug(c["name"])[:48], h[:8])
        dst = FILES / name
        shutil.copy2(sf2, dst)
        hd["files"][c["id"]] = {
            "file": name, "bytes": dst.stat().st_size, "sha256": h,
            "path": SITE_FILES + "/" + name,
            "url": SITE_BASE + SITE_FILES + "/" + name,       # 对外地址（含 CORS）
            "release": RELEASE_BASE + name,                   # 字节源（CI 从这儿拉）
            "name": c["name"], "author": c["author"], "license": c["license"],
            "src": c["dl_url"], "src_bytes": arc.stat().st_size,
            "cat": c["cat"],
        }
        print("      ✓ %s（%.1f MB · %s · %s）" % (name, dst.stat().st_size / 1048576,
                                                  h[:12], c["license"]))
        HOSTED.parent.mkdir(parents=True, exist_ok=True)
        HOSTED.write_text(json.dumps(hd, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)

    tot = sum(v["bytes"] for v in hd["files"].values())
    print("\n托管清单 %s：%d 个文件 · %.1f MB" % (HOSTED, len(hd["files"]), tot / 1048576))
    print("下一步：python tools/gen_catalog.py  →  再跑 tools/preflight.py")
    print("上传：python tools/host_f1.py --upload-hint")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
