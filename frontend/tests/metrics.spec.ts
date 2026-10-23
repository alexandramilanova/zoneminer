import { test, expect, type Page } from '@playwright/test';
import { formatDuration, formatMetricValue, metricAxisLabel } from '../src/lib/metricPresentation';
import type { MetricInfo } from '../src/api';

const ids: Record<string, string> = {};
test.beforeAll(async ({ request }) => {
  test.setTimeout(180_000);
  const demo = await (await request.get('/api/demo')).json();
  for (const timeframe of ['D', 'h']) {
    const response = await request.post('/api/datasets/demo/analyses', { data: { zones: demo.zones, timeframe } });
    expect(response.ok()).toBeTruthy();
    const created = await response.json();
    ids[timeframe] = created.analysis_id;
    if (created.job_id) await expect.poll(async () => (await (await request.get(`/api/jobs/${created.job_id}`)).json()).status,
      { timeout: 120_000 }).toBe('done');
  }
});
async function open(page: Page, tf = 'D') {
  await page.addInitScript((id) => localStorage.setItem('zone-analytics-current', id), ids[tf]);
  await page.goto('/#/metrics');
}

test('shared presentation preserves canonical values, fractional ratios and missing values', () => {
  const duration = { label: 'Duration', unit_label: 'seconds' } as MetricInfo;
  const ratio = { label: 'Share', unit_label: 'ratio (fraction)' } as MetricInfo;
  expect(formatMetricValue(7200, duration)).toContain('7,200 seconds');
  expect(formatMetricValue(.25, ratio)).toBe('0.25 ratio (fraction)');
  expect(formatMetricValue(null, duration)).toBe('Unavailable');
  expect(formatDuration(null)).toBe('–');
  expect(formatDuration(7200)).toBe('2.0 h');
  expect(formatDuration(172800)).toBe('2.0 d');
  expect(metricAxisLabel(duration, true)).toBe('Duration (z-score)');
});

for (const tf of ['D', 'h']) {
  test(`${tf}: actual API metadata, rendered definitions and duration chart agree`, async ({ page, request }) => {
    const catalog = await (await request.get(`/api/analyses/${ids[tf]}/metrics`)).json();
    await open(page, tf);
    await expect(page.getByRole('heading', { name: tf === 'D' ? 'Reading daily windows' : 'Reading hourly windows' })).toBeVisible();
    await expect(page.locator('[data-testid^="metric-"]')).toHaveCount(catalog.metrics.length);
    for (const name of ['token_enter', 'token_avg_duration_completed', 'token_completion_ratio', 'alignment_trace_fitness_mean', 'zone_local_fitness']) {
      const meta = catalog.metrics.find((m: any) => m.name === name);
      const row = page.getByTestId(`metric-${name}`);
      await expect(row).toContainText(meta.label);
      await expect(row).toContainText(meta.unit_label);
      await expect(row).toContainText(meta.formula);
      expect(await row.innerText()).not.toContain('**');
      await expect(row.locator('strong', { hasText: 'Calculation / population:' })).toHaveCount(1);
    }
    await expect(page.getByRole('region', { name: 'Global conformance · process/window', exact: true }).getByTestId('metric-alignment_trace_fitness_mean')).toHaveCount(1);
    await expect(page.getByRole('region', { name: 'Zone-attributed conformance', exact: true }).getByTestId('metric-zone_local_fitness')).toHaveCount(1);
    await page.getByLabel('Find a metric').fill('token_avg_duration_completed');
    await expect(page.locator('[data-testid^="metric-"]')).toHaveCount(1);
    await page.getByLabel('Find a metric').fill('does-not-exist');
    await expect(page.getByText('No metrics match this search and scope.')).toBeVisible();
    await page.getByLabel('Find a metric').fill('');
    await page.getByLabel('Metric scope').selectOption('zone_conformance');
    await expect(page.locator('[data-testid^="metric-"]')).toHaveCount(6);
    // Unit integration exercises real API values without running the independent PELT detector.
    await page.route('**/trends/selection', async (route) => {
      const body = route.request().postDataJSON();
      const response = await route.fetch({ postData: { ...body, local_enabled: false, overall_enabled: false } });
      await route.fulfill({ response });
    });
    await page.goto('/#/trends');
    const plot = page.getByTestId('configured-plot').first();
    await expect(plot.getByTestId('selected-pairs').getByRole('button')).toHaveCount(5);
    while (await plot.getByTestId('selected-pairs').getByRole('button').count()) await plot.getByTestId('selected-pairs').getByRole('button').first().click();
    await plot.getByRole('combobox', { name: 'Metric', exact: true }).selectOption('token_avg_duration_completed');
    await plot.getByRole('button', { name: 'Add series', exact: true }).click();
    const graph = plot.getByTestId('trend-charts').locator('.js-plotly-plot');
    await expect.poll(() => graph.evaluate((el: any) => el.layout.yaxis.title.text)).toBe('seconds');
    const plotted = await graph.evaluate((el: any) => el.data.filter((t: any) => t.meta?.kind === 'series').map((t: any) => ({ zone: t.meta.zone, y: t.y, unit: t.customdata[0][3], hover: t.hovertemplate })));
    const raw = await (await request.get(`/api/analyses/${ids[tf]}/trends?metrics=token_avg_duration_completed`)).json();
    for (const series of plotted) {
      expect(series.y).toEqual(raw.rows.filter((r: any) => r.zone === series.zone).map((r: any) => r.value));
      expect(series.unit).toBe('seconds');
      expect(series.hover).toContain('%{customdata[3]}');
    }
    await expect(page.getByTestId('series-data')).toHaveCount(0);
    await plot.getByTestId('plot-heatmaps').locator('summary').click();
    const heatCell = plot.getByTestId('plot-heatmaps').locator('[title*="seconds"]').first();
    await expect(heatCell).toHaveCount(1);
    await plot.getByTestId('selected-pairs').getByRole('button').first().click();
    await plot.getByRole('combobox', { name: 'Metric', exact: true }).selectOption('token_completion_ratio');
    await plot.getByRole('button', { name: 'Add series', exact: true }).click();
    await expect.poll(() => graph.evaluate((el: any) => el.layout.yaxis.title.text)).toContain('ratio (fraction)');
  });
}

test('loading, unavailable metrics and API errors are explicit', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/metrics', async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.metrics = data.metrics.map((m: any) => m.name === 'token_avg_age_open' ? { ...m, non_null_count: 0 } : m);
    await gate;
    await route.fulfill({ json: data });
  });
  await open(page);
  await expect(page.getByText('Loading metric reference…')).toBeVisible();
  release();
  await expect(page.getByTestId('metric-token_avg_age_open')).toContainText('Unavailable in this analysis');
  await page.unroute('**/metrics');
  await page.route('**/metrics', (route) => route.fulfill({ status: 503, json: { detail: 'reference unavailable' } }));
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('Metric reference unavailable');
  await expect(page.locator('[data-testid^="metric-"]')).toHaveCount(0);
});

test('empty reference and mobile search remain usable', async ({ page }) => {
  await page.route('**/metrics', async (route) => {
    const data = await (await route.fetch()).json();
    await route.fulfill({ json: { ...data, metrics: [] } });
  });
  await open(page);
  await expect(page.getByText('No metric columns are available for this analysis.')).toBeVisible();
  await page.unroute('**/metrics');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByLabel('Find a metric').fill('token_enter');
  await expect(page.getByTestId('metric-token_enter')).toBeVisible();
  await page.getByLabel('Find a metric').focus();
  await expect(page.getByLabel('Find a metric')).toBeFocused();
});
