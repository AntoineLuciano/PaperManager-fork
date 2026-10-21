#!/usr/bin/env node
/**
 * End-to-end smoke test of Knowledge Chat against a running PaperManager.
 *
 * Logs in, asks one question that should produce a concept card (written inline
 * by the model) and a 3D structure card, checks both render (the structure from
 * the backend's RCSB proxy, 3Dmol.js from /vendor), optionally runs the concept
 * pipeline on the answer (`--visualise`), then deletes the conversation again.
 *
 *   PM_BASE_URL=https://papers.example.org PM_USER=me PM_PASSWORD=... \
 *     node e2e/knowledge-chat.smoke.mjs [--visualise] [--model claude-code] [--shots DIR]
 *
 * Needs the `playwright` package and a Chromium for it (`npx playwright install chromium`).
 * If it is not installed in this project, point PLAYWRIGHT_NODE_MODULES at a
 * node_modules folder that has it. Exits non-zero on the first failed check.
 */
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };

const BASE = (process.env.PM_BASE_URL || 'http://localhost:5173').replace(/\/$/, '');
const USER = process.env.PM_USER;
const PASSWORD = process.env.PM_PASSWORD;
const MODEL = opt('--model', process.env.PM_MODEL || 'claude');
const SHOTS = opt('--shots', process.env.PM_SHOTS || '');
const ANSWER_TIMEOUT = 10 * 60_000;
const CARDS_TIMEOUT = 15 * 60_000;
if (!USER || !PASSWORD) { console.error('Set PM_USER and PM_PASSWORD.'); process.exit(2); }

async function loadPlaywright() {
  try { return await import('playwright'); } catch { /* fall through */ }
  const dir = process.env.PLAYWRIGHT_NODE_MODULES;
  if (!dir) throw new Error('playwright is not installed; set PLAYWRIGHT_NODE_MODULES');
  return createRequire(path.join(path.resolve(dir), 'noop.js'))('playwright');
}

const QUESTION =
  'Show ubiquitin (PDB 1UBQ) in 3D as a structure block with the Ile44 hydrophobic patch highlighted, ' +
  'and write the radius of gyration as a concept block (type formula) with two steps. Keep the prose short.';

const checks = [];
const check = (ok, what) => {
  checks.push({ ok, what });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`);
  if (!ok) throw new Error(what);
};

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
let conversationId = null;
const shot = async (name) => { if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await page.screenshot({ path: path.join(SHOTS, `${name}.png`) }); } };

try {
  await page.goto(`${BASE}/login`);
  await page.fill('input[placeholder="Enter your username"]', USER);
  await page.fill('input[placeholder="Enter your password"]', PASSWORD);
  await Promise.all([page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 30_000 }), page.click('button[type=submit]')]);
  check(true, 'logged in');

  await page.goto(`${BASE}/knowledge`);
  await page.waitForSelector('.kchat', { timeout: 30_000 });
  check(await page.isVisible('text=Ask your library anything.'), 'Knowledge Chat opens on the welcome');

  // The subscription option appears once the server says it is allowed for this user.
  await page.waitForSelector(`.kc-composer-bar select option[value="${MODEL}"]`, { state: 'attached', timeout: 10_000 }).catch(() => {});
  const models = await page.$$eval('.kc-composer-bar select option', (os) => os.map((o) => o.value));
  check(models.includes(MODEL), `model "${MODEL}" offered (${models.join(', ')})`);
  await page.selectOption('.kc-composer-bar select', MODEL);

  await page.fill('.kc-input textarea', QUESTION);
  await page.click('.kc-send');
  await page.waitForSelector('.msg.user .user-text', { timeout: 10_000 });
  check(true, 'question shown in the transcript');

  await page.waitForSelector('.msg.assistant .kc-answer-foot, .msg.assistant .kc-note.error', { timeout: ANSWER_TIMEOUT });
  const failed = await page.$('.msg.assistant .kc-note.error');
  check(!failed, `answer arrived${failed ? `: ${await failed.innerText()}` : ''}`);

  check(await page.locator('.msg.assistant .kc-concept').count() > 0, 'concept card rendered');
  check(await page.locator('.msg.assistant .kc-concept .katex').count() > 0, 'concept card shows typeset maths');

  await page.waitForSelector('.msg.assistant .structure .structure-chips, .msg.assistant .structure-err', { timeout: 90_000 });
  check(!(await page.$('.msg.assistant .structure-err')), 'structure loaded through the backend proxy');
  check(await page.locator('.msg.assistant .structure canvas').count() > 0, '3Dmol.js drew the structure');
  check(await page.evaluate(() => typeof window.$3Dmol === 'object'), '3Dmol.js came from /vendor (no CDN)');
  await page.locator('.msg.assistant .structure').first().scrollIntoViewIfNeeded();
  await shot('knowledge-chat-answer');

  if (flag('--visualise')) {
    await page.locator('.msg.assistant').last().locator('button:has-text("Visualise")').click();
    await page.waitForFunction(() => !document.querySelector('.kc-visualising'), null, { timeout: CARDS_TIMEOUT });
    const made = await page.locator('.kc-card-foot:has-text("made from this answer")').count();
    const note = await page.locator('.msg.assistant .kc-note').allInnerTexts();
    check(made > 0 || note.some((t) => /No idea in this answer/.test(t)), `concept pipeline finished (${made} cards)`);
    await shot('knowledge-chat-visualised');
  }

  check(errors.length === 0, `no page errors${errors.length ? `: ${errors[0]}` : ''}`);
} catch (e) {
  if (!checks.some((c) => !c.ok)) console.log(`FAIL ${e.message}`);
  process.exitCode = 1;
} finally {
  // The conversation this run made: the newest one titled with the question.
  const list = await page.request.get(`${BASE}/knowledge-chat/conversations`).then((r) => r.json()).catch(() => []);
  conversationId = Array.isArray(list) ? list.find((c) => QUESTION.startsWith(c.title.replace(/…$/, '')))?.id ?? null : null;
  if (conversationId) {
    const r = await page.request.delete(`${BASE}/knowledge-chat/conversations/${conversationId}`);
    console.log(`cleanup: deleted the test conversation (${r.status()})`);
  }
  await browser.close();
}
