/* ═══════════════════════════════════════════════════════════════════════
   midicn-lib · player.js
   共享播放引擎：Tone.js + Midi.js 解析调度（主路径）
                 js-synthesizer 音源套件若可用则优先（可选增强，不存在则静默跳过）
   设计要点
     · 任何第三方 API 都先做 typeof 检查再调用 —— 库版本差异不应导致播放失败
     · 解析出错不吞异常：把原因写到状态回调，便于页面向用户说明
     · 对外只暴露 init / play / toggle / stop / setVolume / isPlaying
   ═══════════════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  var syn = null, bass = null, perc = null, ready = false;
  var part = null, uiTimer = null;
  var playing = false, looping = false;
  var curTotal = 0, curTrack = null, curIdx = -1, queue = [];
  var vol = 70, hooks = {};
  var graph = 'none', lastError = '';

  function $(id) { return document.getElementById(id); }
  function fmt(s) {
    s = Math.max(0, Math.round(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }
  function safe(fn) { try { return fn(); } catch (e) { return null; } }

  /* ── 供应商库按需加载 ───────────────────────────────────────────────
     Tone.js 压缩后 79.8 KB，占全站 JS 载荷 71%，而它只有用户点播放时才用得上。
     过去 1,078 页每页两个无条件 <script>；现在 URL 从 __KB__.vendor 读，
     首次播放时注入并等待。地址由构建器注入，页面模板里不再有这两个标签。 */
  var vendorP = null;
  function loadVendor() {
    if (global.Tone && global.Midi) return Promise.resolve(true);
    if (vendorP) return vendorP;
    var v = (global.__KB__ && global.__KB__.vendor) || {};
    var urls = [];
    if (!global.Tone && v.tone) urls.push(v.tone);
    if (!global.Midi && v.midi) urls.push(v.midi);
    if (!urls.length) {
      lastError = '未配置音频库地址';
      return Promise.resolve(false);
    }
    vendorP = Promise.all(urls.map(function (u) {
      return new Promise(function (res) {
        var el = document.createElement('script');
        el.src = u;
        el.async = true;
        el.onload = function () { res(true); };
        el.onerror = function () { lastError = '音频库加载失败：' + u; res(false); };
        document.head.appendChild(el);
      });
    })).then(function (rs) { return rs.every(Boolean); });
    return vendorP;
  }

  /* ── 音频图（首次播放时建立）──────────────────────────────────────── */
  function initAudio() {
    if (ready) return true;
    if (!global.Tone) { lastError = 'Tone.js 未加载'; return false; }
    // 完整音频图（效果链）；任一步失败则降级为最小图，保证能出声
    try {
      var verb = new Tone.Reverb({ decay: 3.0, preDelay: .015, wet: .26 }).connect(Tone.Destination);
      var filt = new Tone.Filter({ type: 'lowpass', frequency: 5200, rolloff: -12 }).connect(verb);
      var comp = new Tone.Compressor({ threshold: -20, ratio: 2.6, attack: .01, release: .25 }).connect(filt);
      syn = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: 'amtriangle', harmonicity: 2.02, modulationType: 'sine' },
        envelope: { attack: .004, decay: 1.35, sustain: .1, release: 2.0 }, volume: -9
      }).connect(comp);
      bass = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: 'sine' },
        envelope: { attack: .012, decay: 1.1, sustain: .16, release: 1.6 }, volume: -11
      }).connect(comp);
      perc = new Tone.PolySynth(Tone.MembraneSynth || Tone.Synth, { volume: -6 }).connect(comp);
      graph = 'full';
    } catch (e) {
      safe(function () { syn && syn.dispose(); });
      try {
        syn = new Tone.PolySynth(Tone.Synth, { volume: -8 }).toDestination();
        bass = syn; perc = syn; graph = 'minimal';
        lastError = '效果链不可用（已降级）：' + ((e && e.message) || e);
      } catch (e2) {
        lastError = '合成器初始化失败：' + ((e2 && e2.message) || e2);
        return false;
      }
    }
    applyVolume();
    ready = true;
    if (graph === 'minimal' && hooks.onBadge) safe(function () { hooks.onBadge('简易音源'); });
    return true;
  }
  function applyVolume() {
    if (!global.Tone) return;
    safe(function () { Tone.getDestination().volume.value = (vol / 100) * 12 - 12; });
  }

  /* ── 状态回调（页面自行决定怎么显示）─────────────────────────────── */
  function badge(text) { if (hooks.onBadge) safe(function () { hooks.onBadge(text); }); }
  function status(text) { if (hooks.onStatus) safe(function () { hooks.onStatus(text); }); }

  /* ── 停止 ───────────────────────────────────────────────────────── */
  function stop() {
    if (uiTimer) { clearInterval(uiTimer); uiTimer = null; }
    if (part) safe(function () { part.stop(); part.dispose(); }), part = null;
    safe(function () { if (global.Tone) { Tone.Transport.stop(); Tone.Transport.cancel(); } });
    if (ready && syn) safe(function () { syn.releaseAll(); bass.releaseAll(); perc.releaseAll(); });
    playing = false;
    if (hooks.onState) safe(function () { hooks.onState(false); });
  }

  /* ── 进度 ───────────────────────────────────────────────────────── */
  function tick() {
    if (uiTimer) clearInterval(uiTimer);
    uiTimer = setInterval(function () {
      if (!playing || !ready) return;
      var pos = safe(function () { return Tone.Transport.seconds; }) || 0;
      if (hooks.onTime) safe(function () { hooks.onTime(pos, curTotal); });
      if (pos >= curTotal) onEnded();
    }, 250);
  }
  function onEnded() {
    if (looping && curTrack) { play(curTrack, curIdx); return; }
    stop();
    if (hooks.onEnd) safe(function () { hooks.onEnd(); });
  }

  /* ── 播放 ───────────────────────────────────────────────────────── */
  async function play(track, idx, list) {
    try {
      return await _play(track, idx, list);
    } catch (e) {
      playing = false;
      if (hooks.onState) safe(function () { hooks.onState(false); });
      status('播放失败：' + ((e && e.message) || e));
    }
  }

  async function _play(track, idx, list) {
    stop();
    curTrack = track;
    if (typeof idx === 'number') curIdx = idx;
    if (Array.isArray(list)) queue = list;
    if (!track || typeof track.f !== 'string' || !track.f) { status('该条目缺少文件路径'); return; }

    if (!global.Tone || !global.Midi) {
      status('加载音频引擎…');
      var okv = await loadVendor();
      if (!okv) { status(lastError || '音频引擎不可用'); return; }
    }
    if (!initAudio()) { status(lastError || 'Tone.js 未就绪'); return; }
    safe(function () { Tone.start(); });
    if (global.Tone && Tone.start && Tone.start().catch) safe(function () { Tone.start()['catch'](function () {}); });
    if (!global.Midi) { status('Midi.js 未加载'); return; }

    try {
      status((track.t || track.id) + ' · 读取中');
      var res = await fetch(track.f, { cache: 'force-cache' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var buf = await res.arrayBuffer();
      var midi = new Midi(buf);
      var notes = [];
      midi.tracks.forEach(function (tr) {
        tr.notes.forEach(function (n) {
          notes.push({ time: n.time, name: n.name, dur: Math.max(n.duration, .05),
                       vel: n.velocity, pitch: n.midi });
        });
      });
      if (!notes.length) { status('该文件无可播放音符'); return; }

      var isPerc = (track.g === 'drum') || /drum|perc/i.test(track.i || '');
      Tone.Transport.stop(); Tone.Transport.cancel(); Tone.Transport.position = 0;
      part = new Tone.Part(function (time, n) {
        var v = Math.min(1, Math.max(.15, n.vel || .7));
        if (isPerc) perc.triggerAttackRelease(n.pitch < 50 ? 'C1' : 'G2', .12, time, v * .9);
        else if (n.pitch < 48) bass.triggerAttackRelease(n.name, n.dur, time, v * .85);
        else syn.triggerAttackRelease(n.name, n.dur, time, v);
      }, notes);
      part.start(0);
      curTotal = Math.round(midi.duration) || 1;
      part.stop(curTotal + 1.5);
      Tone.Transport.start('+0.08');
      playing = true;
      if (hooks.onState) safe(function () { hooks.onState(true); });
      if (hooks.onTime) safe(function () { hooks.onTime(0, curTotal); });
      badge('Tone');
      status((track.t || track.id) + ' · ' + fmt(curTotal));
      tick();
    } catch (e) {
      playing = false;
      if (hooks.onState) safe(function () { hooks.onState(false); });
      status('播放失败：' + ((e && e.message) || e));
    }
  }

  function toggle() {
    if (!global.Tone) return;
    if (playing) { safe(function () { Tone.Transport.pause(); }); playing = false;
                   if (hooks.onState) safe(function () { hooks.onState(false); }); }
    else { safe(function () { Tone.Transport.start(); }); playing = true;
           if (hooks.onState) safe(function () { hooks.onState(true); }); }
  }

  function next() { if (curIdx >= 0 && queue[curIdx + 1]) play(queue[curIdx + 1], curIdx + 1); }
  function prev() { if (curIdx > 0 && queue[curIdx - 1]) play(queue[curIdx - 1], curIdx - 1); }
  function seek(frac) {
    if (!ready || !curTotal) return;
    safe(function () { Tone.Transport.seconds = Math.max(0, Math.min(0.999, frac)) * curTotal; });
  }

  global.Player = {
    init: function (opts) { hooks = opts || {}; },
    play: play, toggle: toggle, stop: stop, next: next, prev: prev, seek: seek,
    setVolume: function (v) { vol = v; applyVolume(); },
    setLoop: function (on) { looping = !!on; },
    isPlaying: function () { return playing; },
    fmt: fmt
  };
})(window);
