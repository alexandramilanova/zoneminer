import { test, expect } from '@playwright/test';

test('late previous-analysis metadata cannot replace a new upload', async ({ page }) => {
  let uploaded!: () => void;
  const uploadStarted = new Promise<void>(resolve => { uploaded = resolve; });
  let restoredPreviousModel = 0;
  const graph = (place: string) => ({ places: [place], transitions: [], arcs: [],
    initial_marking: {}, final_marking: {}, activity_labels: [],
    model_source: 'discovered from log', model_notice: null,
    process_tree_available: false, bpmn_available: false });
  await page.route('**/api/analyses/previous', async route => {
    await uploadStarted;
    await route.fulfill({ json: { id: 'previous', dataset_id: 'previous',
      zone_places: { Previous: ['old_place'] }, timeframe: '7D', timeframe_label: 'Weekly',
      backend: 'r4pm', status: 'done', error: null, has_artifacts: true } });
  });
  await page.route('**/api/datasets', async route => {
    uploaded();
    await route.fulfill({ json: { id: 'uploaded', name: 'new-upload.csv',
      log_filename: 'new-upload.csv', pnml_filename: null, created_at: '2026-10-29' } });
  });
  await page.route('**/api/datasets/previous/model', async route => {
    restoredPreviousModel++;
    await route.fulfill({ json: graph('old_place') });
  });
  await page.route('**/api/datasets/uploaded/model', route => route.fulfill({ json: graph('new_place') }));
  await page.goto('/?analysis=previous#/');
  await page.locator('input[name="log"]').setInputFiles({ name: 'new-upload.csv',
    mimeType: 'text/csv', buffer: Buffer.from('case_id,concept:name,time:timestamp\nc,A,2024-01-01T00:00:00Z\n') });
  const metadata = page.waitForResponse(r => r.url().endsWith('/api/analyses/previous'));
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  await metadata;
  await expect(page.getByRole('checkbox', { name: 'new_place', exact: true })).toBeVisible();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByRole('checkbox', { name: 'old_place', exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: 'Time window', exact: true })).toHaveValue('D');
  expect(restoredPreviousModel).toBe(0);
});
