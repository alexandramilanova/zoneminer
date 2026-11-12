import {test,expect,type Page} from '@playwright/test';
let analysisId:string;
test.beforeAll(async({request})=>{
 const demo=await(await request.get('/api/demo')).json();
 const created=await(await request.post(`/api/datasets/${demo.dataset_id}/analyses`,{data:{zones:demo.zones,timeframe:'D'}})).json();analysisId=created.analysis_id;
 if(created.job_id)await expect.poll(async()=>(await(await request.get(`/api/jobs/${created.job_id}`)).json()).status,{timeout:120000}).toBe('done');
});
async function openDemo(page:Page){await page.goto(`/?analysis=${analysisId}#/`);await expect(page.getByRole('combobox',{name:'Active zone',exact:true})).toHaveValue('0');}
test('new zones select automatically; switching preserves edits and selected places',async({page})=>{
 await openDemo(page);
 await page.getByRole('button',{name:'+ Add zone',exact:true}).click();
 const selected=page.getByRole('combobox',{name:'Active zone',exact:true});await expect(selected).toHaveValue('5');
 await expect(page.getByRole('textbox')).toHaveCount(1);
 await page.getByRole('textbox',{name:'Zone 6 name',exact:true}).fill('New stage');
 await page.getByRole('button',{name:'Edit places',exact:true}).filter({visible:true}).click();
 await page.getByRole('checkbox',{name:'p_start',exact:true}).check();
 await expect(page.getByRole('checkbox',{name:/^p_after_A1/})).toBeDisabled();
 await selected.selectOption('0');await expect(page.getByRole('textbox',{name:'Zone 1 name',exact:true})).toHaveValue('Customer Interaction');
 await selected.selectOption('5');await expect(page.getByRole('textbox',{name:'Zone 6 name',exact:true})).toHaveValue('New stage');
 await expect(page.getByRole('checkbox',{name:'p_start',exact:true})).toBeChecked();
 await page.getByTitle('Remove zone',{exact:true}).filter({visible:true}).click();await expect(selected).toHaveValue('4');
 await expect(selected.locator('option')).toHaveCount(5);
});

test('discovery preview requires an explicit zone reset and preserves the original model',async({page,request})=>{
 const rows=['case_id,concept:name,time:timestamp'];for(let c=0;c<31;c++)(c===30?['B','C','D','A']:['A','B','C','D']).forEach((a,i)=>rows.push(`${c},${a},2024-01-01T0${i+1}:00:00Z`));
 await page.goto('/#/');await page.locator('input[name=log]').setInputFiles({name:'discovery-controls.csv',mimeType:'text/csv',buffer:Buffer.from(rows.join('\n'))});
 const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/datasets')&&r.request().method()==='POST');await page.getByRole('button',{name:'Upload',exact:true}).click();
 const original=(await(await uploaded).json()).id;const before=await(await request.get(`/api/datasets/${original}/model`)).json();
 const internal=before.places.find((p:string)=>!before.initial_marking[p]&&!before.final_marking[p]);
 await page.getByRole('button',{name:'Edit places',exact:true}).click();
 await page.getByRole('checkbox',{name:internal,exact:true}).check();
 await page.getByRole('button',{name:'Validate zones',exact:true}).click();await expect(page.getByRole('button',{name:'Run analysis',exact:true})).toBeEnabled();
 await page.getByRole('combobox',{name:'Model discovery noise threshold',exact:true}).selectOption('0.2');
 await page.getByRole('button',{name:'Rediscover model',exact:true}).click();await expect(page.getByRole('button',{name:'Rediscover and reset zones',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Keep current model',exact:true}).click();await expect(page.getByRole('checkbox',{name:internal,exact:true})).toBeChecked();
 await page.getByRole('button',{name:'Rediscover model',exact:true}).click();
 const discovered=page.waitForResponse(r=>r.url().endsWith('/discover')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Rediscover and reset zones',exact:true}).click();const response=await discovered;expect(response.ok()).toBe(true);const next=(await response.json()).id;expect(next).not.toBe(original);
 await expect(page.getByText(/Current model: .*noise threshold 0.2/)).toBeVisible();
 await expect(page.getByRole('button',{name:'Run analysis',exact:true})).toBeDisabled();
 await expect(page.getByRole('textbox',{name:'Zone 1 name',exact:true})).toHaveValue('Zone 1');
 await expect(page.locator('input[type=checkbox]:checked:visible')).toHaveCount(0);
 const after=await(await request.get(`/api/datasets/${next}/model`)).json();expect(after.places.length).toBeLessThan(before.places.length);expect(after.event_count).toBe(before.event_count);
 const retained=await(await request.get(`/api/datasets/${original}/model`)).json();expect(retained.places).toEqual(before.places);
});
