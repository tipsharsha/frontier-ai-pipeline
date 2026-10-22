// Render the music video with headless Chromium, then mux it with the song.
//
//   node render_video.mjs                       full render -> build/make-no-mistakes.mp4
//   node render_video.mjs --sheet 1,8.5,33      contact sheet of those times -> build/sheet.png
//   node render_video.mjs --still 33            one full-size frame -> build/still-33.png
//
// Needs the playwright package (npm i playwright) and ffmpeg with libx264.
// BUILD_DIR points at the audio build output (song.wav, timing.json, features.json).

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const build = path.resolve(process.env.BUILD_DIR || path.join(here, 'build'));
const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf('--' + name);
  return i >= 0 ? args[i + 1] : dflt;
};

const timing = JSON.parse(fs.readFileSync(path.join(build, 'timing.json'), 'utf8'));
const features = JSON.parse(fs.readFileSync(path.join(build, 'features.json'), 'utf8'));
const FPS = timing.fps;

async function openPage(browser) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on('pageerror', (e) => console.error('page error:', e.message));
  await page.goto(pathToFileURL(path.join(here, 'visuals', 'index.html')).href);
  await page.evaluate(([t, f]) => window.MNM.init(t, f), [timing, features]);
  return page;
}

async function sheet(browser, times) {
  const page = await openPage(browser);
  const url = await page.evaluate((times) => {
    const cols = Math.min(4, times.length), rows = Math.ceil(times.length / cols);
    const w = 640, h = 360;
    const sheet = document.createElement('canvas');
    sheet.width = cols * w; sheet.height = rows * (h + 34);
    const s = sheet.getContext('2d');
    s.fillStyle = '#222'; s.fillRect(0, 0, sheet.width, sheet.height);
    const main = document.getElementById('c');
    times.forEach((t, i) => {
      window.MNM.draw(t);
      const x = (i % cols) * w, y = Math.floor(i / cols) * (h + 34);
      s.drawImage(main, x, y + 34, w, h);
      s.fillStyle = '#fff'; s.font = '600 22px monospace'; s.fillText(`t=${t.toFixed(2)}s`, x + 10, y + 25);
    });
    return sheet.toDataURL('image/png');
  }, times);
  const out = path.join(build, opt('out', 'sheet.png'));
  fs.writeFileSync(out, Buffer.from(url.split(',')[1], 'base64'));
  console.log('wrote', out);
}

async function still(browser, t) {
  const page = await openPage(browser);
  const url = await page.evaluate((t) => {
    window.MNM.draw(t);
    return document.getElementById('c').toDataURL('image/png');
  }, t);
  const out = path.join(build, opt('out', `still-${t}.png`));
  fs.writeFileSync(out, Buffer.from(url.split(',')[1], 'base64'));
  console.log('wrote', out);
}

async function renderFrames(browser) {
  const frames = path.join(build, 'frames');
  fs.mkdirSync(frames, { recursive: true });
  const total = Math.ceil(timing.length * FPS);
  const workers = Number(opt('workers', 3));
  const todo = [];
  for (let i = 0; i < total; i++) {
    if (!fs.existsSync(path.join(frames, `${String(i).padStart(5, '0')}.jpg`))) todo.push(i);
  }
  console.log(`${total} frames, ${todo.length} to render with ${workers} workers`);
  let next = 0, done = 0;
  const started = Date.now();
  await Promise.all(Array.from({ length: workers }, async () => {
    const page = await openPage(browser);
    while (next < todo.length) {
      const i = todo[next++];
      const url = await page.evaluate((t) => {
        window.MNM.draw(t);
        return document.getElementById('c').toDataURL('image/jpeg', 0.93);
      }, i / FPS);
      fs.writeFileSync(path.join(frames, `${String(i).padStart(5, '0')}.jpg`), Buffer.from(url.split(',')[1], 'base64'));
      if (++done % 300 === 0) {
        const rate = done / ((Date.now() - started) / 1000);
        console.log(`${done}/${todo.length} frames, ${rate.toFixed(1)} fps, ~${((todo.length - done) / rate / 60).toFixed(1)} min left`);
      }
    }
    await page.close();
  }));
  return frames;
}

function encode(frames) {
  const out = path.join(build, opt('out', 'make-no-mistakes.mp4'));
  const r = spawnSync('ffmpeg', [
    '-y', '-hide_banner', '-loglevel', 'error', '-stats',
    '-framerate', String(FPS), '-i', path.join(frames, '%05d.jpg'),
    '-i', path.join(build, 'song.wav'),
    '-c:v', 'libx264', '-preset', 'slow', '-crf', opt('crf', '19'), '-pix_fmt', 'yuv420p',
    '-profile:v', 'high', '-movflags', '+faststart',
    '-c:a', 'aac', '-b:a', '256k', '-ar', '48000',
    '-shortest', out,
  ], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error('ffmpeg failed');
  console.log('wrote', out);
}

const browser = await chromium.launch({ args: ['--force-color-profile=srgb', '--disable-lcd-text'] });
try {
  if (opt('sheet')) await sheet(browser, opt('sheet').split(',').map(Number));
  else if (opt('still')) await still(browser, Number(opt('still')));
  else encode(await renderFrames(browser));
} finally {
  await browser.close();
}
