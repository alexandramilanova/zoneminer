import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

let analysisId: string;
test.beforeAll(async ({ request }) => {
  const demo = await (await request.get('/api/demo')).json();
  const response = await request.post('/api/datasets/demo/analyses', {
    data: { zones: demo.zones, timeframe: 'D' },
  });
  expect(response.ok()).toBeTruthy();
  const created = await response.json();
  analysisId = created.analysis_id;
  if (created.job_id) {
    await expect.poll(async () => (await (await request.get(`/api/jobs/${created.job_id}`)).json()).status,
      { timeout: 120_000 }).toBe('done');
  }
});
test.beforeEach(async ({ page }) => {
  await page.addInitScript((id) => localStorage.setItem('zone-analytics-current', id), analysisId);
  await page.goto('/#/');
  await expect(page.getByRole('textbox', { name: 'Zone 1 name', exact: true })).toBeVisible();
});

const run = (page: Page) => page.getByRole('button', { name: 'Run analysis', exact: true });
const validate = (page: Page) => page.getByRole('button', { name: 'Validate zones', exact: true });
const status = (page: Page) => page.getByRole('status').filter({ hasText: /Zone/ });
async function validated(page: Page) {
  await validate(page).click();
  await expect(status(page)).toHaveText('Zone system is valid.');
  await expect(run(page)).toBeEnabled();
}

test('edit, invalidate, revalidate and run the actual Docker analysis', async ({ page }) => {
  await expect(run(page)).toBeDisabled();
  await validated(page);
  await page.getByRole('textbox', { name: 'Zone 1 name', exact: true }).fill('Customer edited');
  await expect(status(page)).toContainText('not validated');
  await expect(run(page)).toBeDisabled();
  await expect(page.getByText('Configuration changed.', { exact: false })).toBeVisible();
  await validated(page);
  await run(page).click();
  await expect(page).toHaveURL(/#\/overview/);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
});

test('duplicate and blank drafts remain visible and are rejected without data loss', async ({ page }) => {
  const first = page.getByRole('textbox', { name: 'Zone 1 name', exact: true });
  const second = page.getByRole('textbox', { name: 'Zone 2 name', exact: true });
  await page.getByRole('combobox', { name: 'Active zone', exact: true }).selectOption('1');
  const secondName = await second.inputValue();
  await page.getByRole('combobox', { name: 'Active zone', exact: true }).selectOption('0');
  await first.fill(secondName);
  await validate(page).click();
  await expect(status(page)).toContainText('invalid.');
  await expect(page.getByText(/Duplicate names found/)).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveCount(1);
  await first.fill(' ');
  await validate(page).click();
  await expect(page.getByText(/Zone names cannot be empty/)).toBeVisible();
  await expect(first).toHaveValue(' ');
  await expect(page.getByRole('textbox')).toHaveCount(1);
  await expect(run(page)).toBeDisabled();
});

test('removing all zones rejects the empty system', async ({ page }) => {
  const remove = page.getByTitle('Remove zone', { exact: true });
  while (await remove.count()) await remove.first().click();
  await validate(page).click();
  await expect(page.getByText('Define at least one zone.', { exact: true })).toBeVisible();
  await expect(run(page)).toBeDisabled();
});

test('editing places invalidates success and preserves disconnected selections', async ({ page }) => {
  await validated(page);
  await page.getByRole('button', { name: 'Edit places', exact: true }).first().click();
  await page.getByRole('checkbox', { name: 'p_start', exact: true }).check();
  await expect(status(page)).toContainText('not validated');
  await expect(run(page)).toBeDisabled();
  await validated(page); // source place adjoins Customer Interaction
  await page.getByRole('checkbox', { name: 'p_end', exact: true }).check();
  await validate(page).click();
  await expect(page.getByText(/Disconnected zones found/)).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'p_end', exact: true })).toBeChecked();
});

test('late validation success cannot authorize an edited configuration', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/zones/validate', async (route) => {
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  const pending = page.waitForRequest('**/zones/validate');
  await validate(page).click();
  await pending;
  await page.getByRole('textbox', { name: 'Zone 1 name', exact: true }).fill('Changed during validation');
  release();
  await expect(validate(page)).toBeEnabled();
  await expect(status(page)).toContainText('not validated');
  await expect(run(page)).toBeDisabled();
});

const tour = (page: Page) => page.locator('.tour-tooltip[role=dialog]');
async function unobscured(page: Page) {
  await expect(tour(page)).toBeVisible();
  await expect.poll(() => tour(page).evaluate((el) => {
    const r = el.getBoundingClientRect();
    return r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1 &&
      el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
  })).toBeTruthy();
}

test('complete tour, back, close, restart and focus return', async ({ page }) => {
  const start = page.getByRole('button', { name: '✦ Tour', exact: true });
  await start.click();
  await expect(tour(page)).toContainText('Step 1 / 8');
  await expect(tour(page).getByRole('button', { name: '← Back', exact: true })).toBeDisabled();
  for (let i = 2; i <= 8; i++) {
    await tour(page).getByRole('button', { name: 'Next →', exact: true }).click();
    await expect(tour(page)).toContainText(`Step ${i} / 8`);
    await unobscured(page);
    if (i === 3) {
      const play = page.getByRole('button', { name: '▶ Play', exact: true });
      await play.click();
      await page.getByRole('button', { name: '⏸ Pause', exact: true }).click();
      await expect(tour(page)).toContainText('Step 3 / 8');
    }
  }
  await tour(page).getByRole('button', { name: '← Back', exact: true }).click();
  await expect(tour(page)).toContainText('Step 7 / 8');
  await tour(page).getByRole('button', { name: 'Next →', exact: true }).click();
  await tour(page).getByRole('button', { name: 'Finish', exact: true }).click();
  await expect(tour(page)).toHaveCount(0);
  await expect(start).toBeFocused();
  await start.click();
  await expect(tour(page)).toContainText('Step 1 / 8');
  await tour(page).getByRole('button', { name: 'Close tour', exact: true }).click();
  await expect(start).toBeFocused();
});

test('tour stays above a panel and native modal while controls remain usable', async ({ page }) => {
  await page.getByRole('button', { name: '✦ Tour', exact: true }).click();
  await page.evaluate(() => {
    const panel = document.createElement('div');
    panel.id = 'test-panel';
    panel.textContent = 'Panel';
    Object.assign(panel.style, { position: 'fixed', inset: '0', zIndex: '2147483646', background: 'white' });
    document.body.append(panel);
  });
  await unobscured(page);
  await page.evaluate(() => {
    const dialog = document.createElement('dialog');
    dialog.id = 'test-modal';
    dialog.innerHTML = '<h2>Modal heading</h2><button id="close-test-modal">Close modal</button>';
    document.body.append(dialog);
    dialog.querySelector('button')!.addEventListener('click', () => dialog.close());
    dialog.showModal();
  });
  await unobscured(page);
  await expect.poll(() => page.locator('[data-testid="tour-layer"]').evaluate((el) => el.parentElement?.id)).toBe('test-modal');
  await tour(page).getByRole('button', { name: 'Next →', exact: true }).click();
  await expect(tour(page)).toContainText('Step 2 / 8');
  await page.getByRole('button', { name: 'Close modal', exact: true }).click();
  await page.evaluate(() => document.querySelector('#test-panel')?.remove());
  await unobscured(page);
  await page.getByRole('link', { name: 'Token replay', exact: true }).click();
  await expect(tour(page)).toContainText('Step 3 / 8');
});

test('resizing, scrolling, highlights and keyboard navigation', async ({ page }) => {
  await page.getByRole('button', { name: '✦ Tour', exact: true }).click();
  await unobscured(page);
  const highlight = page.getByTestId('tour-highlight');
  await expect(highlight).toBeVisible();
  await expect.poll(async () => {
    const h = await highlight.boundingBox();
    const target = await page.locator('main h1').boundingBox();
    return h && target ? Math.abs(h.x - target.x + 4) < 2 && Math.abs(h.y - target.y + 4) < 2 : false;
  }).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 600 });
  await page.evaluate(() => window.scrollTo(0, 600));
  await unobscured(page);
  const next = tour(page).getByRole('button', { name: 'Next →', exact: true });
  await next.focus();
  await page.keyboard.press('Enter');
  await expect(tour(page)).toContainText('Step 2 / 8');
  await expect(next).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(tour(page).getByRole('button', { name: 'Close tour', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(tour(page)).toHaveCount(0);
  await expect(page.getByRole('button', { name: '✦ Tour', exact: true })).toBeFocused();
});


test('uploaded normative PNML rejects invalid configurations through the real API', async ({ request }) => {
  const uploaded = await request.post('/api/datasets', { multipart: {
    log: { name: 'zone-test.csv', mimeType: 'text/csv', buffer: Buffer.from('case_id,concept:name,time:timestamp\nzone-test,A1_View_Product,2024-01-01T08:00:00\n') },
    pnml: { name: 'model.pnml', mimeType: 'application/xml', buffer: readFileSync(new URL('../../data/demo/order_process.pnml', import.meta.url)) },
  } });
  expect(uploaded.ok()).toBeTruthy();
  const id = (await uploaded.json()).id;
  for (const zones of [{}, [], { Ghost: ['missing-place'] },
    [{ name: 'Same', places: ['p_after_A1'] }, { name: 'Same', places: ['p_after_A2'] }],
    [{ name: ' ', places: ['p_after_A1'] }]]) {
    const checked = await request.post(`/api/datasets/${id}/zones/validate`, { data: { zones } });
    expect((await checked.json()).valid).toBe(false);
    const analysis = await request.post(`/api/datasets/${id}/analyses`, { data: { zones, timeframe: 'D' } });
    expect(analysis.status()).toBe(422);
  }
});

test('later native popover and nested modal cannot cover the tour', async ({ page }) => {
  await page.getByRole('button', { name: '✦ Tour', exact: true }).click();
  await page.evaluate(() => {
    const popover = document.createElement('div');
    popover.id = 'test-popover';
    popover.setAttribute('popover', 'manual');
    Object.assign(popover.style, { position: 'fixed', inset: '0', width: '100vw', height: '100vh', background: 'white' });
    document.body.append(popover);
    popover.showPopover();
  });
  await unobscured(page);
  for (const id of ['first-dialog', 'second-dialog']) {
    await page.evaluate((id) => {
      const dialog = document.createElement('dialog');
      dialog.id = id;
      dialog.innerHTML = '<h2>Dialog</h2><button>Dialog control</button>';
      document.body.append(dialog);
      dialog.showModal();
    }, id);
    await expect.poll(() => page.getByTestId('tour-layer').evaluate((el) => el.parentElement?.id)).toBe(id);
    await unobscured(page);
    await expect(tour(page).getByRole('button', { name: 'Next →', exact: true })).toBeFocused();
  }
  await page.evaluate(() => (document.querySelector('#second-dialog') as HTMLDialogElement).close());
  await expect.poll(() => page.getByTestId('tour-layer').evaluate((el) => el.parentElement?.id)).toBe('first-dialog');
  await unobscured(page);
  await page.keyboard.press('Escape');
  await expect(tour(page)).toHaveCount(0);
  await expect(page.locator('#first-dialog button')).toBeFocused();
  await expect(page.locator('#first-dialog')).toBeVisible();
});

test('unknown restored places remain visible and can be corrected', async ({ page }) => {
  await page.route(`**/api/analyses/${analysisId}`, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.zone_places['Customer Interaction'].push('missing-place');
    await route.fulfill({ response, json: body });
  });
  await page.reload();
  await expect(page.locator('.zone-snapshot-summary')).toContainText('1 unknown place IDs');
  await page.getByRole('button', { name: 'Edit places', exact: true }).first().click();
  const missing = page.getByRole('checkbox', { name: 'missing-place (not in model)', exact: true });
  await expect(missing).toBeChecked();
  await validate(page).click();
  await expect(page.getByText(/references nonexistent Petri-net place/)).toBeVisible();
  await expect(missing).toBeChecked();
  // Correcting an unknown place removes that extra option from the editor.
  await missing.click();
  await expect(missing).toHaveCount(0);
  await validated(page);
});

test('validation transport errors clear old success and cannot enable Run', async ({ page }) => {
  await validated(page);
  await page.route('**/zones/validate', (route) => route.abort());
  await validate(page).click();
  await expect(validate(page)).toBeEnabled();
  await expect(status(page)).toContainText('not validated');
  await expect(run(page)).toBeDisabled();
  await expect(page.getByRole('textbox')).toHaveCount(1);
});
