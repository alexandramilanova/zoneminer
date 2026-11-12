import { test, expect } from '@playwright/test';

test('read admission bursts retry, while uploads are never repeated automatically', async ({ page }) => {
  let reads = 0;
  await page.route('**/api/examples', async route => {
    if (++reads === 1) await route.fulfill({ status: 429, json: { detail: 'Server is busy.' } });
    else await route.continue();
  });
  await page.goto('/#/');
  await expect(page.getByTestId('example-scenarios')).toBeVisible();
  await expect.poll(() => reads).toBe(2);
  let uploads = 0;
  await page.route('**/api/datasets', async route => {
    if (route.request().method() === 'POST') {
      uploads++;
      await route.fulfill({ status: 429, json: { detail: 'Server is busy.' } });
    } else await route.continue();
  });
  await page.locator('input[name=log]').setInputFiles({ name: 'test.csv', mimeType: 'text/csv',
    buffer: Buffer.from('case_id,concept:name,time:timestamp\nc,A,2024-01-01T00:00:00Z\n') });
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  await expect(page.locator('.notice.error')).toContainText('Server is busy.');
  await page.waitForTimeout(1500);
  expect(uploads).toBe(1);
});

test('anonymous upload, analysis, private results and deletion work in the browser', async ({ page, browser }) => {
  await page.goto('/#/');
  await expect(page.getByText(/Temporary private workspace/)).toBeVisible();
  const csv = 'case_id,concept:name,time:timestamp\nc1,A,2024-01-01T00:00:00Z\nc1,B,2024-01-02T00:00:00Z\nc2,A,2024-01-01T01:00:00Z\nc2,B,2024-01-02T01:00:00Z\n';
  await page.locator('input[name=log]').setInputFiles({ name: 'private.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  const response = await uploaded;
  expect(response.ok()).toBeTruthy();
  const dataset = await response.json();
  const graph = await (await page.request.get(`/api/datasets/${dataset.id}/model`)).json();
  const internal = graph.places.find((p: string) => !graph.initial_marking[p] && !graph.final_marking[p]);
  await page.getByRole('button',{name:'Edit places',exact:true}).click();
  await page.getByRole('checkbox', { name: internal, exact: true }).check();
  await page.getByRole('button', { name: 'Validate zones', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Zone system is valid.' })).toBeVisible();
  await page.getByRole('button', { name: 'Run analysis', exact: true }).click();
  await expect(page).toHaveURL(/#\/overview/, {timeout:120_000});
  await expect(page.getByRole('heading', { name: 'Zones at the latest window', exact: true })).toBeVisible();

  const stranger = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  try {
    expect((await stranger.request.get(`/api/datasets/${dataset.id}`)).status()).toBe(404);
  } finally { await stranger.close(); }

  await page.getByRole('button', { name: 'Delete session and files', exact: true }).click();
  await expect(page.getByText(/Temporary private workspace/)).toBeVisible();
  await expect.poll(async () => (await page.request.get(`/api/datasets/${dataset.id}`)).status()).toBe(404);
});
