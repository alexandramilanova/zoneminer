import {test,expect} from '@playwright/test';

test('retained research API freezes earlier models independently of the retrospective UI',async({request})=>{
  test.setTimeout(120000);
  const rows=['case_id,concept:name,time:timestamp'];
  for(let block=0;block<20;block++)for(let n=0;n<(block%4<2?1:4);n++){
    const at=new Date(Date.UTC(2024,0,1,block*4,10+n));
    rows.push(`${block}-${n},A,${at.toISOString()}`,`${block}-${n},B,${new Date(at.getTime()+2*3600000).toISOString()}`);
  }
  const upload=await request.post('/api/datasets',{multipart:{log:{name:'calibration-workflow.csv',mimeType:'text/csv',buffer:Buffer.from(rows.join('\n'))}}});
  expect(upload.ok()).toBe(true);const dataset=(await upload.json()).id;
  const graph=await(await request.get(`/api/datasets/${dataset}/model`)).json();
  const place=graph.places.find((p:string)=>!graph.initial_marking[p]&&!graph.final_marking[p]);
  const created=await(await request.post(`/api/datasets/${dataset}/analyses`,{data:{zones:{Descriptive:[place]},timeframe:'h'}})).json();
  if(created.job_id)await expect.poll(async()=>(await(await request.get(`/api/jobs/${created.job_id}`)).json()).status,{timeout:120000}).toBe('done');
  const before=await(await request.get(`/api/analyses/${created.analysis_id}/features`)).text();
  const original=await(await request.get(`/api/analyses/${created.analysis_id}/prediction/options`)).json();
  expect(original.calibration_required).toBe(true);
  const calibrated=await(await request.post(`/api/analyses/${created.analysis_id}/prediction/calibrate`,{data:{calibration_end:'2024-01-01T20:00:00Z'}})).json();
  const internal=calibrated.places.find((p:string)=>!calibrated.initial_marking[p]&&!calibrated.final_marking[p]);
  expect((await request.post(`/api/analyses/${created.analysis_id}/prediction/studies`,{data:{calibration_id:calibrated.calibration.id,zones:{}}})).status()).toBe(422);
  const study=await(await request.post(`/api/analyses/${created.analysis_id}/prediction/studies`,{data:{calibration_id:calibrated.calibration.id,zones:{Earlier:[internal]}}})).json();
  const options=await(await request.get(`/api/analyses/${created.analysis_id}/prediction/options?study_id=${study.id}`)).json();
  expect(options.metrics.filter((m:any)=>m.forecast_supported)).toHaveLength(2);
  const response=await request.post(`/api/analyses/${created.analysis_id}/prediction`,{data:{study_id:study.id,target_zone:'Earlier',target_metric:'token_present_end',threshold:3,horizon:1,development_end:'2024-01-03T08:00:00Z',observed_through:options.window_ends.at(-1),protocol_acknowledged:true,history_lags:0,feature_pairs:[{zone:'Earlier',metric:'case_present_end'}]}});
  expect(response.ok(),await response.text()).toBe(true);
  expect((await response.json()).models).toHaveLength(3);
  expect(await(await request.get(`/api/analyses/${created.analysis_id}/features`)).text()).toBe(before);
});
