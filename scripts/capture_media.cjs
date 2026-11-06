#!/usr/bin/env node
/* Regenerates the README media from the static live demo:
 *   docs/report.png, docs/report-dark.png    the sample report's top, 2x
 *   docs/demo.gif, docs/demo-dark.gif        the live UI replay, looping
 *   docs/demo.mp4, docs/demo-dark.mp4        the same, as video
 *
 *   python scripts/build_demo_site.py /tmp/site
 *   node scripts/capture_media.cjs /tmp/site [docs]
 *
 * Needs playwright (npm i --no-save playwright; any Chromium or Chrome) and ffmpeg on PATH. */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const [site, out = path.join(__dirname, '..', 'docs')] = process.argv.slice(2);
if (!site) { console.error('usage: node scripts/capture_media.cjs SITE_DIR [OUT_DIR]'); process.exit(2); }

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  let rel = decodeURIComponent(req.url.split('?')[0]);
  if (rel.endsWith('/')) rel += 'index.html';
  const file = path.join(site, rel);
  if (!file.startsWith(path.resolve(site)) || !fs.existsSync(file)) { res.writeHead(404).end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' }).end(fs.readFileSync(file));
});

const VIEW = { width: 960, height: 740 };
const HOLD_MS = 2800;       // how long the finished report stays on screen before the loop restarts
const GIF_WIDTH = 880;

async function launch() {
  try { return await chromium.launch(); } catch (e) { return chromium.launch({ channel: 'chrome' }); }
}

async function reportShot(browser, base, scheme, file) {
  const ctx = await browser.newContext({ viewport: { width: 960, height: 900 }, deviceScaleFactor: 2, colorScheme: scheme, locale: 'en-US' });
  const page = await ctx.newPage();
  await page.goto(`${base}/sample-report.html`);
  await page.addStyleTag({ content: '.nav a{display:none}' });   // the links between pages mean nothing in a picture
  const bottom = await page.evaluate(() => document.querySelector('.hero').getBoundingClientRect().bottom);
  await page.screenshot({ path: file, clip: { x: 0, y: 0, width: 960, height: Math.ceil(bottom) + 32 } });
  await ctx.close();
}

async function recordDemo(browser, base, scheme, stem) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'whatsent-video-'));
  const started = Date.now();
  const ctx = await browser.newContext({
    // Playwright records video at the viewport's CSS size; a larger frame or a higher scale factor
    // leaves the page in one corner of a grey canvas.
    viewport: VIEW, colorScheme: scheme, locale: 'en-US',
    recordVideo: { dir, size: VIEW },
  });
  const page = await ctx.newPage();
  await page.goto(`${base}/demo/`);
  await page.waitForSelector('.win');
  const lead = (Date.now() - started) / 1000;
  await page.waitForFunction(() => /Export image/.test(document.body.innerText), null, { timeout: 60000 });
  await page.waitForTimeout(HOLD_MS);
  const length = (Date.now() - started) / 1000 - lead;
  const video = page.video();
  await ctx.close();
  const webm = path.join(dir, 'raw.webm');
  await video.saveAs(webm);   // waits until the recording is finished
  const palette = path.join(dir, 'palette.png');
  const cut = ['-ss', lead.toFixed(2), '-t', length.toFixed(2), '-i', webm];
  const scale = `scale=${GIF_WIDTH}:-2:flags=lanczos`;
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...cut, '-vf', `fps=12,${scale},palettegen=max_colors=96:stats_mode=diff`, palette]);
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...cut, '-i', palette, '-lavfi',
    `fps=12,${scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle`, '-loop', '0', path.join(out, `${stem}.gif`)]);
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...cut, '-vf', 'fps=30', '-c:v', 'libx264', '-crf', '23',
    '-preset', 'slow', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an', path.join(out, `${stem}.mp4`)]);
  fs.rmSync(dir, { recursive: true, force: true });
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await launch();
  try {
    await reportShot(browser, base, 'light', path.join(out, 'report.png'));
    await reportShot(browser, base, 'dark', path.join(out, 'report-dark.png'));
    await recordDemo(browser, base, 'light', 'demo');
    await recordDemo(browser, base, 'dark', 'demo-dark');
  } finally {
    await browser.close();
    server.close();
  }
  for (const f of fs.readdirSync(out).filter((n) => /^(report|demo).*\.(png|gif|mp4)$/.test(n))) {
    console.log(f.padEnd(18), (fs.statSync(path.join(out, f)).size / 1024).toFixed(0).padStart(6), 'KB');
  }
})().catch((e) => { console.error(e); process.exit(1); });
