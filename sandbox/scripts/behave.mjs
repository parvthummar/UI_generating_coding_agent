import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';

const dist = path.resolve(process.argv[2] || '');
const scenario = process.argv[3] || '';

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
};

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

function report(kind, reason) {
  console.log(kind);
  if (reason) console.log(reason);
}

async function bodyText(page) {
  return page.locator('body').innerText();
}

async function todo(page) {
  const input = page.locator('input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), textarea').first();
  if ((await input.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No text field was found, so adding a task could not be checked.');
    return;
  }
  await input.fill('Buy milk');
  const add = page.getByRole('button', { name: /add|create|save|submit/i }).first();
  if ((await add.count()) > 0) await add.click();
  else await input.press('Enter');
  await page.waitForTimeout(300);
  const text = await bodyText(page);
  if (!text.includes('Buy milk')) {
    report('BEHAVE_FAIL', 'The entered task text did not appear.');
    return;
  }
  if (!/(left|remaining|to do|todo)[^\n]{0,40}\b1\b|\b1\b[^\n]{0,40}(left|remaining|task|item)/i.test(text)) {
    report('BEHAVE_INCONCLUSIVE', 'The task appeared, but no remaining-count text was recognized.');
    return;
  }
  report('BEHAVE_PASS', 'A task was added and a remaining count was visible.');
}

async function pomodoro(page) {
  const start = page.getByRole('button', { name: /start/i }).first();
  if ((await start.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No start control was found.');
    return;
  }
  const before = await bodyText(page);
  await start.click();
  await page.waitForTimeout(400);
  const pause = page.getByRole('button', { name: /pause/i }).first();
  const afterStart = await bodyText(page);
  const started = (await pause.count()) > 0 || afterStart !== before;
  if (!started) {
    report('BEHAVE_FAIL', 'Start did not change the timer or show a pause control.');
    return;
  }
  if ((await pause.count()) > 0) await pause.click();
  const reset = page.getByRole('button', { name: /reset/i }).first();
  if ((await reset.count()) > 0) await reset.click();
  report('BEHAVE_PASS', 'Start changed the timer, and pause or reset was available.');
}

async function kanban(page) {
  const move = page.getByRole('button', { name: /move|→|›|right|next/i }).first();
  if ((await move.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No move control was found.');
    return;
  }
  const before = await bodyText(page);
  await move.click();
  await page.waitForTimeout(300);
  const after = await bodyText(page);
  if (before === after) {
    report('BEHAVE_FAIL', 'The move control did not change the visible board.');
    return;
  }
  report('BEHAVE_PASS', 'The move control changed the visible board.');
}

async function weather(page) {
  const unit = page
    .locator('button, [role="switch"], [role="radio"]')
    .filter({ hasText: /celsius|fahrenheit|°\s*C|°\s*F|\bC\b|\bF\b/i })
    .first();
  if ((await unit.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No Celsius or Fahrenheit control was found.');
    return;
  }
  const before = await bodyText(page);
  await unit.click();
  await page.waitForTimeout(300);
  const after = await bodyText(page);
  const beforeC = /celsius|°\s*C/i.test(before);
  const beforeF = /fahrenheit|°\s*F/i.test(before);
  const afterC = /celsius|°\s*C/i.test(after);
  const afterF = /fahrenheit|°\s*F/i.test(after);
  if ((beforeC && afterF && !afterC) || (beforeF && afterC && !afterF)) {
    report('BEHAVE_PASS', 'The temperature unit switched.');
    return;
  }
  if (before === after) {
    report('BEHAVE_FAIL', 'The unit control did not change the visible text.');
    return;
  }
  report('BEHAVE_INCONCLUSIVE', 'The control changed the page, but the unit labels were not both recognized.');
}

const scenarios = { todo, pomodoro, kanban, weather };

if (!scenarios[scenario]) {
  report('BEHAVE_FAIL', 'Unknown interaction scenario.');
  process.exit(1);
}
if (!dist || !fs.existsSync(path.join(dist, 'index.html'))) {
  report('BEHAVE_FAIL', 'Staged dist is missing index.html.');
  process.exit(1);
}

const server = await startServer(dist);
const address = server.address();
const port = address && typeof address === 'object' ? address.port : 0;
let browser;
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(400);
  await scenarios[scenario](page);
} catch (err) {
  const message = err && err.message ? String(err.message) : String(err);
  report('BEHAVE_FAIL', message.split('\n')[0]);
} finally {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
