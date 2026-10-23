import { test, expect } from '@playwright/test';

test('uploads come first and examples are collapsed with keyboard access', async ({ page }) => {
  await page.goto('/#/');
  const upload = page.getByRole('button', { name: 'Upload', exact: true });
  const examples = page.getByTestId('example-scenarios');
  await expect(examples).toBeVisible();
  await expect(examples).not.toHaveAttribute('open');
  await expect(page.getByRole('button', { name: 'Load scenario', exact: true }).first()).toBeHidden();
  const boxes = await Promise.all([upload.boundingBox(), examples.boundingBox()]);
  expect(boxes[0]!.y).toBeLessThan(boxes[1]!.y);
  await examples.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(examples).toHaveAttribute('open', '');
  await expect(page.getByRole('button', { name: 'Load scenario', exact: true }).first()).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(examples).not.toHaveAttribute('open');
});

test('out-of-order upload discovers a model and completes validated analysis', async ({ page }) => {
  await page.goto('/#/');
  const file = process.env.E2E_LARGE_LOG_PATH;
  test.setTimeout(file ? 180_000 : 60_000);
  const csv = 'case_id,concept:name,time:timestamp\nc1,B,2024-01-02T00:00:00Z\nc1,A,2024-01-01T00:00:00Z\nc2,A,2024-01-01T01:00:00Z\nc2,B,2024-01-02T01:00:00Z\n';
  await page.locator('input[name=log]').setInputFiles(file ?? { name: 'unordered.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  const uploaded = page.waitForResponse((r) => r.url().endsWith('/api/datasets') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Upload', exact: true }).click();
  const response = await uploaded;
  expect(response.ok()).toBeTruthy();
  const dataset = await response.json();
  await page.getByText('Model import details', { exact: true }).click();
  await expect(page.getByText(/Import ordered .* cases chronologically/)).toBeVisible();
  const model = await (await page.request.get(`/api/datasets/${dataset.id}/model`)).json();
  expect(model.model_source).toBe('discovered_from_log');
  const internalPlace = model.places.find((p: string) => !model.initial_marking[p] && !model.final_marking[p]);
  expect(internalPlace).toBeTruthy();
  // Newly uploaded, empty zones already expose their place checkboxes.
  await page.getByRole('checkbox', { name: internalPlace, exact: true }).check();
  await page.getByRole('button', { name: 'Validate zones', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Zone system is valid.' })).toBeVisible();
  await page.getByRole('button', { name: 'Run analysis', exact: true }).click();
  await expect(page).toHaveURL(/#\/overview/, { timeout: 120_000 });
  await expect(page.getByRole('heading', { name: 'Zones at the latest window', exact: true })).toBeVisible();
  await expect(page.locator('.notice.error')).toHaveCount(0);
  if (file) {
    await page.evaluate(async () => {
      await document.fonts.ready;
      await Promise.all(document.getAnimations().filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => {})));
    });
    await page.screenshot({ path: '/tmp/zone-large-log/bpi2020-analysis.png', fullPage: true });
  }
});
