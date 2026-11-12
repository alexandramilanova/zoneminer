import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
let analysisId: string;
test.beforeAll(async ({request}) => {
  const demo = await (await request.get('/api/demo')).json();
  const created = await (await request.post(`/api/datasets/${demo.dataset_id}/analyses`, {data:{zones:demo.zones,timeframe:'D'}})).json();
  analysisId=created.analysis_id;
  if(created.job_id) await expect.poll(async()=>(await(await request.get(`/api/jobs/${created.job_id}`)).json()).status,{timeout:120000}).toBe('done');
});
const tour = (page:Page) => page.locator('.tour-tooltip');
async function previewTour(page:Page) {
  const route=page.url();
  await page.getByRole('button',{name:'✦ Tour',exact:true}).click();
  for(let step=1;step<=8;step++) {
    await expect(tour(page)).toContainText(`Step ${step} / 8`);
    await expect(tour(page).getByTestId('tour-preview')).toBeVisible();
    expect(page.url()).toBe(route);
    await tour(page).getByRole('button',{name:step===8?'Finish':'Next →',exact:true}).click();
  }
  await expect(tour(page)).toHaveCount(0);
}
test('empty workspace offers a complete explanatory tour without creating results',async({page})=>{
  const requests:string[]=[];page.on('request',r=>{if(r.url().includes('/api/analyses/'))requests.push(r.url());});
  await page.goto('/#/');await previewTour(page);
  expect(await page.evaluate(() => performance.getEntriesByType('resource').some(item => /\/assets\/plotly-/.test(item.name)))).toBe(false);
  await expect(page.getByRole('button',{name:'Upload',exact:true})).toBeVisible();
  expect(requests).toEqual([]);
  await page.goto('/#/dependencies');await expect(page.getByRole('heading',{name:'Dependencies',exact:true})).toBeVisible();
  await expect(page.getByText(/Find zone metrics that move together/)).toBeVisible();
});
for(const pnml of [false,true])test(`tour preserves an uploaded log and zone draft (${pnml?'supplied model':'discovered model'})`,async({page})=>{
  await page.goto(pnml ? '/#/' : `/?analysis=${analysisId}#/`);
  if (!pnml) await expect(page.getByRole('combobox',{name:'Active zone',exact:true})).toBeVisible();
  const csv='case_id,concept:name,time:timestamp\nc1,A,2024-01-01T00:00:00Z\nc1,B,2024-01-02T00:00:00Z\n';
  await page.locator('input[name=log]').setInputFiles({name:'tour-upload.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
  if(pnml)await page.locator('input[name=pnml]').setInputFiles({name:'model.pnml',mimeType:'application/xml',buffer:readFileSync(new URL('../../data/demo/order_process.pnml',import.meta.url))});
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/datasets')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Upload',exact:true}).click();expect((await pending).ok()).toBe(true);
  await expect(page.getByRole('combobox',{name:'Active zone',exact:true}).locator('option')).toHaveCount(1);
  await expect(page.getByText(/Loaded.*tour-upload.csv/)).toBeVisible();
  await expect(page.getByRole('textbox',{name:'Zone 1 name',exact:true})).toHaveValue('Zone 1');
  await page.getByRole('textbox',{name:'Zone 1 name',exact:true}).fill('My review zone');
  await expect(page.getByRole('button',{name:'Edit places',exact:true})).toHaveAttribute('aria-expanded','false');
  await page.getByRole('button',{name:'Edit places',exact:true}).click();
  const place=page.locator('.zone-place-list input[type=checkbox]').first();await place.check();
  await previewTour(page);
  await expect(page.getByRole('textbox',{name:'Zone 1 name',exact:true})).toHaveValue('My review zone');
  await expect(place).toBeChecked();
  await expect(page.getByRole('group',{name:'Zone snapshot'})).toContainText('My review zone');
});
test('zone snapshot gives totals and clicking a card selects that editor',async({page})=>{
  await page.goto(`/?analysis=${analysisId}#/`);
  await expect(page.getByText('5 zones · 24 of 28 places assigned · 4 unassigned',{exact:true})).toBeVisible();
  const snapshot=page.getByRole('group',{name:'Zone snapshot',exact:true});await expect(snapshot.getByRole('button')).toHaveCount(5);
  await snapshot.getByRole('button',{name:'Edit Quality, 2 places',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Zone 4 name',exact:true})).toHaveValue('Quality');
  await expect(snapshot.getByRole('button',{name:'Edit Quality, 2 places',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('link',{name:'Token replay',exact:true}).click();
  await expect(page.locator('.net-frame canvas').first()).toBeVisible();
  await expect(page.getByRole('button',{name:'Focus selected zone',exact:true})).toHaveCount(0);
});
test('trend disclosures start closed and expensive secondary charts mount only when opened',async({page})=>{
  await page.goto(`/?analysis=${analysisId}#/trends`);
  const plot=page.getByTestId('configured-plot');await expect(plot.locator('.js-plotly-plot').first()).toBeVisible();
  await expect(plot.getByRole('button',{name:'Edit plot settings'})).toHaveAttribute('aria-expanded','false');
  await expect(page.locator('details[open]')).toHaveCount(0);
  const detected=plot.getByTestId('detected-changes');await expect(detected.locator('table')).toHaveCount(0);
  await detected.locator('summary').click();await expect(detected.locator('table')).toBeVisible();
  const heatmaps=plot.getByTestId('plot-heatmaps');await expect(heatmaps.locator('div[title]')).toHaveCount(0);
  await heatmaps.locator('summary').click();await expect(heatmaps.locator('div[title]').first()).toBeVisible();
  await heatmaps.locator('summary').click();await expect(heatmaps.locator('div[title]')).toHaveCount(0);
  await plot.getByRole('button',{name:'Edit plot settings'}).click();
  await expect(plot.getByTestId('selected-pairs').locator('.series-selection-card')).toHaveCount(5);
  const input=plot.getByRole('spinbutton',{name:'Change-point strictness (0–100)'});
  const requests:number[]=[];page.on('request',r=>{if(r.url().endsWith('/trends/selection'))requests.push(r.postDataJSON().cp_strictness);});
  await input.fill('60');await input.fill('70');await input.fill('80');
  await expect.poll(()=>requests).toEqual([80]);
});
test('dependencies show paired coverage and keep numerical statistical details closed',async({page,request})=>{
  const catalog=await(await request.get(`/api/analyses/${analysisId}/metrics`)).json();
  await page.route('**/dependencies',r=>r.fulfill({json:{rows:[{from_zone:'Quality',to_zone:'Logistics',src_metric:'token_enter',tgt_metric:'token_exit',best_lag_windows:2,best_corr:-.8,overlap_points:12,p_value:.001,q_value:.02,significant:true}],metric_options:['token_enter','token_exit'],note:'FDR-controlled'}}));
  await page.goto(`/?analysis=${analysisId}#/dependencies`);
  await expect(page.getByRole('cell',{name:`12 out of ${catalog.windows.length}`,exact:true})).toBeVisible();
  await expect(page.getByText('Passes statistical check',{exact:true})).toBeVisible();
  const info = page.getByRole('img',{name:'About Statistical check',exact:true});
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await info.hover();
  await expect(page.getByRole('tooltip')).toContainText('many pairs and delays tested');
  await page.getByRole('heading',{name:'Dependencies',exact:true}).hover();
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await info.focus();await expect(page.getByRole('tooltip')).toBeVisible();
  await info.press('Escape');await expect(page.getByRole('tooltip')).toHaveCount(0);

  await expect(page.getByText('FDR-controlled',{exact:true})).toHaveCount(0);
  await expect(page.locator('details[open]')).toHaveCount(0);
  await expect(page.getByRole('columnheader',{name:/\(q\)/})).toHaveCount(0);
  await page.getByText('How statistical checks work · detailed values',{exact:true}).click();
  await expect(page.getByRole('columnheader',{name:'Value after checking multiple pairs (q)',exact:true})).toBeVisible();
});
