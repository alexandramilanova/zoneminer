import {test,expect,type Page} from '@playwright/test';
let id:string;
test.beforeAll(async({request})=>{
  const rows=['case_id,concept:name,time:timestamp'];
  for(let day=0;day<48;day++)for(let n=0;n<(day%8<4?1:5);n++){
    const at=new Date(Date.UTC(2024,0,day+1,12,n));
    rows.push(`${day}-${n},A,${at.toISOString()}`,`${day}-${n},B,${new Date(at.getTime()+18*3600000).toISOString()}`);
  }
  const dataset=await(await request.post('/api/datasets',{multipart:{log:{name:'retrospective-method-fixture.csv',mimeType:'text/csv',buffer:Buffer.from(rows.join('\n'))}}})).json();
  const model=await(await request.get(`/api/datasets/${dataset.id}/model`)).json();
  const internal=model.places.find((p:string)=>!model.initial_marking[p]&&!model.final_marking[p]);
  const created=await(await request.post(`/api/datasets/${dataset.id}/analyses`,{data:{zones:{Work:[internal]},timeframe:'D'}})).json();id=created.analysis_id;
  if(created.job_id)await expect.poll(async()=>(await(await request.get(`/api/jobs/${created.job_id}`)).json()).status,{timeout:120000}).toBe('done');
});
async function open(page:Page){await page.goto(`/?analysis=${id}#/prediction`);await expect(page.getByRole('combobox',{name:'Target zone',exact:true})).toContainText('Work');}
async function configure(page:Page){
  await page.getByRole('combobox',{name:'Target zone',exact:true}).selectOption('Work');
  await page.getByRole('combobox',{name:'Target metric',exact:true}).selectOption('token_present_end');
  await page.getByRole('spinbutton',{name:'Threshold',exact:true}).fill('3');
  await page.getByRole('checkbox',{name:'Predictor Token present at window end',exact:true}).check();
}

test('simple settings retain all metric families and documented standard settings',async({page})=>{
  await open(page);await expect(page.getByTestId('retrospective-policy')).toContainText('not validated live forecasts');
  await expect(page.getByRole('combobox',{name:'Calibration cutoff (UTC)'})).toHaveCount(0);
  await expect(page.getByRole('spinbutton',{name:'History lags'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Compare three models'})).toBeDisabled();
  await configure(page);
  await expect(page.getByRole('combobox',{name:'Target metric',exact:true}).locator('option')).toHaveCount(44);
  await page.getByRole('button',{name:'Use standard token predictors'}).click();
  await expect(page.getByText('1 predictor zone(s) × 6 metric(s).',{exact:false})).toBeVisible();
  await page.getByText('How the experiment works',{exact:true}).click();
  await expect(page.getByText('All three models run automatically.',{exact:false})).toBeVisible();
});

test('three real models, class counts, tree, SHAP, latest-row estimate and unchanged descriptive output',async({page,request},info)=>{
  test.setTimeout(120000);const before=await(await request.get(`/api/analyses/${id}/features`)).text();
  await open(page);await configure(page);
  const pending=page.waitForResponse(r=>r.url().endsWith('/prediction/retrospective')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Compare three models'}).click();const response=await pending;
  expect(response.ok(),await response.text()).toBe(true);const result=await response.json();
  expect(result.models).toHaveLength(3);expect(result.protocol_version).toBe('retrospective-v3');
  expect(result.positive_windows).toBeGreaterThan(0);expect(result.negative_windows).toBeGreaterThan(0);
  await expect(page.getByRole('region',{name:'Experiment results'})).toContainText('Mean precision');
  await expect(page.getByTestId('decision-tree').getByRole('img')).toBeVisible();
  await page.screenshot({path:info.outputPath('retrospective-tree.png'),fullPage:true});
  await page.getByRole('button',{name:'Random forest',exact:true}).click();
  await expect(page.getByTestId('forecast-shap')).toBeVisible();
  await page.getByText('Latest-window model estimate · exploratory',{exact:true}).click();
  await expect(page.getByText('class-1 model probability',{exact:false})).toBeVisible();
  await page.screenshot({path:info.outputPath('retrospective-shap.png'),fullPage:true});
  expect(await(await request.get(`/api/analyses/${id}/features`)).text()).toBe(before);
  await page.getByRole('spinbutton',{name:'Threshold',exact:true}).fill('4');
  await expect(page.getByRole('region',{name:'Experiment results'})).toHaveCount(0);
});

test('class balancing preserves the workflow and pooled baseline comparison',async({page})=>{
  await open(page);await configure(page);
  await page.getByRole('checkbox',{name:'Balance training classes',exact:true}).check();
  const pending=page.waitForResponse(r=>r.url().endsWith('/prediction/retrospective')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Compare three models'}).click();
  const response=await pending;expect(response.ok(),await response.text()).toBe(true);
  const result=await response.json();expect(result.balance_classes).toBe(true);
  const section=page.getByRole('region',{name:'Experiment results'});
  await expect(section).toContainText('balanced using training-only weights');
  await expect(section).toContainText('Training-majority baseline');
  await expect(section).toContainText('Persistence: current reconstructed condition');
  await expect(page.getByTestId('decision-tree')).toContainText('sample counts are unweighted observations');
  for(const model of result.models){
    const row=section.getByRole('row').filter({has:page.getByRole('cell',{name:model.model_label,exact:true})}).first();
    await expect(row).toContainText(model.evaluation.f1.toFixed(3));
  }
  await page.getByRole('checkbox',{name:'Balance training classes',exact:true}).uncheck();
  await expect(section).toHaveCount(0);
});

test('one-class conditions are explained and user input is preserved',async({page})=>{
  await open(page);await configure(page);await page.getByRole('spinbutton',{name:'Threshold',exact:true}).fill('1000000');
  await page.getByRole('button',{name:'Compare three models'}).click();
  await expect(page.getByRole('alert')).toContainText('one class');
  await expect(page.getByRole('spinbutton',{name:'Threshold',exact:true})).toHaveValue('1000000');
  await expect(page.getByRole('region',{name:'Experiment results'})).toHaveCount(0);
});

test('late responses cannot restore results after settings change and failures stay explicit',async({page})=>{
  let release!:()=>void;const waiting=new Promise<void>(r=>release=r);
  await page.route('**/prediction/retrospective',async route=>{await waiting;await route.fulfill({status:422,json:{detail:'controlled late response'}});});
  await open(page);await configure(page);await page.getByRole('button',{name:'Compare three models'}).click();
  await page.getByRole('combobox',{name:'Prediction horizon',exact:true}).selectOption('2');release();
  await expect(page.getByRole('button',{name:'Compare three models'})).toBeEnabled();await expect(page.getByRole('alert')).toHaveCount(0);
  await page.unroute('**/prediction/retrospective');
  await page.route('**/prediction/retrospective',route=>route.fulfill({status:500,json:{detail:'Prediction service unavailable'}}));
  await page.getByRole('button',{name:'Compare three models'}).click();await expect(page.getByRole('alert')).toContainText('Prediction service unavailable');
});

test('actual showcase trains without prefix gating and reports its baseline comparison honestly',async({page,request},info)=>{
  test.setTimeout(120000);
  const demo=await(await request.get('/api/demo')).json();
  const created=await(await request.post(`/api/datasets/${demo.dataset_id}/analyses`,{data:{zones:demo.zones,timeframe:'D'}})).json();
  if(created.job_id)await expect.poll(async()=>(await(await request.get(`/api/jobs/${created.job_id}`)).json()).status,{timeout:120000}).toBe('done');
  await page.goto(`/?analysis=${created.analysis_id}#/prediction`);
  await page.getByRole('combobox',{name:'Target zone',exact:true}).selectOption('Payment & Risk');
  await page.getByRole('combobox',{name:'Target metric',exact:true}).selectOption('token_enter');
  await page.getByRole('spinbutton',{name:'Threshold',exact:true}).fill('200');
  await page.getByRole('button',{name:'Use standard token predictors'}).click();
  const pending=page.waitForResponse(r=>r.url().endsWith('/prediction/retrospective')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Compare three models'}).click();const response=await pending;
  expect(response.ok(),await response.text()).toBe(true);const result=await response.json();
  expect(result.models).toHaveLength(3);
  const persistence=result.baselines.find((b:any)=>b.model.startsWith('Persistence'));
  const improves=Math.max(...result.models.map((m:any)=>m.evaluation.f1))>persistence.f1;
  await expect(page.getByTestId('baseline-verdict')).toContainText(improves?'At least one classifier exceeded':'No classifier exceeded');
  await expect(page.getByRole('region',{name:'Experiment results'})).toContainText(String(result.training_windows));
  const tree=result.models.find((m:any)=>m.model_key==='decision_tree');
  if(tree.evaluation.positive_rows&&tree.evaluation.confusion.tp===0)
    await expect(page.getByTestId('prediction-diagnostic')).toContainText(`All ${tree.evaluation.positive_rows} positive evaluation windows were missed`);
  await page.screenshot({path:info.outputPath('retrospective-showcase.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('button',{name:'Compare three models'})).toBeVisible();
});

test('historical quantile defaults are editable, resettable, and recorded without score tuning',async({page,request},info)=>{
  const options=await(await request.get(`/api/analyses/${id}/prediction/retrospective/options`)).json();
  await open(page);
  await page.getByRole('combobox',{name:'Target zone',exact:true}).selectOption('Work');
  await page.getByRole('combobox',{name:'Target metric',exact:true}).selectOption('token_present_end');
  const threshold=page.getByRole('spinbutton',{name:'Threshold',exact:true});
  const suggestions=options.availability.Work.token_present_end.suggested_thresholds;
  await expect(threshold).toHaveValue(String(suggestions['>='].value));
  await expect(page.getByTestId('threshold-suggestion')).toContainText('Suggested threshold');
  await page.screenshot({path:info.outputPath('threshold-defaults.png'),fullPage:true});
  await threshold.fill('2');
  await page.getByRole('combobox',{name:'Prediction horizon',exact:true}).selectOption('2');
  await expect(threshold).toHaveValue('2');
  await page.getByRole('button',{name:/Use suggested threshold/}).click();
  await expect(threshold).toHaveValue(String(suggestions['>='].value));
  await page.getByRole('combobox',{name:'Condition',exact:true}).selectOption('<=');
  await expect(threshold).toHaveValue(String(suggestions['<='].value));
  await page.getByRole('checkbox',{name:'Predictor Token present at window end',exact:true}).check();
  const pending=page.waitForResponse(r=>r.url().endsWith('/prediction/retrospective')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Compare three models'}).click();const response=await pending;
  expect(response.ok(),await response.text()).toBe(true);
  expect((await response.json()).specification.threshold_source).toBe('suggested');
});
