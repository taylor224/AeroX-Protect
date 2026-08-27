/* Regenerate the README screenshots in docs/screenshots/.
 *
 * Usage:
 *   npm i playwright          # anywhere; also needs Google Chrome installed (H.264 in live view)
 *   AXP_URL=http://localhost:3000 AXP_ADMIN_ID=admin AXP_ADMIN_PW=... node docs/take-screenshots.js
 *
 * Side effects on the target instance: creates a DISABLED demo flow ("Person intrusion
 * alert") for the automation/flow-editor shots and deletes it afterwards. Nothing else is
 * modified.
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const BASE = process.env.AXP_URL || 'http://localhost:3000';
const API = (process.env.AXP_API_URL || 'http://localhost:10000') + '/api/v1';
const OUT = path.join(__dirname, 'screenshots');
const ADMIN = {
  login_id: process.env.AXP_ADMIN_ID || 'admin',
  password: process.env.AXP_ADMIN_PW || '',
};
if (!ADMIN.password) {
  console.error('AXP_ADMIN_PW is required');
  process.exit(1);
}

const DEMO_FLOW = {
  name: 'Person intrusion alert',
  enabled: false,
  graph: {
    nodes: [
      { id: 't', type: 'trigger', position: { x: 0, y: 180 },
        data: { sources: [{ trigger_type: 'object', classes: ['person'] }] } },
      { id: 'c', type: 'condition', position: { x: 320, y: 180 },
        data: { mode: 'all', clauses: [{ field: 'score', op: 'gte', value: 70 }] } },
      { id: 'p', type: 'push', position: { x: 660, y: 60 },
        data: { title: 'Person detected', body: '{{trigger.subtype}} @ camera {{trigger.camera_id}} (score {{trigger.score}})' } },
      { id: 'w', type: 'webhook', position: { x: 660, y: 300 },
        data: { url: 'https://example.com/nvr-hook', method: 'POST' } },
    ],
    edges: [
      { id: 't-c', source: 't', target: 'c', sourceHandle: 'out' },
      { id: 'c-p-true', source: 'c', target: 'p', sourceHandle: 'true' },
      { id: 'c-w-false', source: 'c', target: 'w', sourceHandle: 'false' },
    ],
  },
};

async function api(token, method, url, body) {
  const res = await fetch(API + url, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`${method} ${url} -> ${res.status} ${JSON.stringify(j).slice(0, 300)}`);
  return j.data;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  const auth = await api(null, 'POST', '/auth/login', ADMIN);
  const token = auth.access_token;
  const flow = await api(token, 'POST', '/flows', DEMO_FLOW);
  const flowUuid = flow.uuid || flow.id;

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log('shot:', name);
  };

  try {
    await page.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    await shot('login');
    await page.fill('#login_id', ADMIN.login_id);
    await page.fill('#password', ADMIN.password);
    await page.click('button[type=submit]');
    await page.waitForURL((u) => !u.pathname.includes('/auth/login'), { timeout: 15000 });

    const pages = [
      ['live', '/live', 20000],                       // let MSE/transcode deliver frames
      ['cameras', '/cameras', 5000],
      ['storage', '/storage', 3500],
      ['maps', '/maps', 5000],
      ['archive', '/archive', 3000],
      ['lpr', '/lpr', 3000],
      ['faces', '/faces', 3000],
      ['access', '/access', 3000],
      ['ai', '/ai', 4000],
      ['search', '/search', 3000],
      ['automation', '/rules', 3500],
      ['flow-editor', `/rules/flows/${flowUuid}`, 6000],
      ['monitors', '/monitors', 3000],
      ['users', '/users', 3000],
      ['settings', '/settings', 3500],
    ];
    for (const [name, route, wait] of pages) {
      await page.goto(BASE + route, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(wait);
      await shot(name);
    }

    // events: open the first camera's timeline over the last 24h so the recording
    // player and event markers are visible (not just the camera picker grid)
    await page.goto(`${BASE}/events`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(3000);
    const card = page.locator('main img, main [class*=card]').first();
    if (await card.count()) {
      await card.click();
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.getByText('최근 24h', { exact: false }).first().click().catch(() => {});
      await page.waitForTimeout(12000);           // timeline + first decoded frame
    }
    await shot('events');
  } finally {
    await browser.close();
    await api(token, 'DELETE', `/flows/${flowUuid}`).catch((e) => console.error('flow cleanup failed:', e.message));
    console.log('cleanup done');
  }
})();
