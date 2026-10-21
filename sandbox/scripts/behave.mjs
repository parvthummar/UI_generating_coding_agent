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

async function listItems(page) {
  const items = page.locator('li, [role="listitem"]');
  const count = await items.count();
  const texts = [];
  for (let index = 0; index < count; index += 1) {
    texts.push((await items.nth(index).innerText()).trim());
  }
  return texts;
}

function remainingCount(text) {
  const patterns = [
    /(\d+)\s*(?:tasks?|items?)?\s*(?:left|remaining)/i,
    /(?:left|remaining)[^\d]{0,24}(\d+)/i,
    /(\d+)\s*(?:to do|todos?)/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return Number(match[1]);
  }
  return null;
}

async function todo(page) {
  const input = page.locator('input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), textarea').first();
  if ((await input.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No text field was found, so adding a task could not be checked.');
    return;
  }
  const beforeItems = await listItems(page);
  const beforeCount = remainingCount(await bodyText(page));
  await input.fill('Buy milk');
  const add = page.getByRole('button', { name: /add|create|save|submit/i }).first();
  if ((await add.count()) > 0) await add.click();
  else await input.press('Enter');
  await page.waitForTimeout(300);
  const afterItems = await listItems(page);
  const afterCount = remainingCount(await bodyText(page));
  const listed = afterItems.some((item) => item.includes('Buy milk'));
  if (!listed) {
    report('BEHAVE_FAIL', 'The new task did not appear in the task list.');
    return;
  }
  if (afterItems.length !== beforeItems.length + 1) {
    report('BEHAVE_FAIL', 'The task list did not grow by one item.');
    return;
  }
  if (beforeCount == null || afterCount == null) {
    report('BEHAVE_INCONCLUSIVE', 'The task list grew, but a remaining count could not be read before and after.');
    return;
  }
  if (afterCount !== beforeCount + 1) {
    report('BEHAVE_FAIL', 'The remaining count changed from ' + beforeCount + ' to ' + afterCount + ' instead of increasing by one.');
    return;
  }
  report('BEHAVE_PASS', 'The task list grew and the remaining count increased from ' + beforeCount + ' to ' + afterCount + '.');
}

function clockValues(text) {
  const found = [];
  const pattern = /\b(\d{1,2}):(\d{2})\b/g;
  let match = pattern.exec(text);
  while (match) {
    found.push(Number(match[1]) * 60 + Number(match[2]));
    match = pattern.exec(text);
  }
  return found;
}

async function pomodoro(page) {
  const start = page.getByRole('button', { name: /start/i }).first();
  const pause = page.getByRole('button', { name: /pause/i }).first();
  const reset = page.getByRole('button', { name: /reset/i }).first();
  if ((await start.count()) === 0 || (await pause.count()) === 0 || (await reset.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'Start, pause, and reset were not all found.');
    return;
  }
  const initial = clockValues(await bodyText(page));
  if (initial.length === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No countdown value such as 25:00 was found.');
    return;
  }
  const startedAt = initial[0];
  await start.click();
  await page.waitForTimeout(1300);
  const running = clockValues(await bodyText(page));
  if (running.length === 0 || running[0] >= startedAt) {
    report('BEHAVE_FAIL', 'The countdown did not advance after start.');
    return;
  }
  const pausedAt = running[0];
  await pause.click();
  await page.waitForTimeout(1300);
  const held = clockValues(await bodyText(page));
  if (held.length === 0 || held[0] !== pausedAt) {
    report('BEHAVE_FAIL', 'Pause did not stop the countdown.');
    return;
  }
  await reset.click();
  await page.waitForTimeout(200);
  const restored = clockValues(await bodyText(page));
  if (restored.length === 0 || restored[0] !== startedAt) {
    report('BEHAVE_FAIL', 'Reset did not restore the initial countdown.');
    return;
  }
  report('BEHAVE_PASS', 'The countdown advanced, pause stopped it, and reset restored ' + startedAt + ' seconds.');
}

async function boardColumns(page) {
  return page.evaluate(() => {
    const heads = Array.from(document.querySelectorAll('h1, h2, h3, h4'));
    return heads.map((head) => {
      let box = head.parentElement;
      while (box && box.parentElement) {
        const parentHeads = box.parentElement.querySelectorAll('h1, h2, h3, h4');
        if (parentHeads.length > 1) break;
        box = box.parentElement;
      }
      const title = (head.textContent || '').trim();
      const cards = [];
      const items = box ? box.querySelectorAll('li, [role="listitem"]') : [];
      items.forEach((item) => {
        const copy = item.cloneNode(true);
        copy.querySelectorAll('button').forEach((button) => button.remove());
        const text = (copy.textContent || '').replace(/\s+/g, ' ').trim();
        if (text && text !== title) cards.push(text);
      });
      return { title, cards };
    });
  });
}

function cardColumn(columns, card) {
  const hits = [];
  columns.forEach((column, index) => {
    if (column.cards.some((line) => line.includes(card))) hits.push(index);
  });
  return hits;
}

async function kanban(page) {
  const before = await boardColumns(page);
  if (before.length < 2) {
    report('BEHAVE_INCONCLUSIVE', 'Fewer than two columns were found.');
    return;
  }
  let card = '';
  let from = -1;
  for (const column of before) {
    for (const line of column.cards) {
      const hits = cardColumn(before, line);
      if (hits.length === 1) {
        card = line;
        from = hits[0];
        break;
      }
    }
    if (card) break;
  }
  if (!card) {
    report('BEHAVE_INCONCLUSIVE', 'No card could be tied to a single column.');
    return;
  }
  const move = page
    .locator('h1, h2, h3, h4')
    .filter({ hasText: before[from].title })
    .locator('xpath=ancestor::*[.//button][1]')
    .getByRole('button', { name: /move|→|‹|›|left|right|next|back/i })
    .first();
  if ((await move.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No move control was found in the card column.');
    return;
  }
  await move.click();
  await page.waitForTimeout(300);
  const after = await boardColumns(page);
  const now = cardColumn(after, card);
  if (now.length === 0) {
    report('BEHAVE_FAIL', 'The card disappeared instead of moving to another column.');
    return;
  }
  if (now.length === 1 && now[0] === from) {
    report('BEHAVE_FAIL', 'The card stayed in the same column.');
    return;
  }
  if (!now.some((index) => index !== from)) {
    report('BEHAVE_FAIL', 'The card was not found in a different column.');
    return;
  }
  report('BEHAVE_PASS', 'The card moved from ' + before[from].title + ' to another column.');
}

function temperatureReading(text) {
  const labeled = text.match(/(-?\d+(?:\.\d+)?)\s*(?:°\s*)?(celsius|fahrenheit|°\s*[CFcf]|[CFcf])\b/i);
  if (!labeled) return { value: null, unit: '' };
  const unitText = labeled[2].toLowerCase();
  let unit = '';
  if (unitText.indexOf('c') === 0 || unitText.indexOf('°') === 0 && /c/i.test(unitText)) unit = 'C';
  if (unitText.startsWith('f') || /f/i.test(unitText)) unit = 'F';
  if (unitText.indexOf('celsius') === 0) unit = 'C';
  if (unitText.indexOf('fahrenheit') === 0) unit = 'F';
  return { value: Number(labeled[1]), unit };
}

async function weather(page) {
  const unit = page
    .locator('button, [role="switch"], [role="radio"]')
    .filter({ hasText: /celsius|fahrenheit|°\s*[CFcf]/i })
    .first();
  if ((await unit.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No Celsius or Fahrenheit control was found.');
    return;
  }
  const beforeText = await bodyText(page);
  const before = temperatureReading(beforeText);
  const labelBefore = (await unit.innerText()).trim();
  if (before.value == null && !before.unit) {
    report('BEHAVE_INCONCLUSIVE', 'A unit control exists, but no temperature value or unit was visible.');
    return;
  }
  await unit.click();
  await page.waitForTimeout(300);
  const after = temperatureReading(await bodyText(page));
  const labelAfter = (await unit.innerText()).trim();
  const unitChanged = (before.unit && after.unit && before.unit !== after.unit) || (labelBefore !== labelAfter && /celsius|fahrenheit|°/i.test(labelBefore + labelAfter));
  const valueChanged = before.value != null && after.value != null && Math.abs(before.value - after.value) > 0.2;
  if (unitChanged || valueChanged) {
    report('BEHAVE_PASS', 'The temperature unit or value changed.');
    return;
  }
  report('BEHAVE_INCONCLUSIVE', 'The unit control was used, but neither a unit nor a temperature value could be shown to change.');
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
