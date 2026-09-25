/* sf.midicn.com · 端到端回归（jsdom）
 * ─────────────────────────────────────────────────────────────────────
 * 复用数据三站那一套：jsdom + stub fetch，不起服务器。
 * 重点验三件事：① 页面脚本真能跑起来（不静默空白）② 筛选/双语交互真的生效
 * ③ **许可政策在渲染层没有被绕过**（F3 不给直链、F4 不出现、存疑不逐条列）
 *
 * 用法（NODE_PATH 指向托管 workspace，那里装了 jsdom）：
 *   NODE_PATH=<node-workspace>/node_modules node tools/e2e-test.js            # 本地产物
 *   NODE_PATH=<node-workspace>/node_modules node tools/e2e-test.js --online   # 线上站点
 * 项目惯例：**本地 + 线上都跑** —— 线上跑能挡住「本地对、线上 404」这类装配漏项。
 */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const SITE = path.resolve(__dirname, '..');
const ONLINE = process.argv.includes('--online');
const ORIGIN = 'https://sf.midicn.com/';

let pass = 0, fail = 0;
const fails = [];
function ok(name, cond, extra){
  if (cond){ pass++; console.log('  ✓ ' + name + (extra ? ' — ' + extra : '')); }
  else { fail++; fails.push(name); console.log('  ✗ ' + name + (extra ? ' — ' + extra : '')); }
}
const wait = ms => new Promise(r=>setTimeout(r, ms));

/* 取站点相对路径的内容：本地读盘 / 线上抓取（带退避） */
async function loadText(rel){
  if (!ONLINE) return fs.readFileSync(path.join(SITE, rel.replace(/\//g, path.sep)), 'utf-8');
  for (let i=0;i<3;i++){
    try{ const r = await fetch(ORIGIN + rel); if (r.ok) return await r.text(); }catch(e){}
    await wait(1500*(i+1));
  }
  throw new Error('线上取不到 ' + rel);
}

(async () => {
  const rawHtml = await loadText('index.html');
  const data = await loadText('data/soundfonts.json');
  /* ⚠️ 必须把 assets/shell.js 内联 —— jsdom 默认不加载外链脚本，
     不内联就会「外壳脚本永不执行」，测出的是假象（lib 站 e2e 同一处理）。 */
  const shellJs = await loadText('assets/shell.js');
  const html = rawHtml.replace(/<script[^>]*src="assets\/shell\.js"[^>]*><\/script>/,
                               '<script>' + shellJs + '</script>');
  console.log('装置：%s%s\n', ONLINE ? '线上 ' + ORIGIN : '本地产物', '');

  /* ① 静态层（对**原始文件**查，不看内联后的副本） */
  ok('页面引用站点样式', /assets\/site\.css/.test(rawHtml));
  ok('页面引用共享外壳脚本', /<script[^>]*src="assets\/shell\.js"/.test(rawHtml));
  ok('SEO 块在位', /<!-- SEO:BEGIN -->/.test(rawHtml) && /<!-- SEO:END -->/.test(rawHtml));
  ok('canonical 指向 sf.midicn.com', /rel="canonical" href="https:\/\/sf\.midicn\.com\/"/.test(rawHtml));
  ok('JSON-LD 为 DataCatalog', /"@type":"DataCatalog"/.test(rawHtml));
  const zh = (rawHtml.match(/data-zh="/g) || []).length;
  const en = (rawHtml.match(/data-en="/g) || []).length;
  ok('双语属性成对', zh === en && zh > 20, zh + ' / ' + en);
  ok('无残留写作标记', !/\bTODO\b|\bFIXME\b|待补|待办/.test(rawHtml));

  /* ② 运行层：stub fetch 从本地读盘，模拟真实浏览器 */
  const vc = new VirtualConsole();
  const errs = [];
  vc.on('jsdomError', e => errs.push(String(e && e.message || e)));
  vc.on('error', e => errs.push(String(e)));
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://sf.midicn.com/',
    virtualConsole: vc,
    beforeParse(window){
      window.fetch = async (url) => {
        const rel = String(url).replace(/^https?:\/\/[^/]+\//, '').replace(/^\.\//, '');
        if (ONLINE){
          const r = await fetch(ORIGIN + rel, {headers:{'User-Agent':'midicn-e2e/1.0'}});
          return { ok: r.ok, status: r.status, json: async()=>JSON.parse(await r.text()) };
        }
        const fp = path.join(SITE, rel.replace(/\//g, path.sep));
        if (!fs.existsSync(fp)) return { ok:false, status:404, json: async()=>({}) };
        const text = fs.readFileSync(fp, 'utf-8');
        return { ok:true, status:200, json: async()=>JSON.parse(text) };
      };
    },
  });
  const w = dom.window, d = w.document;
  /* ⚠️ **必须轮询等渲染就绪**，不能用固定延时：
     线上模式要走网络拉 300KB 数据，固定 `wait(400)` 在慢网下会「首屏还没渲染就断言」，
     产生**假回归**（实测踩到过一次：`#catalog` 还是空的，一批交互断言全红）。
     与 lib 站 e2e 同一做法（那边等瓦片与曲目行就绪）。 */
  await wait(400);
  for (let i = 0; i < 40; i++){
    if (d.querySelectorAll('#catalog .srow').length && d.getElementById('stat').children.length) break;
    await wait(400);
  }

  ok('页面脚本无异常', errs.length === 0, errs.slice(0,2).join(' | '));
  const $ = s => d.querySelector(s);
  const $$ = s => Array.from(d.querySelectorAll(s));

  ok('目录渲染出条目', $$('#catalog .srow').length > 0, $$('#catalog .srow').length + ' 行');
  ok('分类折叠区渲染', $$('#catalog details.catsec').length >= 10, $$('#catalog details.catsec').length + ' 个分类');
  ok('总览条 5 项', $$('#stat > div').length === 5);
  /* ⚠️ 断言里的数字**一律从数据读**，不要写死 ——
     写死一次，以后每次台账增长都会误报（本轮就因此红了 3 项）。 */
  const DOC = JSON.parse(data);
  const nRed = DOC.totals.redist, nHosted = DOC.totals.hosted;
  ok('概览文案含可分发总数', new RegExp(String(nRed)).test($('#lede').textContent),
     '可分发 ' + nRed);
  ok('第一栏（可直接下载）有内容', $$('#f1 .srow').length > 0, $$('#f1 .srow').length + ' 行');
  ok('许可分级四档都渲染', $$('#tiers .tierbox').length === 4);
  ok('不收录聚合已渲染', $$('.excagg li').length >= 6, $$('.excagg li').length + ' 类原因');
  ok('「存疑」只给总数', /358/.test($('#excluded').textContent));

  /* ③ 许可政策不得被渲染绕过 */
  const rows = $$('#catalog .srow');
  const f4 = rows.filter(r => r.querySelector('.tierbadge.c4'));
  ok('目录里没有 F4 条目', f4.length === 0, f4.length + ' 条');
  const f3bad = rows.filter(r => {
    const b = r.querySelector('.tierbadge');
    if (!b || b.textContent.trim() !== 'F3') return false;
    return !!r.querySelector('.act.dl, .act.src');
  });
  ok('F3 条目没有下载/来源直链按钮', f3bad.length === 0, f3bad.length + ' 条');
  const f3 = rows.filter(r => (r.querySelector('.tierbadge')||{}).textContent === 'F3');
  ok('F3 条目仍是「指引」形态', f3.length === 0 || f3.every(r => r.querySelector('.act.guide')));

  /* ③b S2/S3 新能力：站内直下 + 反向链接 */
  const dl = rows.filter(r => r.querySelector('.act.dl'));
  ok('站内托管条目有直下按钮', dl.length > 0, dl.length + ' 条');
  ok('直下按钮都带 download，且指向**本站源**（有 CORS，播放器才取得到）',
     dl.every(r => {
       const a = r.querySelector('.act.dl');
       return a.hasAttribute('download') && /^https:\/\/sf\.midicn\.com\/files\//.test(a.getAttribute('href'));
     }), '例：' + (dl[0] ? dl[0].querySelector('.act.dl').getAttribute('href') : '—'));
  ok('已托管条目给「一键带过去播放」深链（?sf=<uid>）',
     dl.every(r => {
       const a = r.querySelector('.act.lib.play');
       if (!a) return false;
       const href = a.getAttribute('href');
       const id = r.getAttribute('data-id');
       return href === 'https://lib.midicn.com/?sf=' + encodeURIComponent(id);
     }), dl.length + ' 条深链');
  ok('未托管条目只给音乐库首页（不带 sf 参数）',
     rows.filter(r => !r.querySelector('.act.dl')).every(r => {
       const a = r.querySelector('.act.lib');
       return a && a.getAttribute('href') === 'https://lib.midicn.com/';
     }));
  ok('托管条目显示的是**站内实测体积**（不是上游压缩包大小）', (() => {
    const doc = JSON.parse(data);
    const h = doc.entries.filter(e => e.h && e.hz);
    if (!h.length) return false;
    const e0 = h[0];
    const row = rows.find(r => r.getAttribute('data-id') === e0.i);
    if (!row) return false;
    const shown = row.querySelector('.sr-z').textContent;
    const want = Math.round(e0.hz) + ' MB';
    return shown === want || shown === e0.hz.toFixed(1) + ' MB';
  })(), '首条托管条目的体积按 hz 渲染');
  /* 目录是**分类折叠 + 每类截断**渲染的，所以 DOM 里的托管行数 ≤ 总数 ——
     这里按**数据层**对账（DOM 只断言「第一栏有托管行」）。 */
  ok('数据层：托管条数 == 清单条数',
     DOC.entries.filter(e => e.h).length === nHosted,
     DOC.entries.filter(e => e.h).length + ' / ' + nHosted);
  ok('每条都有「音乐库试听」反向链接', rows.every(r => r.querySelector('.act.lib')));
  /* 第一栏含「已托管 + 未托管但 ≤50MB」两类：前者必须有「用它试听」深链，
     后者只给来源链接（所以不能要求整栏都有深链）。 */
  const f1rows = $$('#f1 .srow');
  const f1host = f1rows.filter(r => r.querySelector('.act.dl'));
  ok('第一栏渲染且托管行都带「用它试听」深链',
     f1rows.length > 0 && f1host.length > 0 && f1host.every(r => r.querySelector('.act.lib.play')),
     f1rows.length + ' 行（其中托管 ' + f1host.length + '）');
  ok('分类头下有回音乐库的曲目提示', $$('#catalog .libhint').length > 0,
     $$('#catalog .libhint').length + ' 条提示');

  /* ④ 交互：筛选 */
  const before = $$('#catalog .srow').length;
  const q = $('#q');
  q.value = 'bagpipe'; q.dispatchEvent(new w.Event('input'));
  await wait(60);
  const after = $$('#catalog .srow').length;
  ok('搜索能收窄结果', after > 0 && after < before, before + ' → ' + after);
  ok('搜索命中 bagpipe', /bagpipe/i.test($('#catalog').textContent));

  q.value = 'zzzz-no-such-bank'; q.dispatchEvent(new w.Event('input'));
  await wait(60);
  ok('无匹配时给出提示', /没有匹配/.test($('#catalog').textContent));
  q.value = ''; q.dispatchEvent(new w.Event('input'));
  await wait(60);

  const chip = $$('#tierChips .chip').find(c => /F1/.test(c.textContent));
  chip.dispatchEvent(new w.Event('click'));
  await wait(60);
  const t1 = $$('#catalog .srow').length;
  ok('档位 chip 能筛选', t1 > 0 && t1 < before, before + ' → ' + t1);
  ok('只剩 F1 徽标', $$('#catalog .tierbadge').every(b => b.textContent.trim() === 'F1'));
  chip.dispatchEvent(new w.Event('click'));
  await wait(60);
  ok('再点一次取消筛选', $$('#catalog .srow').length === before);

  const sf2c = $$('#optChips .chip').find(c => /sf2/.test(c.textContent));
  const beforeN = $$('#catalog .srow').length;
  sf2c.dispatchEvent(new w.Event('click'));
  await wait(80);
  const sf2rows = $$('#catalog .srow');
  ok('「仅 .sf2」筛选生效（匹配数下降）',
     Number(($('#hint').textContent.match(/匹配\s*([\d,]+)/) || [0,0])[1].replace(/,/g,'')) < nRed,
     $('#hint').textContent.slice(0, 40));
  ok('「仅 .sf2」下每行 meta 都含 sf2',
     sf2rows.length > 0 && sf2rows.every(r => /sf2/.test(r.querySelector('.sr-meta').textContent)),
     sf2rows.length + ' 行');
  sf2c.dispatchEvent(new w.Event('click'));
  await wait(80);
  ok('取消「仅 .sf2」后恢复', $$('#catalog .srow').length === beforeN);

  /* ⑤ 双语切换 */
  const langBtn = $('#lang');
  langBtn.dispatchEvent(new w.Event('click'));
  await wait(80);
  ok('切到英文后 <html lang> 变更', d.documentElement.lang === 'en');
  ok('英文文案已替换', /records/.test($('#lede').textContent));
  ok('英文下导航仍是 7 项', $$('header .nav a').length === 7);
  langBtn.dispatchEvent(new w.Event('click'));
  await wait(80);
  ok('切回中文正常', d.documentElement.lang === 'zh' && /实测记录/.test($('#lede').textContent));

  /* ⑥ 外壳与页脚 */
  ok('页脚法务行已填实时数字', new RegExp(String(nRed)).test($('#footLegal').textContent));
  ok('页脚备注已填', $('#footNote').textContent.trim().length > 0);
  /* 2026-09-26：sf **进全站导航** —— 数据四站的导航自此完全一致（lib/mid/zip/sf），
     sf 自己是第 4 项，且不再有站点特例覆盖。 */
  const navHrefs = $$('header .nav a').map(a => a.getAttribute('href'));
  const DATA4 = ['https://lib.midicn.com/', 'https://mid.midicn.com/',
                 'https://zip.midicn.com/', 'https://sf.midicn.com/'];
  ok('导航第 4 项就是本站（sf 已进全站导航）', navHrefs[3] === 'https://sf.midicn.com/', navHrefs[3]);
  ok('导航前四项与数据四站顺序一致', navHrefs.slice(0, 4).join() === DATA4.join(),
     navHrefs.slice(0, 4).join(' · '));
  ok('导航共 7 项且含许可与法律', navHrefs.length === 7 && /licenses/.test(navHrefs[6] || ''),
     navHrefs.length + ' 项');

  /* ⑦ S4 专区页（**服务端渲染**，只查内容，不需要 jsdom 交互）
     ─────────────────────────────────────────────────────────────────
     这两页是「内容的呈现」，所以断言以内容为准：条数要和台账对得上、
     署名实据（上游许可原文）要在、不该出现的（F4 / 站内直下）不能出现。 */
  console.log('\n【S4】专区页（F2 / 民族）');
  {
    const doc = JSON.parse(data);
    const nF2 = doc.entries.filter(e => e.t === 'F2').length;
    const nEth = doc.entries.filter(e => e.k === 'ethnic').length;

    const f2 = await loadText('f2/index.html');
    ok('F2 专区可取到', f2.length > 10000, (f2.length / 1024).toFixed(0) + ' KB');
    ok('F2 条数与台账一致', (f2.match(/class="srow"/g) || []).length === nF2,
       (f2.match(/class="srow"/g) || []).length + ' / ' + nF2);
    ok('F2 页给出署名实据（上游许可原文）',
       (f2.match(/class="sr-lic"/g) || []).length > nF2 * 0.5);
    ok('F2 页说明了为什么基本不托管', /为什么 F2 基本不托管/.test(f2));
    ok('F2 页 canonical 指向 /f2/', /rel="canonical" href="https:\/\/sf\.midicn\.com\/f2\/"/.test(f2));
    ok('F2 页资源前缀正确（子目录 ../）', /src="\.\.\/assets\/shell\.js"/.test(f2));
    ok('F2 页不出现 F4 徽标', !/tierbadge c4/.test(f2));
    ok('F2 页不含站内直下（F2 基本不托管）', !/class="act dl"/.test(f2));

    const eth = await loadText('ethnic/index.html');
    ok('民族专项可取到', eth.length > 5000, (eth.length / 1024).toFixed(0) + ' KB');
    ok('民族条数与台账一致', (eth.match(/class="srow"/g) || []).length === nEth,
       (eth.match(/class="srow"/g) || []).length + ' / ' + nEth);
    ok('民族页给出「库内对应曲目」提示', (eth.match(/class="sr-hit"/g) || []).length === nEth);
    ok('民族页诚实说明缺口', /最大的缺口/.test(eth));
    ok('民族页 canonical 指向 /ethnic/',
       /rel="canonical" href="https:\/\/sf\.midicn\.com\/ethnic\/"/.test(eth));
    ok('民族页资源前缀正确', /src="\.\.\/assets\/shell\.js"/.test(eth));
    /* ⚠️ 防「双语属性漏进内容」：属性只能出现在标签内（`<a data-zh="…">`），
       一旦出现在 `>` 之后就会被浏览器当**可见文本**显示出来（真实踩到过：
       页面上直接印着 data-zh="站内直下 ↓"）。这条断言专门守它。 */
    for (const [name, text] of [['F2 专区', f2], ['民族专项', eth]]) {
      const leaked = (text.match(/>[^<]*\sdata-(zh|en|ph-zh|ph-en)="/g) || []).slice(0, 2);
      ok(`${name}：双语属性没有漏进可见文本`, leaked.length === 0,
         leaked.map(s => s.trim().slice(0, 40)).join(' | ') || '干净');
    }
    ok('首页有专区入口且条数与数据一致', (() => {
      const z = $('#zones');
      if (!z) return false;
      const a = Array.from(z.querySelectorAll('a')).map(x => x.getAttribute('href'));
      return a.join() === 'f2/,ethnic/'
        && new RegExp(String(nF2)).test(z.textContent)
        && new RegExp(String(nEth)).test(z.textContent);
    })(), $('#zones') ? $('#zones').textContent.slice(0, 60) : '无');
  }

  console.log('\n===== 结果 (' + (pass + fail) + ' 项): ' + pass + '/' + (pass + fail) + ' 通过 =====');
  if (fails.length) console.log('失败项:\n  - ' + fails.join('\n  - '));
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('装置异常：', e); process.exit(2); });
