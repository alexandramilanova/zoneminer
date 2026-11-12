import { test, expect, type Page } from '@playwright/test';
let analysisId: string;
test.beforeAll(async ({ request }) => {
  const demo = await (await request.get('/api/demo')).json();
  const created = await (await request.post('/api/datasets/demo/analyses', { data: { zones: demo.zones, timeframe: 'D' } })).json();
  analysisId = created.analysis_id;
  if (created.job_id) await expect.poll(async () => (await (await request.get(`/api/jobs/${created.job_id}`)).json()).status, { timeout: 120_000 }).toBe('done');
});
async function screenshot(page: Page, name: string, fullPage = false) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {})));
  });
  await page.screenshot({ path: `test-results/${name}.png`, fullPage });
}
async function open(page: Page, path: string) {
  await page.addInitScript(id => localStorage.setItem('zone-analytics-current', id), analysisId);
  await page.goto(`/#/${path}`);
}
const pair = (src: string, target = 'token_avg_age_open') => ({ note: 'test', rows: [{ from_zone: 'Source test zone', to_zone: 'Target test zone', src_metric: src, tgt_metric: target, best_lag_windows: 1, best_corr: .625, overlap_points: 12, significant: false }] });
async function dependencies(page: Page) {
  await page.route('**/dependencies', r => r.fulfill({ json: { rows: [], note: '', metric_options: ['token_netflow', 'token_enter', 'token_avg_age_open', 'token_exit'] } }));
  await open(page, 'dependencies');
  await page.getByText('Explore a specific pair of metrics',{exact:true}).click();
  await expect(page.getByRole('combobox', { name: 'Source', exact: true })).toHaveValue('token_netflow');
  await expect(page.getByRole('button', { name: 'Explore pair' })).toBeEnabled();
}

test('pair results invalidate for source, target and lag changes; empty and failed states differ', async ({ page }) => {
  let mode = 'success';
  await page.route('**/dependencies/pair?*', r => mode === 'error' ? r.fulfill({ status: 500, json: { detail: 'Diagnostic failure' } }) : r.fulfill({ json: mode === 'empty' ? { rows: [] } : pair(new URL(r.request().url()).searchParams.get('src_metric')!) }));
  await dependencies(page);
  const run = page.getByRole('button', { name: 'Explore pair' });
  for (const change of [async () => page.getByRole('combobox', { name: 'Source', exact: true }).selectOption('token_enter'), async () => page.getByRole('combobox', { name: 'Target', exact: true }).selectOption('token_exit'), async () => page.getByLabel('Maximum lag (windows)').fill('4')]) {
    await run.click();
    await expect(page.getByText('Source test zone', { exact: true })).toBeVisible();
    await change();
    await expect(page.getByText('Source test zone', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('status')).toContainText('No results for the current settings');
  }
  mode = 'error'; await run.click();
  await expect(page.getByRole('alert')).toContainText('Pair analysis failed');
  await page.getByLabel('Maximum lag (windows)').fill('5');
  await expect(page.getByRole('alert')).toHaveCount(0);
  mode = 'empty'; await run.click();
  await expect(page.getByText('No zone pairs with enough data for this metric pair.')).toBeVisible();
});

test('an older pair response cannot overwrite the newer request', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/dependencies/pair?*', async r => {
    const src = new URL(r.request().url()).searchParams.get('src_metric')!;
    if (src === 'token_netflow') await gate;
    await r.fulfill({ json: pair(src) });
  });
  await dependencies(page);
  const run = page.getByRole('button', { name: 'Explore pair' });
  await run.click();
  await expect(page.getByRole('status')).toContainText('Computing');
  await page.getByRole('combobox', { name: 'Source', exact: true }).selectOption('token_enter');
  await run.click();
  await expect(page.getByText('Results: Token place productions', { exact: false })).toBeVisible();
  const oldResponse = page.waitForResponse(r => r.url().includes('/dependencies/pair?') && r.url().includes('src_metric=token_netflow'));
  release(); await oldResponse;
  await expect(page.getByText('Results: Token place productions', { exact: false })).toBeVisible();
  await expect(page.getByText('Results: Token netflow', { exact: false })).toHaveCount(0);
});

test('Flow patterns groups all seven sections into keyboard-accessible views', async ({ page }) => {
  await open(page, 'flow');
  await expect(page.getByRole('tab')).toHaveCount(4);
  await expect(page.getByRole('heading', { name: 'Zone performance spectrum', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Cumulative flow diagrams', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Queueing profile', exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Flow & occupancy', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Handovers & ordering', exact: true })).toBeFocused();
  await expect(page.getByRole('heading', { name: 'Batch & overtaking fingerprint', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Zone handovers/ })).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('heading', { name: 'Queueing profile', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Bottleneck/ }).first()).toBeVisible();
  await page.getByRole('tab', { name: /Capacity scenarios/ }).click();
  await expect(page.getByRole('heading', { name: /What-if/ }).first()).toBeVisible();
  await page.getByRole('tab', { name: /Capacity scenarios/ }).focus();
  await page.keyboard.press('Home');
  await expect(page.getByRole('tab', { name: 'Flow & occupancy', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tabpanel')).toHaveCount(1);
  await expect(page.getByRole('tabpanel').locator('.js-plotly-plot').first()).toBeVisible();
  await screenshot(page, 'flow-views');
});

test('Overview explicitly separates snapshot boundary from alert lookback', async ({ page, request }) => {
  const overview = await (await request.get(`/api/analyses/${analysisId}/overview`)).json();
  const alerts = await (await request.get(`/api/analyses/${analysisId}/alerts?backlog_threshold=20`)).json();
  await open(page, 'overview');
  await expect(page.getByText('Snapshot boundary', { exact: true })).toBeVisible();
  await expect(page.getByTestId('snapshot-period')).toContainText(overview.latest_window_end);
  await expect(page.getByTestId('alert-period')).toContainText(alerts.period.window_start);
  await expect(page.getByTestId('alert-period')).toContainText('latest flagged window');
  await expect(page.getByTestId('alert-period')).toContainText(`${alerts.period.window_count} available windows`);
  await screenshot(page, 'overview-periods', true);
});

test('Reference coverage counts and sidebar footer are removed; tour is general and includes Reference', async ({ page }) => {
  await open(page, 'metrics');
  await expect(page.locator('[data-testid^="metric-"]').first()).toBeVisible();
  await expect(page.getByText(/\d+ \/ \d+ rows with values/)).toHaveCount(0);
  await expect(page.locator('.foot')).not.toContainText('Dependencies show');
  await page.getByRole('button', { name: '✦ Tour', exact: true }).click();
  const tour = page.locator('.tour-tooltip');
  await expect(tour).toContainText('Upload an event log');
  await expect(tour).not.toContainText('order-fulfillment');
  await expect(tour).toHaveCSS('background-color', 'rgb(20, 38, 63)');
  await expect(tour).toHaveCSS('color', 'rgb(245, 248, 255)');
  await screenshot(page, 'general-tour');
  for (let i = 0; i < 7; i++) await tour.getByRole('button', { name: 'Next →', exact: true }).click();
  await expect(tour).toContainText('Metrics Reference');
  await expect(tour).toContainText('ratios use fractions');
  await expect(page.locator('[data-testid^="metric-"]').first()).toBeVisible();
  await screenshot(page, 'metrics-tour');
  await tour.getByRole('button', { name: 'Finish', exact: true }).click();
  await expect(tour).toHaveCount(0);
  await screenshot(page, 'metrics-reference-clean');
});


test('Overview snapshot renders while the optional metric catalog is still pending', async ({page}) => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/metrics', async route => { await pending; await route.continue(); });
  try {
    await open(page, 'overview');
    await expect(page.getByRole('heading', {name:'Zones at the latest window',exact:true})).toBeVisible();
  } finally { release(); }
});
