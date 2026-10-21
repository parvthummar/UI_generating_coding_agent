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
  // Tasks may be rendered as list items or plain divs, so look for the visible text, not a tag.
  const beforeText = await bodyText(page);
  const beforeCount = remainingCount(beforeText);
  await input.fill('Buy milk');
  const add = page.getByRole('button', { name: /add|create|save|submit/i }).first();
  if ((await add.count()) > 0) await add.click();
  else await input.press('Enter');
  await page.waitForTimeout(300);
  const afterText = await bodyText(page);
  const afterCount = remainingCount(afterText);
  if (beforeText.includes('Buy milk') || !afterText.includes('Buy milk')) {
    report('BEHAVE_FAIL', 'The new task did not appear on the page.');
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
  const reset = page.getByRole('button', { name: /reset/i }).first();
  if ((await start.count()) === 0 || (await reset.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'Start and reset were not both found.');
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
  // Pause may be its own button or the start button relabeled as a toggle, so look for it now.
  const pause = page.getByRole('button', { name: /pause|stop/i }).first();
  if ((await pause.count()) === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No pause control was found while the timer was running.');
    return;
  }
  const pausedAt = clockValues(await bodyText(page))[0];
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

const MOVE_NAME = /\bmove\b|→|←|›|‹|»|«|➡|⬅|▶|◀|⇒|⇐|>|<|\bright\b|\bleft\b|\bnext\b|\bprev|\bback\b|\bforward\b/i;
const FORWARD_NAME = /→|›|»|➡|▶|⇒|>|right|next|forward/i;
const BACKWARD_NAME = /←|‹|«|⬅|◀|⇐|<|left|prev|back/i;

// Try forward moves first: a backward move on a card in the first column is a valid no-op.
function moveRank(name) {
  if (FORWARD_NAME.test(name)) return 0;
  if (!BACKWARD_NAME.test(name)) return 1;
  return 2;
}

// Center x of the card whose text, without its buttons, is exactly this label.
async function cardX(page, label) {
  return page.evaluate((wanted) => {
    function cleanText(el) {
      const copy = el.cloneNode(true);
      copy.querySelectorAll('button').forEach((button) => button.remove());
      return (copy.textContent || '').replace(/\s+/g, ' ').trim();
    }
    const all = Array.from(document.querySelectorAll('body *'));
    for (let index = all.length - 1; index >= 0; index -= 1) {
      if (cleanText(all[index]) === wanted) {
        const box = all[index].getBoundingClientRect();
        return box.left + box.width / 2;
      }
    }
    return null;
  }, label);
}

// The title of the card that holds this button: the first text outside buttons in its nearest ancestor with text.
// Only the title is tracked, because a card may show different badges or buttons in another column.
async function cardLabel(button) {
  return button.evaluate((btn) => {
    let box = btn.parentElement;
    while (box && box !== document.body) {
      const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node) {
        const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
        if (text && node.parentElement && !node.parentElement.closest('button')) return text;
        node = walker.nextNode();
      }
      box = box.parentElement;
    }
    return '';
  });
}

async function kanban(page) {
  const all = page.getByRole('button', { name: MOVE_NAME });
  const count = await all.count();
  if (count === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No move control was found.');
    return;
  }
  const ranked = [[], [], []];
  for (let index = 0; index < count; index += 1) {
    const name = (await all.nth(index).innerText()) + ' ' + ((await all.nth(index).getAttribute('aria-label')) || '');
    ranked[moveRank(name)].push(index);
  }
  const order = ranked[0].concat(ranked[1], ranked[2]);
  let tried = 0;
  for (const index of order.slice(0, 4)) {
    const button = all.nth(index);
    const label = await cardLabel(button);
    if (!label) continue;
    const before = await cardX(page, label);
    if (before == null) continue;
    tried += 1;
    await button.click();
    await page.waitForTimeout(300);
    const after = await cardX(page, label);
    if (after == null) {
      report('BEHAVE_FAIL', 'The card "' + label + '" disappeared instead of moving to another column.');
      return;
    }
    if (Math.abs(after - before) > 40) {
      report('BEHAVE_PASS', 'The card "' + label + '" moved to another column.');
      return;
    }
  }
  if (tried === 0) {
    report('BEHAVE_INCONCLUSIVE', 'No card could be tied to a move control.');
    return;
  }
  report('BEHAVE_FAIL', 'The card stayed in the same column after its move control was used.');
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
