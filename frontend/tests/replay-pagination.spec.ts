import {test, expect} from '@playwright/test';

let id: string;
test.beforeAll(async ({request}) => {
  const demo = await (await request.get('/api/demo')).json();
  const response = await request.post('/api/datasets/demo/analyses', {
    data: {zones: demo.zones, timeframe: 'D'},
  });
  expect(response.ok()).toBe(true);
  const created = await response.json(); id = created.analysis_id;
  if (created.job_id) await expect.poll(async () =>
    (await (await request.get(`/api/jobs/${created.job_id}`)).json()).status,
    {timeout: 120000}).toBe('done');
});

test('replay waits for all pages and includes the late interval beyond 50,000', async ({page}) => {
  let release!: () => void;
  const waiting = new Promise<void>(resolve => release = resolve);
  const offsets: number[] = [];
  await page.route('**/token-intervals?*', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    offsets.push(offset);
    if (offset === 0) {
      const rows = Array.from({length: 50000}, (_, i) => ({case_id: String(i), place: 'p', zone: 'Fulfillment',
        produced_ts: '2024-01-01 00:00:00', consumed_ts: '2024-01-02 00:00:00'}));
      await route.fulfill({json: {rows, row_count: rows.length, total_count: 50001, offset, next_offset: 50000}});
    } else {
      await waiting;
      await route.fulfill({json: {rows: [{case_id: 'last-case', place: 'p', zone: 'Fulfillment',
        produced_ts: '2024-01-03 00:00:00', consumed_ts: '2024-01-04 00:00:00'}],
        row_count: 1, total_count: 50001, offset, next_offset: null}});
    }
  });
  await page.goto(`/?analysis=${id}#/replay`);
  await expect.poll(() => offsets).toEqual([0, 50000]);
  await expect(page.getByRole('button', {name: '▶ Play', exact: true})).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('Loading complete token history');
  release();
  await expect(page.getByRole('status')).toContainText('50,001 token-place intervals');
  await page.getByRole('slider').press('End');
  await expect(page.getByText('2024-01-04 00:00', {exact: true})).toBeVisible();
});

test('a missing second page produces an error and no partial animation', async ({page}) => {
  await page.route('**/token-intervals?*', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    await route.fulfill({json: {rows: offset === 0 ? [{case_id: '1', place: 'p', zone: 'Fulfillment',
      produced_ts: '2024-01-01 00:00:00', consumed_ts: null}] : [],
      row_count: offset === 0 ? 1 : 0, total_count: 2, offset, next_offset: offset === 0 ? 1 : null}});
  });
  await page.goto(`/?analysis=${id}#/replay`);
  await expect(page.getByText('Incomplete replay data:', {exact: false})).toBeVisible();
  await expect(page.getByRole('button', {name: '▶ Play', exact: true})).toHaveCount(0);
});
