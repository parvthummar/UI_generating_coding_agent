import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';

const dist = path.resolve(process.argv[2] || '');

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
].join('; ');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8',
  '.woff2': 'font/woff2',
  '.png': 'image/png',
};

function isBenign(text) {
  return /content security policy|refused to (connect|load|get)|failed to load resource|net::ERR_|ERR_BLOCKED|favicon\.ico|downloadable font|ResizeObserver loop/i.test(
    String(text || ''),
  );
}

function startServer(root) {
  const server = http.createServer((req, res) => {
    let pathname = '/';
    try {
      pathname = decodeURIComponent(new URL(req.url || '/', 'http://127.0.0.1').pathname);
    } catch {
      res.writeHead(400);
      res.end('bad path');
      return;
    }
    if (pathname === '/') pathname = '/index.html';
    const file = path.normalize(path.join(root, pathname));
    const rootNorm = path.normalize(root);
    if (file !== rootNorm && !file.startsWith(rootNorm + path.sep)) {
      res.writeHead(403);
      res.end('forbidden');
      return;
    }
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404);
      res.end('not found');
      return;
    }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(file)] || 'application/octet-stream',
      'Content-Security-Policy': CONTENT_SECURITY_POLICY,
      'Cache-Control': 'no-store',
    });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

function fail(lines) {
  console.log('SMOKE_FAIL');
  for (const line of lines) {
    if (line) console.log(line);
  }
  process.exitCode = 1;
}

if (!dist || !fs.existsSync(path.join(dist, 'index.html'))) {
  fail(['Staged dist is missing index.html.']);
  process.exit(1);
}

const server = await startServer(dist);
const address = server.address();
const port = address && typeof address === 'object' ? address.port : 0;
let browser;
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', (err) => {
    const text = err && err.stack ? String(err.stack) : String(err);
    if (!isBenign(text)) pageErrors.push(text);
  });
  page.on('requestfailed', () => {});
  await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(600);
  const state = await page.evaluate(() => {
    const root = document.getElementById('root');
    const text = document.body ? document.body.innerText || '' : '';
    const mounted = !!(root && (root.childElementCount > 0 || (root.textContent || '').trim().length > 0));
    return {
      mounted,
      crashed: text.includes('This preview crashed'),
      snippet: text.slice(0, 800),
    };
  });
  if (state.crashed || pageErrors.length > 0 || !state.mounted) {
    const lines = [];
    if (state.crashed) lines.push(state.snippet);
    if (!state.mounted) lines.push('React did not mount any UI into #root.');
    for (const err of pageErrors.slice(0, 4)) lines.push(err.split('\n').slice(0, 8).join('\n'));
    fail(lines);
  } else {
    console.log('SMOKE_OK');
  }
} catch (err) {
  const message = err && err.message ? String(err.message) : String(err);
  const hint = /executable|browserType|chromium/i.test(message)
    ? 'Install the browser with: npx playwright install chromium'
    : '';
  fail([message.split('\n')[0], hint]);
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
