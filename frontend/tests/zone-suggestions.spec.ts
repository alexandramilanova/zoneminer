import { test, expect, type Page, type Locator } from '@playwright/test';

let analysisId: string;
test.beforeAll(async ({ request }) => {
  const demo = await (await request.get('/api/demo')).json();
  const response = await request.post('/api/datasets/demo/analyses', { data: { zones: demo.zones, timeframe: 'D' } });
  expect(response.ok()).toBeTruthy();
  const created = await response.json();
  analysisId = created.analysis_id;
  if (created.job_id) await expect.poll(async () => (await (await request.get(`/api/jobs/${created.job_id}`)).json()).status,
    { timeout: 120_000 }).toBe('done');
});
test.beforeEach(async ({ page }) => {
  await page.addInitScript((id) => localStorage.setItem('zone-analytics-current', id), analysisId);
  await page.goto('/#/');
  await expect(zone(page, 1)).toBeVisible();
});
const zone = (page: Page, n: number) => page.getByRole('group', { name: `Zone ${n} configuration`, exact: true });
async function openSuggestions(card: Locator) {
  await card.locator('summary').click();
  return card;
}
const suggest = (card: Locator) => card.getByRole('button', { name: 'Suggest places', exact: true });
const results = (card: Locator) => card.getByRole('group', { name: 'Suggested places', exact: true });
const apply = (card: Locator) => card.getByRole('button', { name: 'Apply selected places to zone', exact: true });

test('every existing and newly added zone can request real activity-based suggestions', async ({ page }) => {
  await expect(page.locator('summary').filter({ hasText: 'Suggest places from activity names' })).toHaveCount(5);
  await page.getByRole('button', { name: '+ Add zone', exact: true }).click();
  for (let n = 1; n <= 6; n++) {
    const card = await openSuggestions(zone(page, n));
    await card.getByRole('group', { name: 'Activities', exact: true }).getByRole('checkbox', { name: 'A1_View_Product', exact: true }).check();
    const reply = page.waitForResponse((r) => r.url().endsWith('/zones/suggest') && r.request().method() === 'POST');
    await suggest(card).click();
    const response = await reply;
    expect(response.ok()).toBeTruthy();
    expect(response.request().postDataJSON()).toEqual({ activities: ['A1_View_Product'] });
    const { places } = await response.json();
    expect(places.length).toBeGreaterThan(0);
    await expect(results(card).getByRole('checkbox')).toHaveCount(places.length);
    await card.locator('summary').click();
  }
});

test('activity selection is independent between zones', async ({ page }) => {
  const first = await openSuggestions(zone(page, 1));
  const second = await openSuggestions(zone(page, 2));
  await first.getByRole('checkbox', { name: 'A1_View_Product', exact: true }).check();
  await second.getByRole('checkbox', { name: 'B1_Initiate_Payment', exact: true }).check();
  await expect(first.getByRole('checkbox', { name: 'B1_Initiate_Payment', exact: true })).not.toBeChecked();
  await expect(second.getByRole('checkbox', { name: 'A1_View_Product', exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: /^Fulfillment \(/ }).click();
  await expect(first.getByRole('checkbox', { name: 'A1_View_Product', exact: true })).toBeChecked();
  await expect(second.getByRole('checkbox', { name: 'B1_Initiate_Payment', exact: true })).toBeChecked();
});

test('selected suggestions apply only to the intended zone, preserve ownership and invalidate validation', async ({ page }) => {
  await page.getByRole('button', { name: 'Validate zones', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Run analysis', exact: true })).toBeEnabled();
  await page.route('**/zones/suggest', (route) => route.fulfill({ json: { places: ['p_start', 'p_end', 'p_after_A1'] } }));
  const card = await openSuggestions(zone(page, 2));
  await card.getByRole('checkbox', { name: 'B1_Initiate_Payment', exact: true }).check();
  await suggest(card).click();
  await expect(results(card).getByRole('checkbox', { name: /p_after_A1/ })).toBeDisabled();
  await results(card).getByRole('checkbox', { name: 'p_end', exact: true }).uncheck();
  await apply(card).click();
  await expect(card.getByText('7 place(s)', { exact: true })).toBeVisible();
  await expect(zone(page, 1).getByText('5 place(s)', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Edit places', exact: true }).click();
  await expect(card.getByRole('checkbox', { name: 'p_start', exact: true })).toBeChecked();
  await expect(card.getByRole('checkbox', { name: 'p_end', exact: true })).not.toBeChecked();
  await expect(page.getByRole('button', { name: 'Run analysis', exact: true })).toBeDisabled();
});

test('late responses cannot restore results for an earlier activity selection', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let seen!: () => void;
  const started = new Promise<void>((resolve) => { seen = resolve; });
  await page.route('**/zones/suggest', async (route) => {
    if (route.request().postDataJSON().activities.includes('A1_View_Product')) {
      seen(); await gate; await route.fulfill({ json: { places: ['p_start'] } });
    } else await route.fulfill({ json: { places: ['p_end'] } });
  });
  const card = await openSuggestions(zone(page, 3));
  await card.getByRole('checkbox', { name: 'A1_View_Product', exact: true }).check();
  await suggest(card).click(); await started;
  await card.getByRole('checkbox', { name: 'A1_View_Product', exact: true }).uncheck();
  await card.getByRole('checkbox', { name: 'A2_Add_To_Cart', exact: true }).check();
  await suggest(card).click();
  await expect(results(card).getByRole('checkbox', { name: 'p_end', exact: true })).toBeVisible();
  const oldReply = page.waitForResponse('**/zones/suggest');
  release(); await oldReply;
  await expect(results(card).getByRole('checkbox', { name: 'p_start', exact: true })).toHaveCount(0);
  await expect(results(card).getByRole('checkbox', { name: 'p_end', exact: true })).toBeVisible();
});

test('pending suggestions remain attached to their zone after another zone is removed', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/zones/suggest', async (route) => { await gate; await route.fulfill({ json: { places: ['p_start'] } }); });
  const card = await openSuggestions(zone(page, 2));
  await card.getByRole('checkbox', { name: 'B1_Initiate_Payment', exact: true }).check();
  const sent = page.waitForRequest('**/zones/suggest');
  await suggest(card).click(); await sent;
  await zone(page, 1).getByTitle('Remove zone', { exact: true }).click();
  release();
  const moved = zone(page, 1);
  await expect(moved.getByRole('textbox')).toHaveValue('Payment & Risk');
  await expect(results(moved).getByRole('checkbox', { name: 'p_start', exact: true })).toBeVisible();
  await expect(results(zone(page, 2))).toHaveCount(0);
});

test('removing a zone discards its pending response without targeting its neighbor', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/zones/suggest', async (route) => { await gate; await route.fulfill({ json: { places: ['p_start'] } }); });
  const card = await openSuggestions(zone(page, 2));
  await card.getByRole('checkbox', { name: 'B1_Initiate_Payment', exact: true }).check();
  const sent = page.waitForRequest('**/zones/suggest');
  await suggest(card).click(); await sent;
  await card.getByTitle('Remove zone', { exact: true }).click();
  const reply = page.waitForResponse('**/zones/suggest');
  release(); await reply;
  const neighbor = await openSuggestions(zone(page, 2));
  await expect(neighbor.getByRole('textbox')).toHaveValue('Fulfillment');
  await expect(results(neighbor)).toHaveCount(0);
  await expect(neighbor.getByRole('checkbox', { name: 'B1_Initiate_Payment', exact: true })).not.toBeChecked();
});

test('failed and empty suggestions are explicit and can be retried', async ({ page }) => {
  let attempt = 0;
  await page.route('**/zones/suggest', (route) => ++attempt === 1
    ? route.fulfill({ status: 503, json: { detail: 'test failure' } })
    : route.fulfill({ json: { places: [] } }));
  const card = await openSuggestions(zone(page, 4));
  await card.getByRole('checkbox', { name: 'D1_Quality_Check', exact: true }).check();
  await suggest(card).click();
  await expect(card.getByRole('alert')).toContainText('Place suggestions unavailable');
  await suggest(card).click();
  await expect(card.getByRole('status')).toHaveText('No places could be derived from that selection.');
  await expect(card.getByRole('alert')).toHaveCount(0);
  await expect(apply(card)).toHaveCount(0);
});
