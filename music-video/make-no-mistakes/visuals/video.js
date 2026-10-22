/* Make No Mistakes: music video renderer.
 *
 * Every frame is a pure function of time: MNM.draw(t). The audio build exports
 * timing.json (sections, per-word lyric timings, drum hits, sound effects) and
 * features.json (per-frame loudness, kick/snare envelopes, spectrum), so the
 * picture lands on the same beats and syllables as the song.
 */
(() => {
  'use strict';

  const W = 1920, H = 1080;
  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');

  const C = {
    bg0: '#06070e', bg1: '#0d1024', navy: '#1a1f3d', violet: '#7c5cff', deep: '#5f3dc4',
    pink: '#ff4fa3', cyan: '#3ee6ff', green: '#43f59a', red: '#ff4d5e', amber: '#ffb547',
    white: '#f4f2ff', dim: '#8d8aa8', faint: '#4a4870',
  };
  const DISPLAY = '"Inter Display", Inter, sans-serif';
  const UI = 'Inter, sans-serif';
  const MONO = '"JetBrains Mono", monospace';
  const EMOJI = '"Noto Color Emoji"';

  let T = null, F = null;
  const lines = {};

  // ------------------------------------------------------------ math

  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, k) => a + (b - a) * k;
  const inv = (a, b, x) => clamp((x - a) / (b - a));
  const easeOut = (k) => 1 - Math.pow(1 - k, 3);
  const easeIn = (k) => k * k * k;
  const easeInOut = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
  const easeBack = (k) => 1 + 2.7 * Math.pow(k - 1, 3) + 1.7 * Math.pow(k - 1, 2);
  const hash = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
  const BEAT = 0.5;

  function feat(name, t) {
    const a = F[name], f = t * F.fps, i = Math.floor(f);
    if (i < 0) return 0;
    if (i >= a.length - 1) return a[a.length - 1] / 100;
    return lerp(a[i], a[i + 1], f - i) / 100;
  }
  const spectrum = (t) => F.spectrum[clamp(Math.round(t * F.fps), 0, F.spectrum.length - 1)];
  const kick = (t) => feat('kick', t);
  const snare = (t) => feat('snare', t);

  function sectionAt(t) {
    for (const s of T.sections) if (t >= s.t0 && t < s.t1) return s;
    return T.sections[T.sections.length - 1];
  }
  const get = (section, kind) => lines[section + ':' + kind] || [];
  const clean = (w) => w.replace(/[.,!]/g, '');

  // ------------------------------------------------------------ drawing helpers

  function font(weight, size, family = UI) { ctx.font = `${weight} ${size}px ${family}`; }

  function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }

  function glowText(str, x, y, color, glow, blur) {
    ctx.save();
    ctx.shadowColor = glow;
    ctx.shadowBlur = blur;
    ctx.fillStyle = color;
    ctx.fillText(str, x, y);
    ctx.restore();
  }

  // Emoji are rasterised once at the font's native bitmap size, then drawn as
  // sprites; large colour-bitmap glyphs drawn directly come out faint.
  const sprites = {};
  function sprite(ch) {
    if (!sprites[ch]) {
      const c = document.createElement('canvas');
      c.width = c.height = 160;
      const g = c.getContext('2d');
      g.font = `128px ${EMOJI}`;
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(ch, 80, 86);
      sprites[ch] = c;
    }
    return sprites[ch];
  }

  function emoji(ch, x, y, size, rot = 0, alpha = 1) {
    ctx.save();
    ctx.globalAlpha *= alpha;
    ctx.translate(x, y);
    ctx.rotate(rot);
    const s = size / 128;
    ctx.drawImage(sprite(ch), -80 * s, -80 * s, 160 * s, 160 * s);
    ctx.restore();
  }

  function cross(x, y, r, color, w = 4) {
    ctx.strokeStyle = color; ctx.lineWidth = w; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r);
    ctx.moveTo(x + r, y - r); ctx.lineTo(x - r, y + r); ctx.stroke();
  }

  function check(x, y, r, color, w = 4, k = 1) {
    ctx.strokeStyle = color; ctx.lineWidth = w; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    const p = [[x - r, y], [x - r * 0.3, y + r * 0.7], [x + r, y - r * 0.8]];
    ctx.beginPath(); ctx.moveTo(p[0][0], p[0][1]);
    const a = clamp(k * 2), b = clamp(k * 2 - 1);
    ctx.lineTo(lerp(p[0][0], p[1][0], a), lerp(p[0][1], p[1][1], a));
    if (b > 0) ctx.lineTo(lerp(p[1][0], p[2][0], b), lerp(p[1][1], p[2][1], b));
    ctx.stroke();
  }

  function sparkle(x, y, r, color, alpha) {
    ctx.save();
    ctx.globalAlpha *= alpha;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.quadraticCurveTo(x, y, x, y + r);
    ctx.quadraticCurveTo(x, y, x - r, y);
    ctx.quadraticCurveTo(x, y, x, y - r);
    ctx.fill();
    ctx.restore();
  }

  function sparkles(t, cx, cy, rx, ry, n, seed, color = '#fff', alpha = 1) {
    for (let i = 0; i < n; i++) {
      const ph = (t * (0.6 + hash(seed + i) * 0.8) + hash(seed + i * 3)) % 1;
      const a = Math.sin(ph * Math.PI);
      const x = cx + (hash(seed + i * 7) - 0.5) * 2 * rx;
      const y = cy + (hash(seed + i * 11) - 0.5) * 2 * ry - ph * 30;
      sparkle(x, y, 6 + 14 * hash(seed + i * 5) * a, color, a * alpha);
    }
  }

  function wrap(words, maxW, space) {
    const rows = [[]];
    let x = 0;
    for (const w of words) {
      const ww = ctx.measureText(w.s).width;
      if (x > 0 && x + ww > maxW) { rows.push([]); x = 0; }
      rows[rows.length - 1].push({ ...w, x, ww });
      x += ww + space;
    }
    const width = Math.max(...rows.map((r) => (r.length ? r[r.length - 1].x + r[r.length - 1].ww : 0)));
    return { rows, width };
  }

  // Shared off-screen canvases for post effects.
  const small = document.createElement('canvas'); small.width = 480; small.height = 270;
  const sctx = small.getContext('2d');
  const copy = document.createElement('canvas'); copy.width = W; copy.height = H;
  const cctx = copy.getContext('2d');
  const sunCanvas = document.createElement('canvas'); sunCanvas.width = 700; sunCanvas.height = 700;
  const sunCtx = sunCanvas.getContext('2d');
  const grain = document.createElement('canvas'); grain.width = 256; grain.height = 256;
  {
    const g = grain.getContext('2d'), img = g.createImageData(256, 256);
    for (let i = 0; i < 256 * 256; i++) {
      const v = Math.floor(hash(i * 0.731) * 255);
      img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v; img.data[i * 4 + 3] = 255;
    }
    g.putImageData(img, 0, 0);
  }

  // ------------------------------------------------------------ backgrounds

  function gradientBg(top, bottom) {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, top); g.addColorStop(1, bottom);
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  }

  function aurora(t, hues, strength = 1) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    hues.forEach((hue, i) => {
      const x = W * (0.2 + 0.6 * hash(i + 1)) + Math.sin(t * 0.11 + i * 2) * 260;
      const y = H * (0.25 + 0.5 * hash(i + 9)) + Math.cos(t * 0.13 + i) * 140;
      const r = 650 + 160 * Math.sin(t * 0.2 + i);
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, `hsla(${hue}, 85%, 55%, ${0.16 * strength})`);
      g.addColorStop(1, `hsla(${hue}, 85%, 55%, 0)`);
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    });
    ctx.restore();
  }

  function dotGrid(t, alpha, speed = 12, gap = 48, color = '170,160,255') {
    ctx.fillStyle = `rgba(${color},${alpha})`;
    const oy = (t * speed) % gap;
    for (let y = -gap + oy; y < H + gap; y += gap) {
      for (let x = gap / 2; x < W; x += gap) ctx.fillRect(x - 1, y - 1, 2.5, 2.5);
    }
  }

  const CODE = [
    'const app = await build({ startup: true });', 'if (bugs.length) fix(bugs);', 'deploy --prod --friday',
    'export default function scale() {', '  return pretty(fast(it));', '}', 'git commit -m "make no mistakes"',
    'assert(mistakes === 0);', 'npm run ship-it-tonight', '// TODO: one shot', 'while (!perfect) retry();',
    'model.generate(prompt, { temperature: 0 })', 'try { vibe(); } catch { apologize(); }', 'tests.forEach(run);',
    'loss.backward(); optimizer.step();', 'return absolutelyRight;',
  ];

  function codeRain(t, alpha, side = 'both') {
    font(500, 22, MONO);
    ctx.fillStyle = `rgba(150,140,230,${alpha})`;
    const cols = side === 'both' ? [60, 1560] : side === 'left' ? [60] : [1560];
    cols.forEach((x0, c) => {
      const speed = 26 + c * 9;
      const off = (t * speed) % 40;
      for (let i = -1; i < 29; i++) {
        const idx = Math.floor(i - Math.floor(t * speed / 40) + c * 7);
        const str = CODE[((idx % CODE.length) + CODE.length) % CODE.length];
        ctx.fillText(str, x0 + (hash(idx) - 0.5) * 30, i * 40 + off);
      }
    });
  }

  // Translucent app windows drifting upward behind the chat, for depth.
  function floaters(t, hue, alpha) {
    for (let i = 0; i < 9; i++) {
      const depth = 0.4 + 0.6 * hash(i * 4.3);
      const w = 260 + 380 * hash(i * 2.1) * depth, h = 160 + 240 * hash(i * 6.7) * depth;
      const x = hash(i * 1.9) * (W + 200) - 100;
      const y = ((hash(i * 3.3) * (H + 600) - t * 22 * depth) % (H + 600) + H + 600) % (H + 600) - 300;
      ctx.save();
      ctx.globalAlpha = alpha * depth;
      rr(x, y, w, h, 24);
      ctx.fillStyle = `hsla(${hue + 40 * hash(i)},70%,60%,0.05)`; ctx.fill();
      ctx.strokeStyle = `hsla(${hue + 40 * hash(i)},80%,70%,0.35)`; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = `hsla(${hue},80%,75%,0.25)`;
      for (let k = 0; k < 3; k++) ctx.fillRect(x + 24, y + 36 + k * 28, w * (0.3 + 0.4 * hash(i * 9 + k)), 8);
      ctx.restore();
    }
  }

  function vignette(strength = 0.6) {
    const g = ctx.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 0.95);
    g.addColorStop(0, 'rgba(0,0,0,0)');
    g.addColorStop(1, `rgba(0,0,0,${strength})`);
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  }

  function stars(t, n, alpha, maxY = H * 0.6) {
    for (let i = 0; i < n; i++) {
      const x = hash(i * 3.1) * W, y = hash(i * 5.7) * maxY;
      const tw = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(t * (1.5 + hash(i) * 3) + i));
      ctx.fillStyle = `rgba(255,255,255,${alpha * tw})`;
      const r = hash(i * 9.1) < 0.1 ? 2.4 : 1.4;
      ctx.fillRect(x, y, r, r);
    }
  }

  function synthwave(t, pal, opts = {}) {
    const horizon = opts.horizon ?? 620;
    const sky = ctx.createLinearGradient(0, 0, 0, horizon);
    sky.addColorStop(0, pal.sky0); sky.addColorStop(1, pal.sky1);
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, horizon);
    stars(t, 160, 0.8, horizon - 40);

    // sun with stripes, drawn off-screen so the stripes can be cut out
    const k = kick(t);
    const r = (opts.sunR ?? 250) * (1 + 0.025 * k);
    const sunY = opts.sunY ?? horizon - 70;
    sunCtx.clearRect(0, 0, 700, 700);
    const sg = sunCtx.createLinearGradient(0, 350 - r, 0, 350 + r);
    sg.addColorStop(0, pal.sun0); sg.addColorStop(1, pal.sun1);
    sunCtx.fillStyle = sg;
    sunCtx.beginPath(); sunCtx.arc(350, 350, r, 0, Math.PI * 2); sunCtx.fill();
    sunCtx.globalCompositeOperation = 'destination-out';
    for (let i = 0; i < 9; i++) {
      const yy = 350 + (i / 9) * r + ((t * 18) % (r / 9));
      const hh = 3 + (i / 9) * 16;
      sunCtx.fillRect(0, yy, 700, hh);
    }
    sunCtx.globalCompositeOperation = 'source-over';
    ctx.save();
    ctx.shadowColor = pal.sun1; ctx.shadowBlur = 90 + 40 * k;
    ctx.drawImage(sunCanvas, W / 2 - 350, sunY - 350);
    ctx.restore();

    // floor
    const fl = ctx.createLinearGradient(0, horizon, 0, H);
    fl.addColorStop(0, pal.floor0); fl.addColorStop(1, pal.floor1);
    ctx.fillStyle = fl; ctx.fillRect(0, horizon, W, H - horizon);
    const K = (H - horizon) * 0.55;
    const speed = opts.speed ?? 2;
    const bright = 0.55 + 0.45 * k;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (let pass = 0; pass < 2; pass++) {
      ctx.lineWidth = pass ? 2 : 7;
      const a = pass ? 0.85 : 0.18;
      for (let i = 0; i < 22; i++) {
        const z = 0.55 + i * 0.75 - ((t * speed) % 0.75);
        if (z <= 0.5) continue;
        const y = horizon + K / z;
        if (y > H + 10) continue;
        ctx.strokeStyle = `rgba(${pal.grid},${a * bright * clamp(1.6 - z / 10)})`;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      for (let j = -14; j <= 14; j++) {
        const xf = W / 2 + j * 1.6 * K / 0.55, xn = W / 2 + j * 1.6 * K / 18;
        ctx.strokeStyle = `rgba(${pal.grid},${a * bright * 0.8})`;
        ctx.beginPath(); ctx.moveTo(xn, horizon + K / 18); ctx.lineTo(xf, H + K * 0.2); ctx.stroke();
      }
    }
    ctx.restore();
    // horizon haze
    const hz = ctx.createLinearGradient(0, horizon - 60, 0, horizon + 50);
    hz.addColorStop(0, 'rgba(0,0,0,0)'); hz.addColorStop(0.5, pal.haze); hz.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = hz; ctx.fillRect(0, horizon - 60, W, 110);
  }

  const PAL = {
    chorus1: { sky0: '#05030f', sky1: '#2a0f45', sun0: '#ffd36e', sun1: '#ff4fa3', floor0: '#12052a', floor1: '#06030f', grid: '255,79,200', haze: 'rgba(255,79,163,0.35)', text: ['#ffffff', '#ffc4e6'], accent: C.pink },
    chorus2: { sky0: '#020a14', sky1: '#0b2547', sun0: '#7df9ff', sun1: '#7c5cff', floor0: '#05122a', floor1: '#02060f', grid: '62,230,255', haze: 'rgba(62,230,255,0.3)', text: ['#ffffff', '#bff7ff'], accent: C.cyan },
    final: { sky0: '#1a0624', sky1: '#ff7a59', sun0: '#fff1a8', sun1: '#ff8a3d', floor0: '#3a0f3d', floor1: '#12051a', grid: '255,190,120', haze: 'rgba(255,160,90,0.45)', text: ['#ffffff', '#fff3dc'], accent: 'rgba(255,120,60,0.9)', outline: 'rgba(48,6,40,0.92)' },
  };

  // ------------------------------------------------------------ terminal

  function terminal(t, x, y, w, h, rows, title = 'agent — ~/make-no-mistakes') {
    ctx.save();
    ctx.shadowColor = 'rgba(124,92,255,0.45)'; ctx.shadowBlur = 70;
    rr(x, y, w, h, 22); ctx.fillStyle = '#0b0d1a'; ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(124,92,255,0.55)'; ctx.stroke();
    rr(x, y, w, 58, [22, 22, 0, 0]); ctx.fillStyle = '#121528'; ctx.fill();
    ['#ff5f57', '#febc2e', '#28c840'].forEach((c, i) => {
      ctx.fillStyle = c; ctx.beginPath(); ctx.arc(x + 32 + i * 30, y + 29, 9, 0, 7); ctx.fill();
    });
    font(500, 22, MONO); ctx.fillStyle = C.dim; ctx.textAlign = 'center';
    ctx.fillText(title, x + w / 2, y + 37);
    ctx.textAlign = 'left';
    let yy = y + 120;
    for (const r of rows) {
      if (r.gap) { yy += r.gap; continue; }
      font(r.weight || 500, r.size || 34, MONO);
      let xx = x + 48 + (r.indent || 0);
      if (r.prefix) { ctx.fillStyle = r.prefixColor || C.violet; ctx.fillText(r.prefix, xx, yy); xx += ctx.measureText(r.prefix).width; }
      ctx.fillStyle = r.color || C.white;
      ctx.fillText(r.text, xx, yy);
      xx += ctx.measureText(r.text).width;
      if (r.cursor && (Math.floor(t * 2.6) % 2 === 0 || r.typing)) {
        ctx.fillStyle = C.white; ctx.fillRect(xx + 4, yy - 28, 18, 36);
      }
      yy += r.lh || 56;
    }
    ctx.restore();
  }

  function typed(entry, t) {
    const n = Math.floor((t - entry.t0) / entry.cps) + 1;
    return { text: entry.text.slice(0, clamp(n, 0, entry.text.length)), typing: n > 0 && n <= entry.text.length };
  }

  const SPIN = ['·', '✢', '✳', '✶', '✻', '✽', '✻', '✶', '✳', '✢'];

  function spokenSoFar(line, t) {
    return line.words.filter((w) => t >= w.t0 - 0.03).map((w) => w.w).join(' ');
  }

  // ------------------------------------------------------------ scenes

  const TASKS = [['write the lyrics', 6.9], ['compose the music', 7.08], ['learn to sing', 7.26], ['render the video', 7.44], ['make no mistakes', null]];

  function introRows(t) {
    const rows = [{ text: '✻ agent ready', color: C.dim, size: 28, lh: 76 }];
    const p1 = typed(T.typing[0], t), p2 = typed(T.typing[1], t);
    const done1 = t > T.typing[0].t0 + T.typing[0].text.length * T.typing[0].cps;
    rows.push({ prefix: '> ', text: p1.text, cursor: !done1 || t < T.typing[1].t0, typing: p1.typing, size: 42, lh: 66 });
    if (t >= T.typing[1].t0 - 0.4) rows.push({ prefix: '> ', text: p2.text, cursor: t < 3.9, typing: p2.typing, size: 42, lh: 66 });
    if (t >= 3.9 && t < 6.3) {
      const s = t - 3.9, tokens = Math.floor(80 + 900 * s * s);
      rows.push({ gap: 14 });
      rows.push({ prefix: SPIN[Math.floor(t * 12) % SPIN.length] + ' ', prefixColor: C.amber, text: `Thinking… (${s.toFixed(0)}s · ${tokens.toLocaleString('en-US')} tokens)`, color: C.amber, size: 34 });
    }
    const ai = get('intro', 'robot')[0];
    if (ai && t >= ai.t0 - 0.05) {
      rows.push({ gap: 14 });
      rows.push({ prefix: '● ', prefixColor: C.green, text: spokenSoFar(ai, t), size: 42, lh: 66 });
      if (t >= 6.62) {
        TASKS.forEach(([name, at], i) => {
          if (t < 6.62 + i * 0.07) return;
          const ok = at !== null && t >= at;
          rows.push({ prefix: ok ? '  ✓ ' : '  ☐ ', prefixColor: ok ? C.green : C.dim, text: name, color: ok ? C.dim : C.white, size: 34, lh: 52 });
        });
      }
    }
    return rows;
  }

  function sceneIntro(t) {
    gradientBg('#07081a', '#030308');
    aurora(t, [262, 300, 220], 0.9);
    dotGrid(t, 0.09);
    const appear = easeOut(inv(0, 0.7, t));
    const zoom = lerp(0.95, 1, appear) * (1 + 2.8 * easeIn(inv(7.5, 8.0, t)));
    ctx.save();
    ctx.globalAlpha = appear * (1 - inv(7.8, 8.0, t));
    ctx.translate(W / 2, H / 2); ctx.scale(zoom, zoom); ctx.translate(-W / 2, -H / 2);
    terminal(t, 300, 150, 1320, 780, introRows(t));
    ctx.restore();
  }

  // --- chat bubbles (verses)

  function chatStack(t, list, side, opts) {
    const maxW = opts.maxW, pad = 30, size = opts.size || 50, gap = 26;
    font(650, size);
    const lay = list.map((line) => {
      const words = line.words.map((w) => ({ ...w, s: w.w }));
      const L = wrap(words, maxW - 2 * pad, size * 0.28);
      return { line, L, h: L.rows.length * size * 1.28 + 2 * pad - size * 0.28, w: L.width + 2 * pad };
    });
    let offset = 0;
    for (let i = lay.length - 1; i >= 0; i--) {
      const it = lay[i], a0 = it.line.t0 - 0.35;
      const e = easeOut(inv(a0, a0 + 0.35, t));
      it.offset = offset;
      it.e = e;
      if (t >= a0) offset += (it.h + gap) * e;
    }
    // Each bubble sits above the ones that arrived after it.
    for (const it of lay) {
      if (t < it.line.t0 - 0.35) continue;
      drawBubble(t, it, side, opts, opts.bottom - it.offset - it.h);
    }
  }

  function drawBubble(t, it, side, opts, y) {
    const { line, L } = it;
    const size = opts.size || 50, pad = 30;
    const top = opts.top ?? 120;
    const fade = clamp((y - top + 60) / 160);
    if (fade <= 0) return;
    const x = side === 'right' ? opts.x - it.w : opts.x;
    const sc = lerp(0.9, 1, easeBack(it.e));
    ctx.save();
    ctx.globalAlpha *= fade * it.e;
    const base = ctx.globalAlpha;
    const ox = side === 'right' ? x + it.w : x, oy = y + it.h;
    ctx.translate(ox, oy); ctx.scale(sc, sc); ctx.translate(-ox, -oy);
    if (side === 'right') {
      const g = ctx.createLinearGradient(x, y, x + it.w, y + it.h);
      g.addColorStop(0, C.deep); g.addColorStop(1, C.violet);
      ctx.fillStyle = g;
      rr(x, y, it.w, it.h, [34, 34, 8, 34]); ctx.fill();
    } else {
      rr(x, y, it.w, it.h, [34, 34, 34, 8]);
      ctx.fillStyle = '#141734'; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(124,92,255,0.7)'; ctx.stroke();
    }
    // label
    font(600, 22, MONO); ctx.fillStyle = C.dim; ctx.textAlign = side === 'right' ? 'right' : 'left';
    ctx.fillText(side === 'right' ? 'you' : 'agent', side === 'right' ? x + it.w - 8 : x + 8, y - 12);
    ctx.textAlign = 'left';
    font(650, size);
    let first = Infinity;
    L.rows.forEach((row, ri) => row.forEach((w) => { first = Math.min(first, w.t0); }));
    if (t < first - 0.05) {
      for (let i = 0; i < 3; i++) {
        const b = 0.5 + 0.5 * Math.sin(t * 12 - i * 0.9);
        ctx.fillStyle = `rgba(255,255,255,${0.35 + 0.5 * b})`;
        ctx.beginPath(); ctx.arc(x + pad + 14 + i * 26, y + it.h / 2 - 4 * b, 8, 0, 7); ctx.fill();
      }
    }
    L.rows.forEach((row, ri) => {
      row.forEach((w) => {
        const k = inv(w.t0 - 0.06, w.t0 + 0.08, t);
        if (k <= 0) return;
        const active = t >= w.t0 && t < w.t1 + 0.04;
        const wx = x + pad + w.x, wy = y + pad + size * 0.82 + ri * size * 1.28 + (1 - easeOut(k)) * 12;
        ctx.globalAlpha = base * k;
        if (opts.wordStyle) opts.wordStyle(w, wx, wy, active, t);
        else if (active) glowText(w.s, wx, wy, '#ffffff', side === 'right' ? 'rgba(255,255,255,0.9)' : 'rgba(124,92,255,1)', 18);
        else { ctx.fillStyle = 'rgba(255,255,255,0.92)'; ctx.fillText(w.s, wx, wy); }
      });
    });
    ctx.restore();
  }

  const fmt = (n) => Math.floor(n).toLocaleString('en-US');
  const wordAt = (line, i) => line.words[Math.min(i, line.words.length - 1)];

  function panelLabel(str, x, y, color = C.dim) {
    font(600, 26, MONO); ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.fillText(str, x, y); ctx.textAlign = 'left';
  }

  function gagVerse1(t, ls) {
    const cx = 470;
    // 1: unicorn valuation
    const L1 = ls[0];
    if (L1) {
      const a = inv(L1.t0 - 0.4, L1.t0, t) * (1 - inv(L1.t1 + 0.3, L1.t1 + 0.6, t));
      if (a > 0) {
        ctx.save(); ctx.globalAlpha *= a;
        emoji('🦄', cx, 380 + Math.sin(t * 4) * 14, 210, Math.sin(t * 2) * 0.08);
        const p = easeIn(inv(L1.t0, wordAt(L1, 9).t0 + 0.2, t));
        panelLabel('VALUATION', cx, 560);
        font(900, 86, DISPLAY); ctx.textAlign = 'center';
        glowText('$' + fmt(1e9 * p), cx, 660, p >= 1 ? C.green : C.white, p >= 1 ? 'rgba(67,245,154,0.9)' : 'rgba(124,92,255,0.6)', 24);
        ctx.textAlign = 'left';
        ctx.restore();
      }
    }
    // 2: bug swarm
    const L2 = ls[1];
    if (L2) {
      const a = inv(L2.t0 - 0.3, L2.t0, t) * (1 - inv(L2.t1 + 0.2, L2.t1 + 0.5, t));
      if (a > 0) {
        ctx.save(); ctx.globalAlpha *= a;
        const p = inv(L2.t0, L2.t1 - 0.3, t);
        const n = Math.floor(4 + 150 * p * p);
        for (let i = 0; i < n; i++) {
          const bx = 80 + hash(i * 1.3) * 780 + Math.sin(t * (1 + hash(i)) + i) * 40;
          const by = 160 + hash(i * 2.9) * 760 + Math.cos(t * (1.2 + hash(i * 3)) + i) * 30;
          emoji('🐛', bx, by, 30 + 26 * hash(i * 7), Math.sin(t * 3 + i) * 0.6);
        }
        rr(cx - 260, 470, 520, 150, 24); ctx.fillStyle = 'rgba(6,7,14,0.82)'; ctx.fill();
        panelLabel('OPEN BUGS', cx, 520, C.red);
        font(900, 78, DISPLAY); ctx.textAlign = 'center';
        glowText(fmt(1e6 * Math.pow(p, 3)), cx, 600, C.red, 'rgba(255,77,94,0.8)', 20);
        ctx.textAlign = 'left';
        ctx.restore();
      }
    }
    // 3: pretty / fast / scale
    const L3 = ls[2];
    if (L3) {
      const a = inv(L3.t0 - 0.2, L3.t0, t) * (1 - inv(L3.t1 + 0.3, L3.t1 + 0.6, t));
      if (a > 0) {
        ctx.save(); ctx.globalAlpha *= a;
        const items = [[2, 'pretty', '✨', 330], [5, 'fast', '⚡', 540], [8, 'SCALE', '📈', 760]];
        items.forEach(([wi, label, em, y], k) => {
          const w = wordAt(L3, wi);
          const e = inv(w.t0 - 0.05, w.t0 + 0.15, t);
          if (e <= 0) return;
          ctx.save();
          ctx.globalAlpha *= e;
          const sc = k === 2 ? lerp(0.6, 1.25, easeOut(inv(w.t0, w.t1, t))) : easeBack(e);
          ctx.translate(cx, y); ctx.scale(sc, sc);
          font(900, 96, DISPLAY); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          if (k === 0) {
            const g = ctx.createLinearGradient(-200, 0, 200, 0);
            for (let i = 0; i <= 6; i++) g.addColorStop(i / 6, `hsl(${(i * 60 + t * 120) % 360},90%,70%)`);
            ctx.fillStyle = g; ctx.fillText(label, 0, 0);
            sparkles(t, 0, 0, 230, 70, 10, 50, '#fff', 1);
          } else if (k === 1) {
            for (let i = 0; i < 7; i++) {
              ctx.fillStyle = `rgba(62,230,255,${0.12 + 0.1 * hash(i)})`;
              ctx.fillRect(-330 - ((t * 900 + i * 120) % 300), -50 + i * 15, 180, 4);
            }
            glowText(label, 0, 0, C.cyan, 'rgba(62,230,255,0.9)', 22);
          } else {
            glowText(label, 0, 0, C.white, 'rgba(124,92,255,0.9)', 26);
          }
          emoji(em, k === 2 ? 210 : 190, -6, 64);
          ctx.restore();
        });
        ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        ctx.restore();
      }
    }
    // 4: first try
    const L4 = ls[3];
    if (L4) {
      const a = inv(L4.t0 - 0.2, L4.t0, t) * (1 - inv(L4.t1 + 0.1, L4.t1 + 0.45, t));
      if (a > 0) {
        ctx.save(); ctx.globalAlpha *= a;
        const base = ctx.globalAlpha;
        panelLabel('ATTEMPT 1 / 1', cx, 300);
        const w = wordAt(L4, 2);
        const e = inv(w.t0 - 0.05, w.t0 + 0.25, t);
        if (e > 0) {
          const r = 130 * easeBack(e);
          ctx.save(); ctx.shadowColor = 'rgba(67,245,154,0.9)'; ctx.shadowBlur = 40;
          ctx.strokeStyle = C.green; ctx.lineWidth = 12; ctx.beginPath(); ctx.arc(cx, 500, r, 0, 7); ctx.stroke();
          check(cx, 505, r * 0.55, C.green, 16, inv(w.t0, w.t0 + 0.3, t));
          ctx.restore();
        }
        const f = wordAt(L4, 7);
        const e2 = inv(f.t0 - 0.05, f.t0 + 0.2, t);
        if (e2 > 0) {
          ctx.globalAlpha = base * e2;
          font(900, 64, DISPLAY); ctx.textAlign = 'center';
          glowText('0 FAILURES', cx, 760, C.white, 'rgba(67,245,154,0.7)', 18);
          ctx.textAlign = 'left';
        }
        ctx.restore();
      }
    }
  }

  function sceneVerse1(t, s) {
    gradientBg('#0b0b22', '#040409');
    aurora(t, [262, 300, 230], 1.1);
    dotGrid(t, 0.07 + 0.08 * kick(t));
    floaters(t, 255, 0.9);
    codeRain(t, 0.07, 'right');
    const ls = get('verse1', 'lead');
    ctx.save();
    ctx.globalAlpha = inv(s.t0 - 0.01, s.t0 + 0.25, t);
    gagVerse1(t, ls);
    chatStack(t, ls, 'right', { x: 1790, bottom: 900, maxW: 900, size: 52 });
    ctx.restore();
  }

  // --- pre-choruses

  function tunnel(t, hue1, hue2, energy) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const k = kick(t);
    for (let i = 0; i < 14; i++) {
      const z = ((i / 14) + t * (0.12 + 0.25 * energy)) % 1;
      const sc = Math.pow(z, 2.2) * 2.4;
      const w = W * sc, h = H * sc;
      ctx.strokeStyle = `hsla(${lerp(hue1, hue2, z)},90%,62%,${(0.08 + 0.35 * z) * (1 - z) * (1 + k)})`;
      ctx.lineWidth = 2 + 6 * z;
      rr(W / 2 - w / 2, H / 2 - h / 2, w, h, 40 * sc + 10); ctx.stroke();
    }
    ctx.restore();
  }

  const BADGES = { pre1: [['🎓', 'senior'], ['🥇', '#1'], ['💸', '$200 tip']], pre2: [['⚠️', 'context'], ['🫠', 'lost'], ['❓', 'who?']] };

  function promptLines(t, ls, opts) {
    const base = ctx.globalAlpha;
    ls.forEach((line, i) => {
      if (t < line.t0 - 0.2) return;
      const y = opts.y0 + i * opts.dy;
      let a = inv(line.t0 - 0.2, line.t0, t);
      let dissolve = 0;
      if (opts.dissolve && i < ls.length - 1) dissolve = inv(ls[i + 1].t0 + 0.3, ls[i + 1].t0 + 1.6, t);
      if (opts.out) a *= 1 - inv(opts.out, opts.out + 0.25, t);
      if (a <= 0) return;
      a *= base;
      ctx.save();
      ctx.globalAlpha = a;
      font(600, opts.size, MONO);
      let x = opts.x;
      ctx.fillStyle = opts.prefixColor; ctx.fillText('> ', x, y);
      x += ctx.measureText('> ').width;
      for (const w of line.words) {
        const k = inv(w.t0 - 0.04, w.t0 + 0.06, t);
        if (k <= 0) break;
        const shown = w.w;
        const ww = ctx.measureText(shown + ' ').width;
        if (dissolve > 0) {
          for (let c = 0; c < shown.length; c++) {
            const ch = shown[c], cw = ctx.measureText(ch).width;
            const n = hash(i * 100 + c + x);
            ctx.globalAlpha = a * (1 - clamp(dissolve * 1.6 - n * 0.6));
            ctx.fillStyle = C.white;
            ctx.fillText(ch, x + (n - 0.5) * 220 * dissolve, y - dissolve * 160 * hash(c + 7 * i) + Math.sin(t * 3 + c) * 8 * dissolve);
            x += cw;
          }
          x += ctx.measureText(' ').width;
          continue;
        }
        const active = t >= w.t0 && t < w.t1;
        ctx.globalAlpha = a * k;
        if (active) glowText(shown, x, y, '#ffffff', opts.glow, 22); else { ctx.fillStyle = C.white; ctx.fillText(shown, x, y); }
        x += ww;
      }
      // badge
      const b = opts.badges && opts.badges[i];
      const last = line.words[line.words.length - 1];
      const e = inv(last.t0, last.t0 + 0.25, t);
      if (b && e > 0 && dissolve < 0.5) {
        ctx.globalAlpha = a * e * (1 - dissolve * 2);
        const bx = x + 30, by = y - opts.size * 0.75;
        font(700, 34, UI);
        const bw = ctx.measureText(b[1]).width + 110;
        ctx.save(); ctx.translate(bx, by + 30); ctx.scale(easeBack(e), easeBack(e));
        rr(0, -32, bw, 64, 32); ctx.fillStyle = 'rgba(255,255,255,0.1)'; ctx.fill();
        ctx.strokeStyle = opts.prefixColor; ctx.lineWidth = 2; ctx.stroke();
        emoji(b[0], 38, 1, 36);
        ctx.fillStyle = C.white; ctx.fillText(b[1], 70, 12);
        ctx.restore();
      }
      ctx.restore();
    });
  }

  function scenePre1(t, s) {
    const brk = 30;
    if (t < brk + 0.2) {
      gradientBg('#0a0718', '#040309');
      const energy = inv(24, 30, t);
      tunnel(t, 262, 330, energy);
      aurora(t, [300, 262], 0.6 + energy);
      ctx.save();
      ctx.globalAlpha = 1 - inv(brk, brk + 0.2, t);
      const z = 1 + 0.05 * energy + 0.015 * kick(t);
      ctx.translate(W / 2, H / 2); ctx.scale(z, z); ctx.translate(-W / 2, -H / 2);
      font(700, 30, MONO); ctx.fillStyle = C.dim; ctx.fillText('SYSTEM PROMPT', 250, 300);
      promptLines(t, get('pre1', 'lead'), { x: 250, y0: 420, dy: 150, size: 66, prefixColor: C.pink, glow: 'rgba(255,79,163,0.9)', badges: BADGES.pre1 });
      ctx.restore();
    }
    if (t >= brk) breakPrompt(t, get('pre1', 'spoken')[0], 'fire0');
  }

  function breakPrompt(t, line, style) {
    ctx.save();
    ctx.globalAlpha = Math.max(0.001, inv(30, 30.15, t));
    if (!line) { ctx.restore(); return; }
    font(700, 92, MONO);
    const full = '> ' + line.text.toLowerCase();
    const shown = '> ' + spokenSoFar(line, t).toLowerCase();
    const w = ctx.measureText(full).width;
    const x = W / 2 - w / 2, y = H / 2 + 30;
    const build = inv(line.t1, 32, t);
    ctx.fillStyle = `rgba(255,255,255,${0.04 + 0.1 * build})`;
    ctx.fillRect(0, 0, W, H);
    glowText(shown, x, y, '#ffffff', `rgba(255,79,163,${0.5 + 0.5 * build})`, 20 + 60 * build);
    const cw = ctx.measureText(shown).width;
    if (Math.floor(t * 2.6) % 2 === 0) { ctx.fillStyle = '#fff'; ctx.fillRect(x + cw + 8, y - 70, 46, 86); }
    ctx.restore();
  }

  function scenePre2(t, s) {
    const brk = 78;
    if (t < brk + 0.3) {
      gradientBg('#0b0712', '#040306');
      const energy = inv(72, 78, t);
      tunnel(t, 30, 0, energy * 0.7);
      ctx.save();
      ctx.globalAlpha = 1 - inv(brk, brk + 0.3, t);
      // token stream
      const toks = ['billion', 'bug', 'pretty', 'fast', 'scale', 'senior', '$200', 'tests', 'green', 'rm -rf', 'build', 'prompt', 'ship', 'tonight', 'heaven'];
      font(500, 30, MONO);
      for (let i = 0; i < 60; i++) {
        const sp = 200 + 500 * hash(i * 3) + 700 * energy;
        const x = W + 200 - ((t * sp + hash(i) * 3000) % (W + 400));
        const y = 140 + hash(i * 7) * 820;
        ctx.fillStyle = `rgba(255,181,71,${0.08 + 0.12 * hash(i * 5)})`;
        ctx.fillText(toks[i % toks.length], x, y);
      }
      // context meter
      const fill = lerp(0.82, 1.0, inv(72, 77.5, t));
      const mx = 260, my = 170, mw = 1400;
      font(700, 28, MONO); ctx.fillStyle = C.dim; ctx.fillText('CONTEXT WINDOW', mx, my - 22);
      const pct = Math.floor(fill * 100);
      ctx.textAlign = 'right'; ctx.fillStyle = fill > 0.95 ? C.red : C.amber;
      ctx.fillText(pct >= 100 ? '100% · compacting…' : pct + '%', mx + mw, my - 22); ctx.textAlign = 'left';
      rr(mx, my, mw, 34, 17); ctx.fillStyle = 'rgba(255,255,255,0.08)'; ctx.fill();
      const g = ctx.createLinearGradient(mx, 0, mx + mw, 0);
      g.addColorStop(0, C.violet); g.addColorStop(0.7, C.amber); g.addColorStop(1, C.red);
      rr(mx, my, mw * fill, 34, 17); ctx.fillStyle = g; ctx.fill();
      if (fill > 0.97 && Math.floor(t * 8) % 2) { rr(mx, my, mw * fill, 34, 17); ctx.fillStyle = 'rgba(255,77,94,0.5)'; ctx.fill(); }
      promptLines(t, get('pre2', 'lead'), { x: 260, y0: 430, dy: 150, size: 66, prefixColor: C.amber, glow: 'rgba(255,181,71,0.9)', badges: BADGES.pre2, dissolve: true });
      ctx.restore();
    }
    if (t >= brk) burnIn(t, get('pre2', 'robot')[0]);
  }

  function burnIn(t, line) {
    if (!line) return;
    ctx.fillStyle = '#020102'; ctx.globalAlpha = inv(78, 78.3, t); ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1;
    // embers
    for (let i = 0; i < 90; i++) {
      const life = (t * (0.25 + 0.3 * hash(i)) + hash(i * 3)) % 1;
      const x = W / 2 + (hash(i * 5) - 0.5) * 1300 + Math.sin(t * 2 + i) * 30;
      const y = 760 - life * 600;
      ctx.fillStyle = `rgba(255,${120 + 80 * hash(i)},40,${(1 - life) * 0.7 * inv(78, 78.6, t)})`;
      ctx.fillRect(x, y, 3, 3);
    }
    const ws = line.words;
    const remember = ws.filter((w) => !/make|no|mistakes/i.test(w.w));
    font(600, 44, MONO); ctx.textAlign = 'center';
    const r = remember.filter((w) => t >= w.t0 - 0.03).map((w) => w.w).join(' ');
    ctx.fillStyle = C.dim; ctx.fillText(r.toLowerCase(), W / 2, 420);
    const hook = ws.filter((w) => /make|no|mistakes/i.test(w.w));
    font(900, 150, DISPLAY);
    const shown = hook.filter((w) => t >= w.t0 - 0.03).map((w) => clean(w.w).toLowerCase()).join(' ');
    const flick = 0.75 + 0.25 * Math.sin(t * 37) * Math.sin(t * 23);
    const build = inv(79.2, 80, t);
    ctx.save();
    ctx.shadowColor = `rgba(255,${90 + 60 * flick},30,1)`; ctx.shadowBlur = 50 + 40 * flick + 80 * build;
    ctx.fillStyle = `rgb(255,${200 + 40 * flick},${150 + 80 * build})`;
    ctx.fillText(shown, W / 2, 620);
    ctx.shadowBlur = 0; ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = 0.35 * flick;
    ctx.fillStyle = '#ff7a2a'; ctx.fillText(shown, W / 2 + 3, 617);
    ctx.restore();
    ctx.textAlign = 'left';
  }

  // --- choruses

  function layoutBig(line, maxW, maxSize) {
    const words = line.words.map((w) => ({ ...w, s: clean(w.w).toUpperCase() }));
    let size = maxSize;
    font(900, size, DISPLAY);
    const total = () => words.reduce((a, w) => a + ctx.measureText(w.s).width, 0) + (words.length - 1) * size * 0.28;
    let rows = [words];
    if (total() > maxW) {
      // split into two balanced rows
      let best = 1, bestDiff = Infinity;
      for (let k = 1; k < words.length; k++) {
        const a = words.slice(0, k).reduce((s, w) => s + ctx.measureText(w.s).width, 0);
        const b = words.slice(k).reduce((s, w) => s + ctx.measureText(w.s).width, 0);
        if (Math.abs(a - b) < bestDiff) { bestDiff = Math.abs(a - b); best = k; }
      }
      rows = [words.slice(0, best), words.slice(best)];
      const widest = () => Math.max(...rows.map((r) => r.reduce((s, w) => s + ctx.measureText(w.s).width, 0) + (r.length - 1) * size * 0.28));
      while (widest() > maxW && size > 60) { size -= 6; font(900, size, DISPLAY); }
    }
    font(900, size, DISPLAY);
    const out = [];
    rows.forEach((r, ri) => {
      const rw = r.reduce((s, w) => s + ctx.measureText(w.s).width, 0) + (r.length - 1) * size * 0.28;
      let x = W / 2 - rw / 2;
      for (const w of r) {
        const ww = ctx.measureText(w.s).width;
        out.push({ ...w, x, ww, row: ri });
        x += ww + size * 0.28;
      }
    });
    return { words: out, size, rows: rows.length };
  }

  function bigLyrics(t, line, endT, pal, cy, opts = {}) {
    const lay = layoutBig(line, opts.maxW || 1650, opts.maxSize || 230);
    const size = lay.size;
    const lineH = size * 1.02;
    const top = cy - (lay.rows * lineH) / 2 + size * 0.78;
    const out = inv(endT, endT + 0.2, t);
    const k0 = kick(t);
    lay.words.forEach((w, i) => {
      const k = inv(w.t0 - 0.03, w.t0 + 0.12, t);
      if (k <= 0) return;
      const sc = lerp(1.5, 1, easeOut(k)) * (1 + 0.08 * out);
      const y = top + w.row * lineH;
      const cx = w.x + w.ww / 2, cyw = y - size * 0.36;
      ctx.save();
      ctx.globalAlpha = clamp(k * 1.6) * (1 - out);
      ctx.translate(cx, cyw); ctx.scale(sc, sc); ctx.translate(-cx, -cyw);
      font(900, size, DISPLAY);
      if (opts.draw && opts.draw(w, i, y, size, k, t)) { ctx.restore(); return; }
      const dx = (1 - k) * 22 + k0 * 5;
      ctx.globalCompositeOperation = 'lighter';
      ctx.fillStyle = 'rgba(255,40,90,0.75)'; ctx.fillText(w.s, w.x - dx, y);
      ctx.fillStyle = 'rgba(40,200,255,0.75)'; ctx.fillText(w.s, w.x + dx, y);
      ctx.globalCompositeOperation = 'source-over';
      const g = ctx.createLinearGradient(0, y - size * 0.8, 0, y);
      g.addColorStop(0, pal.text[0]); g.addColorStop(1, pal.text[1]);
      if (pal.outline) {
        // a dark outline keeps the words readable against a bright sky
        ctx.lineJoin = 'round'; ctx.lineWidth = size * 0.07; ctx.strokeStyle = pal.outline;
        ctx.shadowColor = pal.outline; ctx.shadowBlur = 40;
        ctx.strokeText(w.s, w.x, y);
      }
      ctx.shadowColor = pal.accent; ctx.shadowBlur = 30 + 30 * (t >= w.t0 && t < w.t1 ? 1 : 0);
      ctx.fillStyle = g; ctx.fillText(w.s, w.x, y);
      ctx.restore();
    });
    return lay;
  }

  function aiBubble(t, line, x, y) {
    const a0 = line.t0 - 0.12, a1 = line.t1 + 0.55;
    const e = inv(a0, a0 + 0.2, t) * (1 - inv(a1, a1 + 0.25, t));
    if (e <= 0) return;
    font(700, 48);
    const text = "You're absolutely right!";
    const tw = ctx.measureText(text).width;
    const w = tw + 150, h = 108;
    ctx.save();
    ctx.globalAlpha = e;
    const sc = easeBack(inv(a0, a0 + 0.25, t));
    ctx.translate(x + w, y + h); ctx.scale(sc, sc); ctx.translate(-(x + w), -(y + h));
    ctx.shadowColor = 'rgba(124,92,255,0.8)'; ctx.shadowBlur = 40;
    rr(x, y, w, h, [40, 40, 10, 40]); ctx.fillStyle = '#141734'; ctx.fill();
    ctx.shadowBlur = 0; ctx.lineWidth = 2.5; ctx.strokeStyle = C.violet; ctx.stroke();
    const og = ctx.createRadialGradient(x + 50, y + h / 2 - 8, 4, x + 52, y + h / 2, 26);
    og.addColorStop(0, '#fff'); og.addColorStop(0.4, C.pink); og.addColorStop(1, C.violet);
    ctx.fillStyle = og; ctx.beginPath(); ctx.arc(x + 52, y + h / 2, 24, 0, 7); ctx.fill();
    let xx = x + 96;
    for (const wd of line.words) {
      if (t < wd.t0 - 0.02) break;
      const s = wd.w.replace('!', '') + (wd === line.words[line.words.length - 1] ? '!' : '');
      const active = t >= wd.t0 && t < wd.t1;
      if (active) glowText(s, xx, y + 71, '#fff', C.pink, 16); else { ctx.fillStyle = C.white; ctx.fillText(s, xx, y + 71); }
      xx += ctx.measureText(s + ' ').width;
    }
    sparkles(t, x + w / 2, y + h / 2, w / 2 + 30, h, 8, 77, '#fff', 1);
    ctx.restore();
  }

  function rocket(t, t0, t1) {
    const p = inv(t0, t1, t);
    if (p <= 0 || p >= 1) return;
    const path = (q) => [lerp(-150, W + 150, q), lerp(H + 100, -150, q) + Math.sin(q * Math.PI) * -60];
    for (let i = 24; i > 0; i--) {
      const q = p - i * 0.012;
      if (q < 0) continue;
      const [x, y] = path(q);
      ctx.fillStyle = `rgba(255,${150 + i * 3},${60 + i * 5},${0.5 * (1 - i / 24)})`;
      ctx.beginPath(); ctx.arc(x + (hash(i + Math.floor(t * 30)) - 0.5) * 10, y, 28 - i * 0.8, 0, 7); ctx.fill();
    }
    const [x, y] = path(p);
    emoji('🚀', x, y, 230, 0);
  }

  function progress(t, a, b, label) {
    const e = inv(a - 0.2, a, t) * (1 - inv(b + 0.4, b + 0.6, t));
    if (e <= 0) return;
    const p = easeInOut(inv(a, b, t));
    const x = W / 2 - 450, y = 930;
    ctx.save(); ctx.globalAlpha = e;
    rr(x, y, 900, 26, 13); ctx.fillStyle = 'rgba(255,255,255,0.12)'; ctx.fill();
    const g = ctx.createLinearGradient(x, 0, x + 900, 0); g.addColorStop(0, C.violet); g.addColorStop(1, C.green);
    rr(x, y, Math.max(26, 900 * p), 26, 13); ctx.fillStyle = g; ctx.fill();
    font(600, 26, MONO); ctx.fillStyle = C.white;
    ctx.fillText(label, x, y - 16);
    ctx.textAlign = 'right'; ctx.fillText(Math.floor(p * 100) + '%', x + 900, y - 16); ctx.textAlign = 'left';
    ctx.restore();
  }

  function crosshair(t, t0, cx, cy) {
    const p = inv(t0 - 0.15, t0 + 0.45, t);
    const out = inv(t0 + 1.3, t0 + 1.7, t);
    if (p <= 0 || out >= 1) return;
    ctx.save();
    ctx.globalAlpha = (1 - out) * 0.9;
    ctx.strokeStyle = C.red; ctx.lineWidth = 4;
    const r = lerp(700, 170, easeOut(p));
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, r * 0.55, 0, 7); ctx.stroke();
    for (let i = 0; i < 4; i++) {
      const a = (i * Math.PI) / 2 + (1 - p) * 1.2;
      ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r * 0.75, cy + Math.sin(a) * r * 0.75);
      ctx.lineTo(cx + Math.cos(a) * r * 1.25, cy + Math.sin(a) * r * 1.25); ctx.stroke();
    }
    ctx.restore();
  }

  function rays(t, a, b, cx, cy, color, strength = 1) {
    const e = strength * inv(a - 0.2, a + 0.3, t) * (1 - inv(b, b + 0.4, t));
    if (e <= 0) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.translate(cx, cy);
    ctx.rotate(t * 0.25);
    for (let i = 0; i < 14; i++) {
      ctx.rotate((Math.PI * 2) / 14);
      const g = ctx.createLinearGradient(0, 0, 0, -1100);
      g.addColorStop(0, `rgba(${color},${0.22 * e})`); g.addColorStop(1, `rgba(${color},0)`);
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(-70, -1100); ctx.lineTo(70, -1100); ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }

  function confetti(t, n, alpha) {
    for (let i = 0; i < n; i++) {
      const sp = 120 + 160 * hash(i * 2);
      const y = ((t * sp + hash(i) * 1400) % (H + 120)) - 60;
      const x = hash(i * 3.3) * W + Math.sin(t * 2 + i) * 40;
      const rot = t * (2 + hash(i) * 3) + i;
      ctx.save(); ctx.globalAlpha = alpha; ctx.translate(x, y); ctx.rotate(rot);
      const kind = i % 3;
      if (kind === 0) check(0, 0, 12, C.green, 5);
      else if (kind === 1) cross(0, 0, 9, i % 2 ? C.amber : C.pink, 5);
      else { ctx.fillStyle = [C.violet, C.cyan, C.amber][i % 3]; ctx.fillRect(-8, -4, 16, 8); }
      ctx.restore();
    }
  }

  function sceneChorus(t, s) {
    const name = s.name;
    const pal = PAL[name];
    const final = name === 'final';
    const lift = final ? easeOut(inv(s.t0, s.t0 + 8, t)) : 0;
    synthwave(t, pal, { horizon: 640, sunY: 590 - 50 * lift, sunR: 250 + 40 * lift, speed: 2.2 });
    if (final) confetti(t, 70, 0.9);
    const ls = get(name, 'lead');
    const k = kick(t);
    const z = 1 + 0.018 * k;
    ctx.save();
    ctx.translate(W / 2, H / 2); ctx.scale(z, z); ctx.translate(-W / 2, -H / 2);
    ls.forEach((line, i) => {
      const next = ls[i + 1];
      const endT = next ? next.t0 - 0.16 : s.t1 - 0.3;
      if (t < line.t0 - 0.05 || t > endT + 0.25) return;
      // gags around the text; "BREAK" gets its crack in finalWord
      if (i === 1) progress(t, wordAt(line, 3).t0, line.t1 - 0.1, final ? 'breaking things on purpose…' : 'deploying to prod…');
      if (i === 2) {
        if (!final) crosshair(t, line.t0, W / 2, 420);
        rays(t, wordAt(line, 2).t0, line.t1, W / 2, 360, final ? '255,210,140' : name === 'chorus2' ? '160,240,255' : '255,200,240', final ? 0.6 : 1);
      }
      bigLyrics(t, line, endT, pal, 400, { draw: final ? finalWord : null });
      if (i === 1 && !final) rocket(t, line.t0, line.t0 + 1.9);
    });
    ctx.restore();
    get(name, 'backing').forEach((b) => aiBubble(t, b, 1040, 800));
  }

  function outlined(str, x, y, size) {
    ctx.save();
    ctx.lineJoin = 'round'; ctx.lineWidth = size * 0.07; ctx.strokeStyle = PAL.final.outline;
    ctx.shadowColor = PAL.final.outline; ctx.shadowBlur = 40;
    ctx.strokeText(str, x, y);
    ctx.restore();
    ctx.fillText(str, x, y);
  }

  function finalWord(w, i, y, size, k, t) {
    // "MAKE NEW MISTAKES": NO appears, is struck out and replaced by NEW
    if (w.s === 'NEW') {
      const strike = inv(w.t0 + 0.06, w.t0 + 0.2, t), pop = inv(w.t0 + 0.16, w.t0 + 0.34, t);
      ctx.save();
      ctx.fillStyle = `rgba(255,255,255,${1 - pop * 0.5})`;
      ctx.textAlign = 'left';
      outlined('NO', w.x + (w.ww - ctx.measureText('NO').width) / 2, y, size);
      if (strike > 0) {
        ctx.strokeStyle = C.red; ctx.lineWidth = size * 0.09; ctx.lineCap = 'round';
        const nw = ctx.measureText('NO').width, nx = w.x + (w.ww - nw) / 2;
        ctx.beginPath(); ctx.moveTo(nx - 10, y - size * 0.36); ctx.lineTo(nx - 10 + (nw + 20) * strike, y - size * 0.36 + 6); ctx.stroke();
      }
      if (pop > 0) {
        ctx.translate(w.x + w.ww / 2, y - size * 0.95);
        ctx.rotate(-0.08);
        ctx.scale(easeBack(pop) * 0.62, easeBack(pop) * 0.62);
        ctx.fillStyle = C.amber; ctx.textAlign = 'center';
        outlined('NEW', 0, 0, size);
      }
      ctx.restore();
      return true;
    }
    if (w.s === 'BREAK') {
      const crack = inv(w.t0 + 0.1, w.t0 + 0.3, t);
      ctx.save();
      const midX = w.x + w.ww / 2;
      for (const side of [-1, 1]) {
        ctx.save();
        ctx.beginPath();
        if (side < 0) { ctx.moveTo(w.x - 40, y - size); ctx.lineTo(midX + 20, y - size); ctx.lineTo(midX - 25, y - size * 0.45); ctx.lineTo(midX + 15, y - size * 0.1); ctx.lineTo(midX - 5, y + 40); ctx.lineTo(w.x - 40, y + 40); }
        else { ctx.moveTo(midX + 20, y - size); ctx.lineTo(w.x + w.ww + 40, y - size); ctx.lineTo(w.x + w.ww + 40, y + 40); ctx.lineTo(midX - 5, y + 40); ctx.lineTo(midX + 15, y - size * 0.1); ctx.lineTo(midX - 25, y - size * 0.45); }
        ctx.clip();
        ctx.translate(midX + side * 14 * crack, y - size * 0.4 + side * 6 * crack);
        ctx.rotate(side * 0.03 * crack);
        ctx.translate(-midX, -(y - size * 0.4));
        ctx.fillStyle = '#fff'; outlined('BREAK', w.x, y, size);
        ctx.restore();
      }
      ctx.restore();
      return true;
    }
    return false;
  }

  // --- post-choruses: tile grid driven by the vocal chops

  function scenePost(t, s) {
    const name = s.name;
    const warm = name === 'outro';
    const variant = name === 'post2' ? 1 : warm ? 2 : 0;
    gradientBg(variant === 1 ? '#03111c' : warm ? '#1a0812' : '#0c0516', '#020205');
    // diagonal stripes
    ctx.save();
    ctx.globalAlpha = 0.06;
    ctx.fillStyle = variant === 1 ? C.cyan : warm ? C.amber : C.pink;
    for (let i = -10; i < 30; i++) {
      const x = i * 120 + ((t * 120) % 120);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + 60, 0); ctx.lineTo(x + 60 - 700, H); ctx.lineTo(x - 700, H); ctx.fill();
    }
    ctx.restore();
    const cols = 4, rows = 3, gx = 70, gy = 70, gap = 26;
    const tw = (W - 2 * gx - (cols - 1) * gap) / cols, th = (H - 2 * gy - 120 - (rows - 1) * gap) / rows;
    const chops = get(name, 'chop');
    const hits = [];
    chops.forEach((line, li) => line.words.forEach((w, wi) => hits.push({ ...w, s: clean(w.w).toUpperCase(), li, wi })));
    const colors = variant === 1 ? [C.cyan, C.violet, '#ffffff'] : warm ? [C.amber, C.pink, '#ffffff'] : [C.pink, C.violet, '#ffffff'];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        const x = gx + c * (tw + gap), y = gy + r * (th + gap);
        let last = null, li = 0;
        hits.forEach((h, hi) => {
          let lit;
          if (h.s === 'MISTAKES') lit = h.t0 + (c + r) * 0.06;
          else lit = ((hi * 5 + 3 * Math.floor(hi / 7)) % 12) === idx ? h.t0 : null;
          if (lit !== null && t >= lit && (!last || lit > last.lit)) { last = { ...h, lit }; li = hi; }
        });
        const age = last ? t - last.lit : 99;
        const flash = Math.exp(-age / 0.22);
        rr(x, y, tw, th, 22);
        ctx.fillStyle = `rgba(255,255,255,${0.04 + 0.02 * kick(t)})`; ctx.fill();
        if (last && age < 3) {
          const col = colors[li % colors.length];
          const linger = Math.exp(-age / 0.7);
          ctx.save();
          ctx.globalAlpha = 0.85 * flash + 0.14 * linger;
          rr(x, y, tw, th, 22); ctx.fillStyle = col; ctx.fill();
          ctx.globalAlpha = 0.4 + 0.6 * Math.max(flash, linger);
          font(900, last.s.length > 4 ? 72 : 110, DISPLAY);
          ctx.textAlign = 'center';
          ctx.fillStyle = flash > 0.5 ? '#0b0b14' : col;
          ctx.fillText(last.s, x + tw / 2, y + th / 2 + (last.s.length > 4 ? 26 : 38));
          ctx.textAlign = 'left';
          ctx.globalAlpha = linger;
          ctx.shadowColor = col; ctx.shadowBlur = 30;
          ctx.strokeStyle = col; ctx.lineWidth = 4; rr(x, y, tw, th, 22); ctx.stroke();
          ctx.restore();
        }
        ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(255,255,255,0.12)'; rr(x, y, tw, th, 22); ctx.stroke();
      }
    }
    // spectrum
    const sp = spectrum(t);
    const bw = (W - 2 * gx) / sp.length;
    sp.forEach((v, i) => {
      const h = 6 + v * 0.9;
      ctx.fillStyle = colors[i % 2];
      ctx.globalAlpha = 0.85;
      rr(gx + i * bw + 4, H - 40 - h, bw - 8, h, 4); ctx.fill();
    });
    ctx.globalAlpha = 1;
    if (variant === 1) ticker(t);
    // outro: settle into the soft ending
    if (warm) outroSoft(t, s);
  }

  function ticker(t) {
    font(800, 34, MONO);
    const str = "YOU'RE ABSOLUTELY RIGHT ✦ ";
    const w = ctx.measureText(str).width;
    ctx.fillStyle = 'rgba(62,230,255,0.7)';
    for (let x = -((t * 220) % w); x < W; x += w) ctx.fillText(str, x, 46);
  }

  function outroSoft(t, s) {
    const e = inv(139.6, 140.6, t);
    if (e <= 0) return;
    ctx.save();
    ctx.globalAlpha = e;
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, '#2a0b2e'); g.addColorStop(1, '#0a0410');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    const sunY = 760 + 180 * inv(140, 144, t);
    const sg = ctx.createRadialGradient(W / 2, sunY, 10, W / 2, sunY, 600);
    sg.addColorStop(0, 'rgba(255,190,120,0.9)'); sg.addColorStop(0.3, 'rgba(255,120,120,0.35)'); sg.addColorStop(1, 'rgba(255,79,163,0)');
    ctx.fillStyle = sg; ctx.fillRect(0, 0, W, H);
    confetti(t, 30, 0.35 * (1 - inv(142, 144, t)));
    const line = get('outro', 'lead')[0];
    if (line) {
      font(300, 120, DISPLAY);
      ctx.textAlign = 'center';
      const words = line.words;
      const total = words.map((w) => clean(w.w).toLowerCase()).join(' ');
      const tw = ctx.measureText(total).width;
      let x = W / 2 - tw / 2;
      ctx.textAlign = 'left';
      for (const w of words) {
        const s2 = clean(w.w).toLowerCase();
        const k = inv(w.t0 - 0.05, w.t0 + 0.3, t);
        ctx.globalAlpha = e * k * (1 - inv(143.2, 143.9, t));
        glowText(s2, x, 520 + (1 - easeOut(k)) * 30, '#fff', 'rgba(255,180,120,0.8)', 30);
        x += ctx.measureText(s2 + ' ').width;
      }
    }
    ctx.restore();
  }

  // --- verse 2: the agent answers

  function diffPanel(t, x, y, a0, how) {
    const e0 = inv(a0, a0 + 0.35, t);
    if (e0 <= 0) return;
    const e = e0 * ctx.globalAlpha;
    ctx.save();
    ctx.globalAlpha = e;
    ctx.translate((1 - easeOut(e0)) * 120, 0);
    rr(x, y, 760, 420, 20); ctx.fillStyle = '#0d1020'; ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.12)'; ctx.lineWidth = 2; ctx.stroke();
    font(600, 24, MONO); ctx.fillStyle = C.dim; ctx.fillText('src/app.ts', x + 28, y + 44);
    const rows = [['-', 'if (user = null) return;'], ['+', 'if (user === null) return;'], [' ', ''], ['-', 'const total = price * qty'], ['+', 'const total = price * qty // ✓'], ['+', '// TODO: understand why this works']];
    rows.forEach(([sgn, code], i) => {
      const k = inv(a0 + 0.3 + i * 0.22, a0 + 0.45 + i * 0.22, t);
      if (k <= 0) return;
      const yy = y + 100 + i * 50;
      ctx.globalAlpha = e * k;
      if (sgn !== ' ') { ctx.fillStyle = sgn === '-' ? 'rgba(255,77,94,0.16)' : 'rgba(67,245,154,0.14)'; ctx.fillRect(x + 12, yy - 34, 736, 46); }
      font(500, 26, MONO);
      ctx.fillStyle = sgn === '-' ? C.red : sgn === '+' ? C.green : C.dim;
      ctx.fillText(sgn + ' ' + code, x + 28, yy);
    });
    if (how && t >= how.t0 - 0.05) {
      const p = inv(how.t0 - 0.05, how.t0 + 0.2, t);
      ctx.globalAlpha = e * p;
      ctx.translate(x + 380, y + 230); ctx.rotate(-0.06); ctx.scale(easeBack(p), easeBack(p));
      rr(-300, -80, 600, 150, 30); ctx.fillStyle = 'rgba(11,12,24,0.92)'; ctx.fill();
      font(800, 84, UI); ctx.textAlign = 'center'; ctx.fillStyle = C.amber;
      ctx.fillText('¯\\_(ツ)_/¯', 0, 28); ctx.textAlign = 'left';
    }
    ctx.restore();
  }

  function testPanel(t, x, y, line, whisper) {
    const red = wordAt(line, 3), green = wordAt(line, 7);
    const e0 = inv(line.t0 - 0.2, line.t0 + 0.2, t);
    if (e0 <= 0) return;
    const e = e0 * ctx.globalAlpha;
    const isGreen = t >= green.t0;
    ctx.save();
    ctx.globalAlpha = e;
    rr(x, y, 760, 470, 20); ctx.fillStyle = '#0d1020'; ctx.fill();
    ctx.strokeStyle = isGreen ? C.green : t >= red.t0 ? C.red : 'rgba(255,255,255,0.12)'; ctx.lineWidth = 3; ctx.stroke();
    font(700, 26, MONO); ctx.fillStyle = C.dim; ctx.fillText('TEST RESULTS', x + 28, y + 46);
    const names = ['auth › logs in', 'cart › totals', 'api › returns 200', 'db › migrates', 'ui › renders', 'billing › charges once'];
    if (!isGreen) {
      names.forEach((n, i) => {
        const k = inv(red.t0 + i * 0.06, red.t0 + 0.1 + i * 0.06, t);
        const yy = y + 100 + i * 50;
        if (t < red.t0) { ctx.globalAlpha = e * 0.5; font(500, 26, MONO); ctx.fillStyle = C.dim; ctx.fillText('○ ' + n, x + 28, yy); return; }
        ctx.globalAlpha = e * k;
        cross(x + 40, yy - 9, 9, C.red, 4);
        font(500, 26, MONO); ctx.fillStyle = C.white; ctx.fillText(n, x + 66, yy);
      });
      if (t >= red.t0) {
        ctx.globalAlpha = e * inv(red.t0, red.t0 + 0.2, t);
        font(900, 54, DISPLAY); ctx.fillStyle = C.red; ctx.fillText('12 failed', x + 28, y + 440);
      }
    } else {
      const p = inv(green.t0, green.t0 + 0.4, t);
      names.forEach((n, i) => {
        const yy = y + 100 + i * 50 - p * 60 * (1 + i * 0.4);
        ctx.globalAlpha = e * (1 - p);
        font(500, 26, MONO); ctx.fillStyle = C.white; ctx.fillText(n, x + 66 + p * 300 * hash(i), yy);
      });
      ctx.globalAlpha = e * p;
      ctx.save(); ctx.shadowColor = 'rgba(67,245,154,0.9)'; ctx.shadowBlur = 40;
      check(x + 380, y + 210, 70 * easeBack(p), C.green, 18, p);
      ctx.restore();
      font(900, 54, DISPLAY); ctx.fillStyle = C.green; ctx.textAlign = 'center';
      ctx.fillText('0 failed · 0 passed', x + 380, y + 400); ctx.textAlign = 'left';
    }
    if (whisper && t >= whisper.t0 - 0.1) {
      const k = inv(whisper.t0 - 0.1, whisper.t0 + 0.1, t);
      ctx.globalAlpha = e * k;
      const shake = (1 - inv(whisper.t0, whisper.t0 + 0.6, t)) * 6;
      rr(x, y + 490, 760, 70, 14); ctx.fillStyle = '#1a0a10'; ctx.fill();
      font(600, 30, MONO); ctx.fillStyle = C.red;
      const cmd = '$ rm -rf tests/';
      const n = Math.floor(inv(whisper.t0, whisper.t0 + 0.4, t) * cmd.length);
      ctx.fillText(cmd.slice(0, n), x + 28 + (hash(Math.floor(t * 40)) - 0.5) * shake, y + 536);
      font(400, 28, UI); ctx.fillStyle = C.dim; ctx.fillText('(i deleted them)', x + 470, y + 536);
    }
    ctx.restore();
  }

  function badge(t, cx, cy, a0) {
    const e = inv(a0, a0 + 0.3, t);
    if (e <= 0) return;
    ctx.save();
    ctx.globalAlpha *= e;
    ctx.translate(cx, cy); ctx.scale(easeBack(e) * 1.6, easeBack(e) * 1.6);
    font(700, 44, UI);
    const l = 'build', r = 'passing';
    const lw = ctx.measureText(l).width + 50, rw = ctx.measureText(r).width + 50, h = 74;
    const x = -(lw + rw) / 2;
    ctx.shadowColor = 'rgba(67,245,154,0.8)'; ctx.shadowBlur = 50;
    rr(x, -h / 2, lw + rw, h, 14); ctx.fillStyle = '#4c5161'; ctx.fill();
    ctx.shadowBlur = 0;
    rr(x + lw, -h / 2, rw, h, [0, 14, 14, 0]); ctx.fillStyle = '#2fbf71'; ctx.fill();
    ctx.fillStyle = '#fff'; ctx.fillText(l, x + 25, 15); ctx.fillText(r, x + lw + 25, 15);
    // shine
    const sh = ((t - a0) * 0.7) % 1.6 - 0.3;
    ctx.save(); rr(x, -h / 2, lw + rw, h, 14); ctx.clip();
    const g = ctx.createLinearGradient(x + sh * (lw + rw) - 60, 0, x + sh * (lw + rw) + 60, 0);
    g.addColorStop(0, 'rgba(255,255,255,0)'); g.addColorStop(0.5, 'rgba(255,255,255,0.45)'); g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g; ctx.fillRect(x, -h / 2, lw + rw, h);
    ctx.restore();
    ctx.restore();
    sparkles(t, cx, cy, 420, 160, 14, 91, '#fff', e);
  }

  function sceneVerse2(t, s) {
    gradientBg('#07101f', '#030407');
    aurora(t, [190, 262, 160], 1.0);
    dotGrid(t, 0.06 + 0.08 * kick(t), 10, 48, '120,220,255');
    floaters(t, 190, 0.8);
    codeRain(t, 0.06, 'left');
    const ls = get('verse2', 'lead');
    const wh = get('verse2', 'whisper')[0];
    ctx.save();
    ctx.globalAlpha = inv(s.t0 - 0.01, s.t0 + 0.25, t);
    // panels on the right, one per line
    const [L1, L2, L3, L4] = ls;
    const vis = (L, a, b) => inv(a, a + 0.3, t) * (1 - inv(b, b + 0.3, t));
    if (L1) {
      const a = vis(L1, L1.t0 - 0.3, L1.t1 + 0.4);
      if (a > 0) {
        ctx.save(); ctx.globalAlpha *= a;
        font(900, 120, DISPLAY); ctx.textAlign = 'center';
        const g = ctx.createLinearGradient(1060, 0, 1800, 0);
        for (let i = 0; i <= 6; i++) g.addColorStop(i / 6, `hsl(${(i * 60 + t * 140) % 360},90%,72%)`);
        ctx.fillStyle = g;
        const k = inv(wordAt(L1, 1).t0, wordAt(L1, 1).t0 + 0.2, t);
        ctx.globalAlpha *= k;
        ctx.fillText('absolutely', 1430, 470);
        font(800, 64, DISPLAY); ctx.fillStyle = C.white; ctx.fillText('right.', 1430, 560);
        ctx.textAlign = 'left';
        sparkles(t, 1430, 480, 380, 160, 16, 33, '#fff', k);
        ctx.restore();
      }
    }
    if (L2 && t < L2.t1 + 0.7) {
      ctx.save(); ctx.globalAlpha *= 1 - inv(L2.t1 + 0.3, L2.t1 + 0.6, t);
      diffPanel(t, 1050, 300, L2.t0 - 0.35, wordAt(L2, 7));
      ctx.restore();
    }
    if (L3 && t > L3.t0 - 0.3 && t < L3.t1 + 1.4) {
      ctx.save(); ctx.globalAlpha *= 1 - inv(L3.t1 + 1.0, L3.t1 + 1.3, t);
      testPanel(t, 1050, 230, L3, wh);
      ctx.restore();
    }
    if (L4 && t > L4.t0 - 0.3) {
      ctx.save(); ctx.globalAlpha *= 1 - inv(s.t1 - 0.3, s.t1, t);
      badge(t, 1420, 520, wordAt(L4, 2).t0 - 0.1);
      ctx.restore();
    }
    chatStack(t, ls, 'left', { x: 130, bottom: 900, maxW: 820, size: 50 });
    ctx.restore();
  }

  // --- bridge: how a model learns from mistakes

  const NET = [4, 6, 6, 3];
  function netNodes() {
    const out = [];
    NET.forEach((n, li) => {
      for (let i = 0; i < n; i++) out.push({ li, i, x: 560 + li * 270, y: 300 + (i - (n - 1) / 2) * 74 });
    });
    return out;
  }
  const NODES = netNodes();
  const HEART = [];
  for (let ring = 0; ring < 5; ring++) {
    const sc = 1 - ring * 0.17, n = Math.floor(80 * sc);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      const x = 16 * Math.pow(Math.sin(a), 3);
      const y = -(13 * Math.cos(a) - 5 * Math.cos(2 * a) - 2 * Math.cos(3 * a) - Math.cos(4 * a));
      HEART.push([W / 2 + x * 19 * sc, 440 + y * 19 * sc]);
    }
  }

  function sceneBridge(t, s) {
    gradientBg('#040a1c', '#02030a');
    aurora(t, [215, 250], 0.7);
    for (let i = 0; i < 80; i++) {
      const x = (hash(i * 1.7) * W + t * 8 * (hash(i) - 0.5) * 10) % W;
      const y = (hash(i * 4.1) * H - t * 6 * hash(i * 2)) % H;
      ctx.fillStyle = `rgba(160,190,255,${0.15 + 0.2 * hash(i * 9)})`;
      ctx.fillRect((x + W) % W, (y + H) % H, 2, 2);
    }
    const [L1, L2, L3, L4] = get('bridge', 'lead');
    const netFade = 1 - inv(116.0, 117.0, t);
    const build = inv(104.0, 106.5, t);
    const vox = feat('vox', t);
    // network
    if (netFade > 0) {
      ctx.save();
      ctx.globalAlpha = netFade * inv(s.t0, s.t0 + 0.5, t);
      for (const a of NODES) for (const b of NODES) {
        if (b.li !== a.li + 1) continue;
        const appear = inv(hash(a.i + b.i * 7 + a.li * 31) * 0.6, 0.6 + hash(a.i * 3 + b.i) * 0.4, build);
        if (appear <= 0) continue;
        ctx.strokeStyle = `rgba(124,150,255,${0.18 * appear})`; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        const ph = (t * 0.9 + hash(a.i * 13 + b.i * 5 + a.li)) % 1;
        ctx.fillStyle = `rgba(180,200,255,${0.8 * appear})`;
        ctx.fillRect(lerp(a.x, b.x, ph) - 2, lerp(a.y, b.y, ph) - 2, 4, 4);
      }
      NODES.forEach((n, i) => {
        const appear = inv(i / NODES.length * 0.8, i / NODES.length * 0.8 + 0.2, build);
        if (appear <= 0) return;
        const r = 16 + 6 * vox * hash(i + Math.floor(t * 4));
        ctx.save(); ctx.shadowColor = 'rgba(124,160,255,0.9)'; ctx.shadowBlur = 24;
        ctx.fillStyle = `rgba(200,215,255,${appear})`;
        ctx.beginPath(); ctx.arc(n.x, n.y, r * easeBack(appear), 0, 7); ctx.fill();
        ctx.restore();
      });
      ctx.restore();
    }
    // marks: wrong guesses, then corrected, then gathered into a heart
    const N = HEART.length;
    const p3 = L3 ? inv(L3.t0 + 0.2, L3.t1 - 0.4, t) : 0;
    for (let i = 0; i < N; i++) {
      const appear = L2 ? L2.t0 + hash(i * 1.1) * 3.4 : 999;
      if (t < appear) continue;
      const sx = 120 + hash(i * 2.3) * (W - 240), sy = 120 + hash(i * 3.7) * (H - 300);
      const g = L4 ? easeInOut(inv(L4.t0 + 0.2 + hash(i) * 0.9, L4.t0 + 1.6 + hash(i) * 0.9, t)) : 0;
      const [hx, hy] = HEART[i];
      const beat = g > 0.99 ? 1 + 0.06 * kick(t) + 0.04 * Math.sin(t * 6) : 1;
      const x = lerp(sx, W / 2 + (hx - W / 2) * beat, g), y = lerp(sy, 440 + (hy - 440) * beat, g);
      const fixed = hash(i * 5.5) < p3 || g > 0;
      const k = inv(appear, appear + 0.15, t);
      ctx.globalAlpha = k * (g > 0 ? 1 : 0.85);
      const r = lerp(9, 7, g) * easeBack(k);
      if (fixed) check(x, y, r, g > 0.5 ? '#ff6b9a' : C.green, 3.5);
      else cross(x, y, r, C.red, 3.5);
    }
    ctx.globalAlpha = 1;
    if (L2 && t >= L2.t0 && t < (L4 ? L4.t0 + 0.6 : 999)) {
      const a = inv(L2.t0, L2.t0 + 0.3, t) * (1 - inv(L4.t0, L4.t0 + 0.6, t));
      const p = inv(L2.t0, L2.t1, t);
      ctx.save(); ctx.globalAlpha = a;
      font(700, 30, MONO); ctx.fillStyle = C.dim; ctx.fillText('guesses', 140, 120);
      font(900, 54, DISPLAY); ctx.fillStyle = C.white; ctx.fillText(fmt(1e9 * Math.pow(p, 2)), 140, 180);
      font(700, 30, MONO); ctx.fillStyle = C.red; ctx.fillText('wrong', 1500, 120);
      font(900, 54, DISPLAY); ctx.fillText(fmt(1e9 * Math.pow(p, 2) * (1 - p3) * 0.999999), 1500, 180);
      ctx.restore();
    }
    // loss curve
    if (L3 && t >= L3.t0 - 0.3) {
      const a = inv(L3.t0 - 0.3, L3.t0, t) * (1 - inv(L4.t0, L4.t0 + 0.6, t));
      const x0 = 460, y0 = 580, w = 1000, h = 250;
      ctx.save(); ctx.globalAlpha = a;
      rr(x0 - 40, y0 - 40, w + 80, h + 90, 20); ctx.fillStyle = 'rgba(5,8,20,0.8)'; ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.3)'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0, y0 + h); ctx.lineTo(x0 + w, y0 + h); ctx.stroke();
      font(700, 26, MONO); ctx.fillStyle = C.dim; ctx.fillText('loss', x0 + 10, y0 + 6);
      ctx.fillText('steps →', x0 + w - 110, y0 + h + 34);
      const f = (u) => y0 + 10 + (h - 30) * (1 - Math.exp(-4.2 * u)) + Math.sin(u * 60) * 14 * Math.exp(-3 * u);
      // f(u) grows with u in screen space, i.e. the loss falls as training goes on
      ctx.strokeStyle = C.cyan; ctx.lineWidth = 5; ctx.shadowColor = C.cyan; ctx.shadowBlur = 20;
      ctx.beginPath();
      for (let i = 0; i <= 200 * p3; i++) {
        const u = i / 200;
        if (i === 0) ctx.moveTo(x0 + u * w, f(u)); else ctx.lineTo(x0 + u * w, f(u));
      }
      ctx.stroke();
      const u = p3, yy = f(u);
      ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(x0 + u * w, yy, 12, 0, 7); ctx.fill();
      ctx.restore();
    }
    // heart glow + captions
    if (L4) {
      const g = inv(L4.t0 + 1.2, L4.t0 + 2.6, t);
      if (g > 0) {
        const rg = ctx.createRadialGradient(W / 2, 430, 10, W / 2, 430, 520);
        rg.addColorStop(0, `rgba(255,107,154,${0.35 * g * (0.8 + 0.4 * kick(t))})`); rg.addColorStop(1, 'rgba(255,107,154,0)');
        ctx.fillStyle = rg; ctx.fillRect(0, 0, W, H);
      }
    }
    captions(t, [...get('bridge', 'lead'), ...get('bridge', 'spoken')], 985);
    const flash = inv(119.6, 120, t);
    if (flash > 0) { ctx.fillStyle = `rgba(255,240,220,${flash * 0.9})`; ctx.fillRect(0, 0, W, H); }
  }

  function captions(t, list, y) {
    for (const line of list) {
      if (t < line.t0 - 0.25 || t > line.t1 + 0.5) continue;
      const a = inv(line.t0 - 0.25, line.t0, t) * (1 - inv(line.t1 + 0.2, line.t1 + 0.5, t));
      font(600, 56);
      const words = line.words;
      const total = words.map((w) => w.w).join(' ');
      let x = W / 2 - ctx.measureText(total).width / 2;
      for (const w of words) {
        const sung = t >= w.t0;
        const active = sung && t < w.t1;
        ctx.globalAlpha = a * (sung ? 1 : 0.35);
        if (active) glowText(w.w, x, y, '#fff', 'rgba(150,180,255,1)', 18); else { ctx.fillStyle = C.white; ctx.fillText(w.w, x, y); }
        x += ctx.measureText(w.w + ' ').width;
      }
      ctx.globalAlpha = 1;
    }
  }

  // --- tag: the typo

  function sceneTag(t, s) {
    gradientBg('#07081a', '#030308');
    aurora(t, [262, 320], 0.6);
    dotGrid(t, 0.07);
    const robots = get('tag', 'robot');
    const user = get('tag', 'spoken')[0];
    const rows = [];
    const r0 = robots[0], r1 = robots[1], r2 = robots[2];
    if (r0 && t >= r0.t0 - 0.05) rows.push({ prefix: '● ', prefixColor: C.green, text: spokenSoFar(r0, t), size: 32, lh: 52 });
    if (r1 && t >= r1.t0 - 0.05) rows.push({ prefix: '● ', prefixColor: C.green, text: spokenSoFar(r1, t), size: 32, lh: 52 });
    const typo = T.typing[2];
    if (t >= typo.t0 - 0.3) {
      const p = typed(typo, t);
      rows.push({ gap: 8 });
      rows.push({ prefix: '> ', text: p.text, cursor: !r2 || t < r2.t0, typing: p.typing, size: 32, lh: 52 });
    }
    if (r2 && t >= r2.t0 - 0.05) rows.push({ prefix: '● ', prefixColor: C.green, text: spokenSoFar(r2, t), size: 32, lh: 52 });
    const fixT = 151.4;
    if (t >= fixT + 0.2) rows.push({ prefix: '  ✓ ', prefixColor: C.green, text: 'make no mistakes', color: C.dim, size: 30, lh: 48 });
    const fadeIn = inv(144, 144.4, t);
    const end = inv(153.4, 154.6, t);
    ctx.save();
    ctx.globalAlpha = fadeIn * (1 - end);
    terminal(t, 360, 560, 1200, 420, rows);
    // title card
    const ta = inv(146.6, 147.0, t);
    if (ta > 0) {
      ctx.globalAlpha = ta * (1 - end);
      const swap = easeInOut(inv(fixT, fixT + 0.4, t));
      const typoOn = t >= 148.15 && t < fixT;
      font(900, 150, DISPLAY);
      const pre = 'MAKE NO MIST';
      const preW = ctx.measureText(pre).width;
      const aW = ctx.measureText('A').width, eW = ctx.measureText('E').width;
      const total = ctx.measureText('MAKE NO MISTAKES').width;
      const x0 = W / 2 - total / 2, y0 = 360;
      const glow = 0.5 + 0.5 * inv(151.9, 152.2, t);
      ctx.save();
      ctx.shadowColor = `rgba(124,92,255,${glow})`; ctx.shadowBlur = 40 + 60 * inv(151.9, 152.3, t);
      ctx.fillStyle = '#fff';
      ctx.fillText(pre, x0, y0);
      // The typo "MISTAEKS" swaps its E and K back into "MISTAKES".
      const kW = ctx.measureText('K').width;
      const xa = x0 + preW;
      const ePos = lerp(xa + aW, xa + aW + kW, swap), kPos = lerp(xa + aW + eW, xa + aW, swap);
      const arc = Math.sin(swap * Math.PI) * 60;
      ctx.fillText('A', xa, y0);
      ctx.fillStyle = typoOn ? C.red : swap > 0 && swap < 1 ? C.amber : t > fixT + 0.4 && t < fixT + 1.2 ? C.green : '#fff';
      ctx.fillText('E', ePos, y0 - arc);
      ctx.fillText('K', kPos, y0 + arc);
      ctx.fillStyle = '#fff';
      ctx.fillText('S', xa + aW + eW + kW, y0);
      if (typoOn) {
        ctx.strokeStyle = C.red; ctx.lineWidth = 6; ctx.beginPath();
        for (let i = 0; i <= 30; i++) {
          const xx = xa + aW + (i / 30) * (eW + kW), yy = y0 + 26 + Math.sin(i * 1.6) * 7;
          if (i === 0) ctx.moveTo(xx, yy); else ctx.lineTo(xx, yy);
        }
        ctx.stroke();
      }
      ctx.restore();
      font(500, 34, MONO); ctx.fillStyle = C.dim; ctx.textAlign = 'center';
      ctx.fillText('a song written, composed, sung & animated by an AI', W / 2, 450);
      ctx.textAlign = 'left';
    }
    ctx.restore();
    if (end > 0) {
      ctx.fillStyle = `rgba(0,0,0,${end})`; ctx.fillRect(0, 0, W, H);
      ctx.globalAlpha = inv(153.6, 154.0, t) * (1 - inv(154.6, 155, t));
      font(500, 30, MONO); ctx.fillStyle = C.dim; ctx.textAlign = 'center';
      ctx.fillText('prompt: “make me a music video. make no mistakes.”', W / 2, H / 2);
      ctx.textAlign = 'left'; ctx.globalAlpha = 1;
    }
  }

  // ------------------------------------------------------------ post effects

  function bloom(strength) {
    if (strength <= 0) return;
    sctx.filter = 'brightness(0.75) contrast(2.2) blur(5px)';
    sctx.clearRect(0, 0, 480, 270);
    sctx.drawImage(canvas, 0, 0, 480, 270);
    sctx.filter = 'none';
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = strength;
    ctx.drawImage(small, 0, 0, W, H);
    ctx.restore();
  }

  function glitch(t, amount) {
    if (amount < 0.03) return;
    cctx.clearRect(0, 0, W, H);
    cctx.drawImage(canvas, 0, 0);
    const seed = Math.floor(t * 24);
    for (let i = 0; i < 9; i++) {
      const y = hash(seed * 13 + i) * H, h = 8 + hash(seed * 7 + i) * 90;
      const dx = (hash(seed * 3 + i * 11) - 0.5) * 160 * amount;
      ctx.drawImage(copy, 0, y, W, h, dx, y, W, h);
    }
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.18 * amount;
    ctx.drawImage(copy, 12 * amount, 0);
    ctx.restore();
  }

  function grainPass(t, alpha) {
    ctx.save();
    ctx.globalCompositeOperation = 'overlay';
    ctx.globalAlpha = alpha;
    const ox = Math.floor(hash(Math.floor(t * 30)) * 256), oy = Math.floor(hash(Math.floor(t * 30) + 5) * 256);
    for (let y = -oy; y < H; y += 256) for (let x = -ox; x < W; x += 256) ctx.drawImage(grain, x, y);
    ctx.restore();
  }

  const FLASHES = [[8.0, 0.8], [32.0, 1.0], [48.0, 0.35], [56.0, 0.3], [80.0, 1.0], [96.0, 0.35], [104.0, 0.4], [120.0, 1.0], [136.0, 0.3], [151.9, 0.7]];

  const SCENES = {
    intro: sceneIntro, verse1: sceneVerse1, pre1: scenePre1, chorus1: sceneChorus, post1: scenePost,
    verse2: sceneVerse2, pre2: scenePre2, chorus2: sceneChorus, post2: scenePost, bridge: sceneBridge,
    final: sceneChorus, outro: scenePost, tag: sceneTag,
  };
  const BLOOM = { intro: 0.25, verse1: 0.3, pre1: 0.45, chorus1: 0.45, post1: 0.5, verse2: 0.3, pre2: 0.45, chorus2: 0.45, post2: 0.5, bridge: 0.45, final: 0.4, outro: 0.45, tag: 0.3 };

  function draw(t) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
    ctx.shadowBlur = 0; ctx.filter = 'none'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = C.bg0; ctx.fillRect(0, 0, W, H);
    const s = sectionAt(t);
    SCENES[s.name](t, s);
    ctx.globalAlpha = 1;
    bloom(BLOOM[s.name] * (0.8 + 0.4 * feat('level', t)));
    if (s.name.startsWith('post') || (s.name === 'outro' && t < 140)) glitch(t, 0.25 * kick(t) + 0.6 * Math.max(0, snare(t) - 0.4));
    if (s.name.startsWith('chorus') || s.name === 'final') glitch(t, Math.max(0, kick(t) - 0.85) * 2);
    vignette(0.55);
    grainPass(t, 0.04);
    for (const [ft, strength] of FLASHES) {
      if (t >= ft && t < ft + 1) {
        ctx.fillStyle = `rgba(255,255,255,${strength * Math.exp(-(t - ft) / 0.16)})`;
        ctx.fillRect(0, 0, W, H);
      }
    }
    const fadeIn = 1 - inv(0, 0.35, t);
    if (fadeIn > 0) { ctx.fillStyle = `rgba(0,0,0,${fadeIn})`; ctx.fillRect(0, 0, W, H); }
  }

  async function init(timing, features) {
    T = timing; F = features;
    for (const k of Object.keys(lines)) delete lines[k];
    for (const l of T.lines) (lines[l.section + ':' + l.kind] ||= []).push(l);
    await Promise.all([
      document.fonts.load(`900 100px ${DISPLAY}`), document.fonts.load(`300 100px ${DISPLAY}`),
      document.fonts.load(`600 40px ${UI}`), document.fonts.load(`700 40px ${UI}`), document.fonts.load(`800 40px ${UI}`),
      document.fonts.load(`500 30px ${MONO}`), document.fonts.load(`700 30px ${MONO}`), document.fonts.load(`40px ${EMOJI}`, '🚀🐛🦄✨⚡📈🎓🥇💸⚠️🫠❓'),
    ]);
    // warm up glyph caches
    draw(0.5);
    return true;
  }

  window.MNM = { init, draw, W, H };
})();
