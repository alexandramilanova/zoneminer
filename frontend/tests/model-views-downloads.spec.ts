import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
let analysisId: string;
test.beforeAll(async ({ request }) => {
  const demo = await (await request.get('/api/demo')).json();
  const response = await request.post(`/api/datasets/${demo.dataset_id}/analyses`, { data: { zones: demo.zones, timeframe: 'D' } });
  expect(response.ok()).toBeTruthy();
  const created = await response.json(); analysisId = created.analysis_id;
  if (created.job_id) await expect.poll(async () => (await (await request.get(`/api/jobs/${created.job_id}`)).json()).status,
    { timeout: 120_000 }).toBe('done');
});
test.beforeEach(async ({ page }) => {
  await page.addInitScript(id => localStorage.setItem('zone-analytics-current', id), analysisId);
});
test('showcase is inside examples; missing tree is explained and direct BPMN renders', async ({ page }) => {
  const badViews: string[] = [];
  page.on('response', r => { if (/bpmn\.xml|process-tree\.svg/.test(r.url()) && !r.ok()) badViews.push(r.url()); });
  await page.goto('/#/');
  const examples = page.getByTestId('example-scenarios');
  await expect(page.getByRole('button', { name: 'Load demo dataset' })).toBeHidden();
  await examples.locator('summary').click();
  await expect(examples.getByText('Without a PNML file a model is discovered from the log automatically.')).toBeVisible();
  await examples.getByRole('button', { name: 'Load demo dataset' }).click();
  await expect(page.getByRole('checkbox', { name: 'Process-tree helper view' })).toBeDisabled();
  await expect(page.getByTestId('process-tree-explanation')).toContainText('not a workflow net');
  await expect(page.getByText(/PM4Py error:/)).toHaveCount(0);
  await page.getByRole('checkbox', { name: 'BPMN view', exact: true }).check();
  await expect(page.locator('.bjs-container .djs-container > svg')).toBeVisible();
  await expect(page.locator('.bjs-container [data-element-id]')).not.toHaveCount(0);
  expect(badViews).toEqual([]);
  await page.screenshot({ path: 'test-results/model-views-fixed.png', fullPage: true });
});
test('unavailable BPMN explains the limitation without making a failed request', async ({ page }) => {
  await page.route('**/api/datasets/*/model', async route => {
    const response = await route.fetch(); const graph = await response.json();
    await route.fulfill({ json: { ...graph, bpmn_available: false, bpmn_reason: 'BPMN cannot represent weighted arcs faithfully. Use the Petri net.' } });
  });
  let requests = 0;
  await page.route('**/bpmn.xml', route => { requests++; return route.abort(); });
  await page.goto('/#/');
  await expect(page.getByRole('checkbox', { name: 'BPMN view', exact: true })).toBeDisabled();
  await expect(page.getByTestId('bpmn-explanation')).toContainText('weighted arcs'); expect(requests).toBe(0);
});
test('trend data and displayed change rows download as CSV; plots as PNG and SVG', async ({ page }) => {
  await page.goto('/#/trends'); const plot = page.getByTestId('configured-plot').first();
  await expect(plot.getByRole('button', { name: 'Download plot (PNG)', exact: true }).first()).toBeEnabled();
  let pending = page.waitForEvent('download');
  await plot.getByRole('button', { name: 'Download plot data (CSV)', exact: true }).click();
  let download = await pending;
  expect(download.suggestedFilename()).toBe('Zone-occupancy-over-time-data.csv');
  let csv = readFileSync((await download.path())!, 'utf8');
  expect(csv).toContain('"analysis_id","zone","metric","window_start","value","unit","normalized"');
  expect(csv).toContain('"Payment & Risk","token_present_end"'); expect(csv).toContain('"435","tokens","false"');
  for (const format of ['PNG', 'SVG']) {
    pending = page.waitForEvent('download');
    await plot.getByRole('button', { name: `Download plot (${format})`, exact: true }).first().click();
    download = await pending; const bytes = readFileSync((await download.path())!);
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${format.toLowerCase()}$`));
    if (format === 'PNG') expect(bytes.subarray(1, 4).toString()).toBe('PNG'); else expect(bytes.toString()).toContain('<svg');
  }
  pending = page.waitForEvent('download');
  await plot.getByTestId('detected-changes').locator('summary').click();
  await plot.getByTestId('detected-changes').getByRole('button', { name: 'Download displayed rows (CSV)' }).click();
  download = await pending; csv = readFileSync((await download.path())!, 'utf8');
  expect(csv).toContain('"type","timestamp","zone","metric","selection","order"'); expect(csv).toContain('"Local"');
  await page.screenshot({ path: 'test-results/download-controls.png', fullPage: false });
});
test('CSV preserves quoted text and precision, and neutralizes spreadsheet formulas', async ({ page }) => {
  await page.route('**/dependencies', route => route.fulfill({ json: { note: 'Associations only',
    metric_options: ['token_enter', 'token_exit'], rows: [{ from_zone: '=formula,"quoted"\nsecond line', to_zone: 'Target',
      src_metric: 'token_enter', tgt_metric: 'token_exit', best_lag_windows: 1, best_corr: -0.625123456789,
      overlap_points: 12, significant: false }] } }));
  await page.goto('/#/dependencies'); const pending = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download displayed rows (CSV)' }).click(); const download = await pending;
  const csv = readFileSync((await download.path())!, 'utf8');
  expect(csv).toContain('"\'=formula,""quoted""\nsecond line"'); expect(csv).toContain('"-0.625123456789"');
  expect(csv).not.toContain('"\'-0.625123456789"');
});
