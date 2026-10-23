import { test, expect, type Page, type Locator } from '@playwright/test';
let analysisId: string;
const payment = 'Payment & Risk', logistics = 'Logistics';
const stamp = (d: number) => `2024-01-${String(d).padStart(2, '0')} 00:00:00+00:00`;
const plots = (page: Page) => page.getByTestId('configured-plot');
const graphs = (plot: Locator) => plot.getByTestId('trend-charts').locator('.js-plotly-plot');
const strictness = (plot: Locator) => plot.getByRole('spinbutton', { name: 'Change-point strictness (0–100)' });
const localSwitch = (plot: Locator) => plot.getByLabel('Show Local Change Points', { exact: true });
const overallSwitch = (plot: Locator) => plot.getByLabel('Show Overall Change Points', { exact: true });
const errors = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page }) => { const found: string[] = []; errors.set(page, found); page.on('pageerror', (e) => found.push(e.message)); });
test.afterEach(async ({ page }) => expect(errors.get(page), 'No browser chart errors').toEqual([]));
test.beforeAll(async ({ request }) => {
  const demo = await (await request.get('/api/demo')).json();
  const result = await request.post(`/api/datasets/${demo.dataset_id}/analyses`, { data: { zones: demo.zones, timeframe: 'D' } });
  expect(result.ok()).toBeTruthy();
  const created = await result.json(); analysisId = created.analysis_id;
  if (created.job_id) await expect.poll(async () => (await (await request.get(`/api/jobs/${created.job_id}`)).json()).status, { timeout: 120000 }).toBe('done');
});
function response(body: any) {
  const cps = Number(body.cp_strictness) === 100 ? [] : Number(body.cp_strictness) >= 75 ? [7] : [4, 7];
  return {
    rows: body.pairs.flatMap((p: any) => [1, 1, 1, 9, 9, 9, 3, 3, 3].map((value, i) => ({ ...p, window_start: stamp(i + 1), metric_label: p.metric,
      value: body.normalize ? value / 10 : p.metric === 'token_avg_age_open' ? value * 3600 : value }))),
    series: body.pairs.map((p: any) => ({ ...p, n_observations: 9, n_windows: 9, status: 'usable', local_status: body.local_enabled ? 'detected' : 'disabled' })),
    local_changepoints: body.local_enabled ? body.pairs.flatMap((p: any) => cps.map((d, i) => ({ timestamp: stamp(d), zone: p.zone, metric_column: p.metric,
      metric_label: p.metric, series: `${p.zone} · ${p.metric}`, cp_index: d - 1, cp_order: i + 1 }))) : [],
    overall: { status: !body.overall_enabled ? 'disabled' : body.pairs.length < 2 ? 'insufficient_components' : cps.length ? 'detected' : 'no_changes',
      n_series: body.pairs.length,
      changepoints: body.overall_enabled && body.pairs.length >= 2 ? cps.map((d, i) => ({ timestamp: stamp(d), selection_label: 'Selected collection', aggregate_method: 'mean', n_series: body.pairs.length, cp_index: d - 1, cp_order: i + 1 })) : [],
      signal: body.overall_enabled ? [0, 0, 0, 1, 1, 1, -.5, -.5, -.5].map((value, i) => ({ window_start: stamp(i + 1), value, n_components: body.pairs.length })) : [],
      contributions: body.overall_enabled ? cps.flatMap((d) => body.pairs.map((p: any, i: number) => ({ timestamp: stamp(d), zone: p.zone,
        metric_column: p.metric, metric_label: p.metric, series: `${p.zone} · ${p.metric}`, selection_label: 'Selected collection', aggregate_method: 'mean',
        before_mean: 0, after_mean: i === 0 ? (d === 4 ? 3 : 1) : i === 1 ? (d === 4 ? 1 : 3) : 0,
        jump_score: i === 0 ? (d === 4 ? 3 : 1) : i === 1 ? (d === 4 ? 1 : 3) : 0,
        contribution_pct: i === 0 ? (d === 4 ? 75 : 25) : i === 1 ? (d === 4 ? 25 : 75) : 0,
        before_start: stamp(1), before_end: stamp(d - 1), after_start: stamp(d), after_end: stamp(9) }))) : [], contribution_details: [] },
    protocol: { contribution_context: 'adjacent_detected_segments', min_points: 8, min_size: 3, missing_policy: 'mean available' },
  };
}
async function open(page: Page, mocked = true) {
  await page.addInitScript((id) => localStorage.setItem('zone-analytics-current', id), analysisId);
  if (mocked) await page.route('**/trends/selection', (route) => route.fulfill({ json: response(route.request().postDataJSON()) }));
  await page.goto('/#/trends'); await expect(graphs(plots(page).first()).first()).toBeVisible();
}
async function clear(plot: Locator) { while (await plot.getByTestId('selected-pairs').getByRole('button').count()) await plot.getByTestId('selected-pairs').getByRole('button').first().click(); }
async function add(plot: Locator, zone: string, metric: string) {
  await plot.getByRole('combobox', { name: 'Zone', exact: true }).selectOption(zone);
  await plot.getByRole('combobox', { name: 'Metric', exact: true }).selectOption(metric);
  await plot.getByRole('button', { name: 'Add series', exact: true }).click();
}
async function shapes(plot: Locator) { return graphs(plot).first().evaluate((el: any) => el.layout.shapes ?? []); }
async function localCount(plot: Locator) { return graphs(plot).first().evaluate((el: any) => el.data.filter((t: any) => t.meta?.kind === 'local').reduce((n: number, t: any) => n + t.x.length, 0)); }

test('exact different-zone metrics, same-zone multiple metrics and duplicate rejection', async ({ page }) => {
  await open(page); const plot = plots(page).first(); await clear(plot);
  await add(plot, payment, 'token_present_end'); await add(plot, logistics, 'case_present_end'); await add(plot, payment, 'token_enter');
  const expected = [{ zone: payment, metric: 'token_present_end' }, { zone: logistics, metric: 'case_present_end' }, { zone: payment, metric: 'token_enter' }];
  const request = page.waitForRequest((r) => r.url().endsWith('/trends/selection') && r.postDataJSON().normalize);
  await plot.getByLabel('Normalize display').check(); expect((await request).postDataJSON().pairs).toEqual(expected);
  await expect(graphs(plot)).toHaveCount(1);
  await expect.poll(() => graphs(plot).evaluate((el: any) => el.data.filter((t: any) => t.meta?.kind === 'series').length)).toBe(3);
  await expect(plot.getByRole('button', { name: 'Add series', exact: true })).toBeDisabled();
  await expect(plot.getByTestId('selected-pairs').getByRole('button')).toHaveCount(3);
});

for (const [local, overall] of [[false, false], [true, false], [false, true], [true, true]]) {
  test(`independent switches: local=${local}, overall=${overall}`, async ({ page }) => {
    await open(page); const plot = plots(page).first();
    await localSwitch(plot).setChecked(local); await overallSwitch(plot).setChecked(overall);
    await expect.poll(() => localCount(plot)).toBe(local ? 10 : 0);
    await expect.poll(async () => (await shapes(plot)).length).toBe(overall ? 2 : 0);
    await expect(plot.getByTestId('detected-changes').locator('tbody tr')).toHaveCount((local ? 10 : 0) + (overall ? 2 : 0));
    await expect(plot.getByTestId('overall-contributions')).toHaveCount(overall ? 1 : 0);
  });
}

test('marker timestamps, pixel positions, hover and table agree', async ({ page }) => {
  await open(page); const plot = plots(page).first(); await overallSwitch(plot).check();
  await expect.poll(async () => (await shapes(plot)).length).toBe(2);
  const geometry = await graphs(plot).evaluate((el: any) => {
    const axis = el._fullLayout.xaxis, origin = el.getBoundingClientRect().left;
    return [...el.querySelectorAll('.shapelayer path')].map((p: any, i) => ({ actual: p.getBoundingClientRect().x,
      expected: origin + axis._offset + axis.d2p(el.layout.shapes[i].x0) }));
  });
  for (const point of geometry) expect(Math.abs(point.actual - point.expected)).toBeLessThan(2);
  const points = await graphs(plot).evaluate((el: any) => el.data.filter((t: any) => t.meta?.kind === 'local').flatMap((t: any) => t.customdata));
  for (const [timestamp, zone, metric] of points) await expect(plot.getByTestId('detected-changes').locator('tbody tr').filter({ hasText: timestamp }).filter({ hasText: zone }).filter({ hasText: metric })).toHaveCount(1);
  await graphs(plot).locator('.scatterlayer .trace').last().locator('.point').first().hover({ force: true });
  await expect(graphs(plot).locator('.hoverlayer')).toContainText('Local:');
});

test('independent plots preserve configuration, title and requests after edits/removal', async ({ page }) => {
  await open(page); const first = plots(page).first(), id = await first.getAttribute('data-plot-id');
  await page.getByRole('button', { name: 'Add Plot', exact: true }).click(); const second = plots(page).nth(1);
  await expect(second.getByText('No selected series. Add a zone–metric pair.')).toBeVisible();
  await second.getByLabel('Plot title').fill('Payment age'); await add(second, payment, 'token_avg_age_open');
  await overallSwitch(second).check(); await strictness(second).fill('75');
  await expect(first.getByLabel('Plot title')).toHaveValue('Zone occupancy over time'); await expect(strictness(first)).toHaveValue('50');
  await expect(overallSwitch(first)).not.toBeChecked();
  await expect(second.getByText(/single component is redundant/)).toBeVisible();
  await first.getByRole('button', { name: 'Remove plot', exact: true }).click();
  await expect(plots(page)).toHaveCount(1); expect(await plots(page).first().getAttribute('data-plot-id')).not.toBe(id);
  await expect(plots(page).first().getByLabel('Plot title')).toHaveValue('Payment age');
  await expect(strictness(plots(page).first())).toHaveValue('75');
});

test('strictness affects only its plot, is sent to both analyses and 100 clears results', async ({ page }) => {
  await open(page); const first = plots(page).first(); await overallSwitch(first).check();
  await page.getByRole('button', { name: 'Add Plot', exact: true }).click(); const second = plots(page).nth(1); await add(second, payment, 'token_enter');
  const seen: any[] = []; page.on('request', (r) => { if (r.url().endsWith('/trends/selection')) seen.push(r.postDataJSON()); });
  await strictness(first).fill('75');
  await expect.poll(async () => (await shapes(first)).map((s: any) => s.x0)).toEqual([stamp(7)]);
  expect(seen.every((r) => r.cp_strictness === 75 && r.local_enabled && r.overall_enabled)).toBeTruthy();
  await expect(strictness(second)).toHaveValue('50');
  await strictness(first).fill('100'); await expect.poll(() => localCount(first)).toBe(0); await expect.poll(async () => (await shapes(first)).length).toBe(0);
});

test('mixed raw units use separate panels, normalized display overlays and observations work', async ({ page }) => {
  await open(page); const plot = plots(page).first(); await clear(plot);
  await add(plot, payment, 'token_present_end'); await add(plot, logistics, 'token_avg_age_open');
  await expect(plot.getByTestId('mixed-units')).toBeVisible(); await expect(graphs(plot)).toHaveCount(2);
  const units = await graphs(plot).evaluateAll((els: any[]) => els.map((el) => el.layout.yaxis.title.text)); expect(units.sort()).toEqual(['seconds', 'tokens']);
  await plot.getByLabel('Normalize display').check(); await expect(graphs(plot)).toHaveCount(1);
  await plot.getByLabel('Show observations').check();
  await expect.poll(() => graphs(plot).evaluate((el: any) => el.data.filter((t: any) => t.meta?.kind === 'series').every((t: any) => t.mode === 'lines+markers'))).toBeTruthy();
  await expect.poll(() => graphs(plot).evaluate((el: any) => el.layout.yaxis.title.text)).toBe('z-score');
});

test('contributions use positive percentages, sorted pair labels and independently selected timestamps', async ({ page }) => {
  await open(page); const plot = plots(page).first(); await overallSwitch(plot).check();
  const chart = plot.getByTestId('contribution-chart').locator('.js-plotly-plot'); await expect(chart).toBeVisible();
  expect(await chart.evaluate((el: any) => el.data[0].x)).toEqual([75, 25]);
  const firstLabels = await chart.evaluate((el: any) => el.data[0].y);
  await plot.getByRole('combobox', { name: 'Contribution change-point time' }).selectOption(stamp(7));
  await expect.poll(() => chart.evaluate((el: any) => el.data[0].y)).not.toEqual(firstLabels);
  expect(await chart.evaluate((el: any) => el.data[0].x)).toEqual([75, 25]);
  await expect(plot.getByTestId('contribution-table')).toContainText(stamp(7));
  await overallSwitch(plot).uncheck(); await expect(plot.getByTestId('overall-contributions')).toHaveCount(0);
});

test('pending, failures and constant/insufficient states remain distinct', async ({ page }) => {
  await open(page); const plot = plots(page).first();
  await page.route('**/trends/selection', (route) => route.fulfill({ status: 500, json: { detail: 'detector failed' } }));
  await strictness(plot).fill('75'); await expect(plot.getByRole('alert')).toContainText('Plot analysis unavailable'); await expect(graphs(plot)).toHaveCount(0);
  await page.unroute('**/trends/selection');
  await page.route('**/trends/selection', (route) => { const data = response(route.request().postDataJSON());
    data.series[0].status = 'constant'; data.series[1].status = 'insufficient_observations'; data.local_changepoints = [];
    data.overall.status = 'insufficient_components'; data.overall.changepoints = []; return route.fulfill({ json: data }); });
  await overallSwitch(plot).check(); await expect(plot.getByText(/Constant series/)).toBeVisible(); await expect(plot.getByText(/Insufficient observations/)).toBeVisible();
  await expect(plot.getByText(/at least two usable components/)).toBeVisible();
});

test('late success and failure cannot overwrite a newer plot request', async ({ page }) => {
  await open(page); const plot = plots(page).first(); let release!: () => void; const gate = new Promise<void>((r) => { release = r; });
  await page.route('**/trends/selection', async (route) => {
    const body = route.request().postDataJSON(); if (body.cp_strictness === 75) { await gate; return route.fulfill({ status: 500, json: { detail: 'old error' } }); }
    return route.fulfill({ json: response(body) });
  });
  const sent = page.waitForRequest((r) => r.url().endsWith('/trends/selection') && r.postDataJSON().cp_strictness === 75);
  await strictness(plot).fill('75'); await sent; await expect(plot.getByRole('status')).toContainText('Loading plot');
  await strictness(plot).fill('100'); await expect(plot.getByText('No local change points detected in eligible series with these settings.')).toBeVisible();
  const reply = page.waitForResponse((r) => r.status() === 500); release(); await reply;
  await expect(plot.getByRole('alert')).toHaveCount(0); await expect.poll(() => localCount(plot)).toBe(0);
});

test('changing the analysis resets plot identities/configuration and ignores old results', async ({ page }) => {
  await open(page); await page.getByRole('button', { name: 'Add Plot', exact: true }).click();
  const old = await (await page.request.get(`/api/analyses/${analysisId}`)).json();
  const other = { ...old, id: 'other-analysis' };
  const catalog = await (await page.request.get(`/api/analyses/${analysisId}/metrics`)).json();
  await page.route('**/api/analyses/other-analysis', (r) => r.fulfill({ json: other }));
  await page.route('**/api/analyses/other-analysis/metrics', (r) => r.fulfill({ json: catalog }));
  await page.route('**/api/analyses/other-analysis/drift*', (r) => r.fulfill({ json: { rows: [] } }));
  // Navigate through the app's analysis override; old plot settings must not survive.
  await page.goto('/?analysis=other-analysis#/trends'); await expect(plots(page)).toHaveCount(1);
  await expect(plots(page).first().getByLabel('Plot title')).toHaveValue('Zone occupancy over time');
});

test('real showcase and screenshots agree with exact-pair API at several strictness settings', async ({ page, request }, info) => {
  await open(page, false); const plot = plots(page).first();
  const pairs = ['Customer Interaction', 'Fulfillment', 'Logistics', 'Payment & Risk', 'Quality'].map((zone) => ({ zone, metric: 'token_present_end' }));
  for (const strict of [50, 75, 100]) {
    await strictness(plot).fill(String(strict));
    const expected = await (await request.post(`/api/analyses/${analysisId}/trends/selection`, { data: { pairs, cp_strictness: strict, local_enabled: true, overall_enabled: false } })).json();
    if (strict === 50) expect(expected.local_changepoints.length).toBeGreaterThan(0);
    await expect.poll(() => localCount(plot)).toBe(expected.local_changepoints.length);
    await expect(plot.getByTestId('detected-changes').locator('tbody tr')).toHaveCount(expected.local_changepoints.length);
  }
  await strictness(plot).fill('50'); await expect.poll(() => localCount(plot)).toBeGreaterThan(0);
  await plot.screenshot({ path: info.outputPath('showcase-local-only.png'), animations: 'disabled' });
  await localSwitch(plot).uncheck(); await overallSwitch(plot).check();
  await expect(plot.getByTestId('contribution-chart')).toBeVisible();
  await plot.screenshot({ path: info.outputPath('showcase-overall-only.png'), animations: 'disabled' });
  await localSwitch(plot).check(); await expect.poll(() => localCount(plot)).toBeGreaterThan(0);
  await plot.screenshot({ path: info.outputPath('showcase-both.png'), animations: 'disabled' });
  const actual = await (await request.post(`/api/analyses/${analysisId}/trends/selection`, { data: { pairs, overall_enabled: true, cp_strictness: 50 } })).json();
  const at = await plot.getByRole('combobox', { name: 'Contribution change-point time' }).inputValue();
  const expected = actual.overall.contributions.filter((c: any) => c.timestamp === at && c.contribution_pct > 0 && c.jump_score > 0).sort((a: any, b: any) => b.contribution_pct - a.contribution_pct).slice(0, 10).map((c: any) => c.contribution_pct);
  expect(await plot.getByTestId('contribution-chart').locator('.js-plotly-plot').evaluate((el: any) => el.data[0].x)).toEqual(expected);
  await plot.getByTestId('overall-contributions').screenshot({ path: info.outputPath('showcase-contributions.png'), animations: 'disabled' });
  await page.getByRole('button', { name: 'Add Plot', exact: true }).click();
  await add(plots(page).nth(1), payment, 'token_avg_age_open'); await add(plots(page).nth(1), logistics, 'case_present_end');
  await plots(page).nth(1).getByLabel('Normalize display').check(); await expect(graphs(plots(page).nth(1))).toBeVisible();
  await page.screenshot({ path: info.outputPath('showcase-multiple-plots.png'), fullPage: true, animations: 'disabled' });
});

test('a failing plot stays isolated and a pending plot keeps its identity after removal', async ({ page }) => {
  await open(page); const first = plots(page).first();
  await page.getByRole('button', { name: 'Add Plot', exact: true }).click(); const second = plots(page).nth(1);
  let release!: () => void; const gate = new Promise<void>((r) => { release = r; });
  await page.route('**/trends/selection', async (route) => {
    const body = route.request().postDataJSON();
    if (body.pairs.some((p: any) => p.metric === 'token_avg_age_open')) { await gate; return route.fulfill({ status: 500, json: { detail: 'only second plot failed' } }); }
    return route.fulfill({ json: response(body) });
  });
  await add(second, payment, 'token_avg_age_open'); await expect(second.getByRole('status')).toContainText('Loading plot');
  await expect(graphs(first)).toBeVisible();
  const secondId = await second.getAttribute('data-plot-id');
  await first.getByRole('button', { name: 'Remove plot', exact: true }).click();
  const reply = page.waitForResponse((r) => r.status() === 500); release(); await reply;
  expect(await plots(page).first().getAttribute('data-plot-id')).toBe(secondId);
  await expect(plots(page).first().getByRole('alert')).toContainText('only second plot failed');
  await page.getByRole('button', { name: 'Add Plot', exact: true }).click(); await add(plots(page).nth(1), logistics, 'token_enter');
  await expect(graphs(plots(page).nth(1))).toBeVisible(); await expect(plots(page).nth(1).getByRole('alert')).toHaveCount(0);
});

test('zero total jump produces no contribution bars or invented percentages', async ({ page }) => {
  await open(page); const plot = plots(page).first();
  await page.route('**/trends/selection', (route) => {
    const data = response(route.request().postDataJSON()); data.overall.contributions = [];
    data.overall.contribution_details = data.overall.changepoints.map((cp: any) => ({ timestamp: cp.timestamp, status: 'no_measurable_contribution', total_jump: 0, included_components: 5, omitted_components: [] }));
    return route.fulfill({ json: data });
  });
  await overallSwitch(plot).check();
  await expect(plot.getByText('No measurable contribution for this boundary.')).toBeVisible();
  await expect(plot.getByTestId('contribution-chart')).toHaveCount(0);
});

test('solid lines and independent minimize/expand preserve plot state', async ({ page }) => {
  await open(page); const plot = plots(page).first(); await overallSwitch(plot).check();
  await expect.poll(async () => (await shapes(plot)).length).toBe(2);
  await plot.getByRole('combobox', { name: 'Contribution change-point time' }).selectOption(stamp(7));
  await page.getByRole('button', { name: 'Add Plot', exact: true }).click();
  const second = plots(page).nth(1);
  const seen: string[] = []; page.on('request', r => { if (r.url().endsWith('/trends/selection')) seen.push(r.url()); });
  const before = await graphs(plot).evaluate((el: any) => ({ data: el.data, shapes: el.layout.shapes }));
  expect(before.data.filter((t: any) => t.meta?.kind === 'series').every((t: any) => t.line.dash === 'solid')).toBeTruthy();
  expect(before.shapes.every((s: any) => s.line.dash === 'solid')).toBeTruthy();
  expect(before.data.filter((t: any) => t.meta?.kind === 'local').every((t: any) => !t.hovertemplate.includes('Clean-series index'))).toBeTruthy();
  await expect(plot.getByTestId('series-data')).toHaveCount(0);
  await expect(plot.getByRole('columnheader', { name: 'clean-series index' })).toHaveCount(0);
  await expect(plot.getByText('Up to 10 positive contributions; all measured components appear in the table.')).toHaveCount(0);
  await plot.getByRole('button', { name: 'Minimize details' }).click();
  await expect(plot.getByRole('heading', { name: 'Zone occupancy over time' })).toBeVisible();
  await expect(graphs(plot)).toBeVisible();
  await expect(localSwitch(plot)).toBeHidden();
  await expect(plot.getByTestId('detected-changes')).toBeHidden();
  await expect(plot.getByTestId('overall-contributions')).toBeHidden();
  await expect(second.getByLabel('Plot title')).toBeVisible();
  expect(await graphs(plot).evaluate((el: any) => ({ data: el.data, shapes: el.layout.shapes }))).toEqual(before);
  await plot.getByRole('button', { name: 'Expand details' }).click();
  await expect(overallSwitch(plot)).toBeChecked();
  await expect(plot.getByRole('combobox', { name: 'Contribution change-point time' })).toHaveValue(stamp(7));
  await expect(plot.getByTestId('detected-changes')).toBeVisible();
  expect(seen).toEqual([]);
});

test('drift explanations describe the implemented retrospective comparison', async ({ page }) => {
  await open(page);
  const section = page.getByRole('region', { name: 'Zone drift scores' });
  await expect(section).toContainText('5 preceding analysis windows with 5 windows starting at the plotted window');
  await expect(section).toContainText('not percentages, probabilities, or significance tests');
  await section.getByText('How drift scores are calculated', { exact: true }).click();
  await expect(section).toContainText('whole-history population standard deviations');
  await expect(section).toContainText('not an online alert or forecast');
});
