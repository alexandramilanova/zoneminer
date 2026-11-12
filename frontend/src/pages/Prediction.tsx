import {useEffect,useRef,useState} from 'react';
import {api,type RetrospectiveResult} from '../api';
import {useAppState} from '../state';
import {useResult} from '../lib/useResult';
import {DataTable,NeedsAnalysis,StatTile} from '../components/shared';
import DecisionTree from '../components/DecisionTree';
import ForecastShap from '../components/ForecastShap';

const DEFAULT_TOKEN_METRICS=['token_enter','token_exit','token_present_end','token_avg_present_window','token_netflow','token_avg_duration_completed'];
const fixed=(v?:number)=>v==null?'Unavailable':v.toFixed(3);

export default function Prediction(){
  const {analysisId,analysis}=useAppState();
  const options=useResult(analysisId?`retrospective-options:${analysisId}`:null,()=>api.retrospectiveOptions(analysisId!));
  const data=options.status==='success'?options.data:null;
  const [targetZone,setTargetZone]=useState(''),[targetMetric,setTargetMetric]=useState('');
  const [threshold,setThreshold]=useState(''),[operator,setOperator]=useState('>=');
  const [thresholdSource,setThresholdSource]=useState<'manual'|'suggested'>('suggested');
  const [horizon,setHorizon]=useState(1),[zones,setZones]=useState<string[]>([]),[metrics,setMetrics]=useState<string[]>([]);
  const [result,setResult]=useState<RetrospectiveResult|null>(null),[error,setError]=useState<string|null>(null),[busy,setBusy]=useState(false);
  const [model,setModel]=useState('decision_tree');
  const [balanceClasses,setBalanceClasses]=useState(false);
  const settings=JSON.stringify([analysisId,targetZone,targetMetric,threshold,thresholdSource,operator,horizon,zones,metrics,balanceClasses]);
  const current=useRef(settings);current.current=settings;
  const revision=useRef(0);
  useEffect(()=>{revision.current++;setResult(null);setError(null);},[settings]);
  useEffect(()=>{setTargetZone('');setTargetMetric('');setThreshold('');setZones([]);setMetrics([]);setHorizon(1);},[analysisId]);
  useEffect(()=>()=>{revision.current++;},[]);
  const label=(name:string)=>data?.metrics.find(m=>m.name===name)?.label??name;
  const featureLabel=(name:string)=>{
    for(const metric of data?.metrics??[]){const part=`__${metric.name}`;const i=name.lastIndexOf(part);if(i>=0)return `${name.slice(0,i)} · ${metric.label}${name.slice(i+part.length).replace('__lag',' · lag ')}`;}
    return name;
  };
  const availability=data?.availability[targetZone]?.[targetMetric];
  const suggestion=availability?.suggested_thresholds[operator];
  useEffect(()=>{
    const next=data?.availability[targetZone]?.[targetMetric]?.suggested_thresholds[operator]?.value;
    setThreshold(next==null?'':String(next));setThresholdSource('suggested');
  },[data,targetZone,targetMetric,operator]);
  const valid=!!(data&&targetZone&&targetMetric&&threshold.trim()!==''&&Number.isFinite(Number(threshold))&&zones.length&&metrics.length);
  const pairs=zones.flatMap(zone=>metrics.map(metric=>({zone,metric})));
  const train=async()=>{
    if(!analysisId||!valid)return;
    const snapshot=settings,request=++revision.current;setBusy(true);setResult(null);setError(null);
    try{const next=await api.retrospectivePrediction(analysisId,{target_zone:targetZone,target_metric:targetMetric,
      threshold:Number(threshold),threshold_source:thresholdSource,operator,horizon,feature_pairs:pairs,balance_classes:balanceClasses});
      if(snapshot===current.current&&request===revision.current){setResult(next);setModel('decision_tree');}}
    catch(e){if(snapshot===current.current&&request===revision.current)setError(String(e));}
    finally{setBusy(false);}
  };
  const selected=result?.models.find(m=>m.model_key===model);
  const unit=analysis?.timeframe==='h'?'hour':analysis?.timeframe==='D'?'day':analysis?.timeframe==='7D'?'week':analysis?.timeframe==='30D'?'30-day window':'window';
  return <NeedsAnalysis>
    <h1>Prediction</h1>
    <p className="help">Explore whether current and recent zone metrics distinguish a threshold condition in a later window. Compare decision tree, random forest and histogram gradient boosting using temporal evaluation.</p>
    <div className="notice" data-testid="retrospective-policy"><strong>Retrospective prediction experiment.</strong> Inputs come from complete-trace alignment reconstruction. Results describe the reconstructed historical data; they are not validated live forecasts. Original uploads and descriptive analytics are unchanged.</div>
    {options.status==='loading'&&<p role="status">Loading prediction metrics…</p>}
    {options.status==='error'&&<p role="alert">Prediction setup unavailable: {options.error}</p>}
    {data&&<section className="panel" aria-label="Prediction setup">
      <h2>1. What condition do you want to predict?</h2>
      <div className="row">
        <label>Target zone <select value={targetZone} onChange={e=>{setTargetZone(e.target.value);if(!zones.length)setZones([e.target.value]);}}><option value="">Choose a zone</option>{data.zones.map(z=><option key={z}>{z}</option>)}</select></label>
        <label>Target metric <select value={targetMetric} onChange={e=>setTargetMetric(e.target.value)}><option value="">Choose a metric</option>{data.metrics.map(m=><option key={m.name} value={m.name} disabled={!!targetZone&&!data.availability[targetZone]?.[m.name]?.observed}>{m.label} · {m.unit_label}</option>)}</select></label>
        <label>Condition <select value={operator} onChange={e=>setOperator(e.target.value)}><option value=">=">At least (≥)</option><option value="<=">At most (≤)</option></select></label>
        <label>Threshold <input type="number" step="any" value={threshold} onChange={e=>{setThreshold(e.target.value);setThresholdSource('manual');}} style={{width:110}} placeholder="Your threshold"/></label>
        <label>Prediction horizon <select value={horizon} onChange={e=>setHorizon(Number(e.target.value))}>{Array.from({length:30},(_,i)=>i+1).map(h=><option key={h} value={h}>{h} {unit}{h>1?'s':''} ahead</option>)}</select></label>
      </div>
      {targetMetric&&<p className="help">{data.metrics.find(m=>m.name===targetMetric)?.description} {availability?.observed?`Historical range: ${availability.minimum?.toLocaleString()}–${availability.maximum?.toLocaleString()} (${availability.observed} defined windows). Choose a threshold meaningful for your process; it is not optimized for a high score.`:'No defined values in the selected zone.'}</p>}
      {suggestion?.value!=null&&<p className="help" data-testid="threshold-suggestion">{thresholdSource==='suggested'?'Suggested threshold':'Custom threshold'} · {suggestion.reason} {thresholdSource==='manual'&&<button onClick={()=>{setThreshold(String(suggestion.value));setThresholdSource('suggested');}}>Use suggested threshold ({suggestion.value})</button>}</p>}
      <p className="help">One {unit} ahead means the next analysis window. Longer horizons refer to that specific later window, not any threshold crossing in between. Durations use seconds and ratios use fractions.</p>
      <h2>2. Which information should the models use?</h2>
      <fieldset><legend>Predictor zones</legend><div className="checkgrid">{data.zones.map(z=><label key={z}><input type="checkbox" checked={zones.includes(z)} onChange={e=>setZones(old=>e.target.checked?[...old,z]:old.filter(v=>v!==z))}/>{z}</label>)}</div></fieldset>
      <p><button onClick={()=>setMetrics(DEFAULT_TOKEN_METRICS.filter(m=>data.metrics.some(q=>q.name===m)))}>Use standard token predictors</button> <span className="help">Or choose any available token, case or conformance metrics below.</span></p>
      {['token','case','conformance'].map(family=><details key={family}><summary>{family==='token'?'Token metrics':family==='case'?'Case metrics':'Conformance metrics'} · {metrics.filter(m=>data.metrics.find(q=>q.name===m)?.family===family).length} selected</summary>
        <div className="checkgrid" style={{maxHeight:230,overflow:'auto'}}>{data.metrics.filter(m=>m.family===family).map(m=><label key={m.name} title={`${m.description}${m.scope==='process_window'?' Global window measure repeated across zones.':''}`}><input type="checkbox" aria-label={`Predictor ${m.label}`} checked={metrics.includes(m.name)} onChange={e=>setMetrics(old=>e.target.checked?[...old,m.name]:old.filter(v=>v!==m.name))}/>{m.label} <small>({m.unit_label})</small></label>)}</div>
      </details>)}
      <p className="help">{zones.length} predictor zone(s) × {metrics.length} metric(s). Each includes the current window and three earlier windows. Metrics without observations cannot be trained; undefined targets are excluded rather than treated as negative.</p>
      <label><input type="checkbox" checked={balanceClasses} onChange={e=>setBalanceClasses(e.target.checked)}/> Balance training classes</label>
      <p className="help">Optional: give positive and negative examples equal total training weight, calculated separately inside each fold. This may improve detection of rare conditions at the cost of more false alarms. Evaluation counts and thresholds stay unchanged. Trying both settings remains exploratory.</p>
      <details><summary>How the experiment works</summary><p>All three models run automatically. Standard settings: three history lags, maximum depth 3, minimum leaf size 5, up to five expanding temporal folds, seed 42. Median imputation is fitted within each training fold. Future labels crossing a fold boundary are purged; single-class training folds are reported as skipped.</p><p>{data.interpretation}</p><p>All {data.windows} analysis windows are considered. Suggested thresholds use the full reconstructed target history: the upper quartile for ≥ and lower quartile for ≤, adjusted for sparse values. They are editable exploratory defaults, not business limits or score-optimized cutoffs. No event filtering, inactive-tail trimming or horizon search is performed automatically. Global conformance values repeat across zones; choosing them from multiple zones adds redundant predictors. Some duration, batching and reference-age metrics use later trace information and remain retrospective.</p></details>
      <button className="primary" disabled={busy||!valid||pairs.length>256} onClick={train}>{busy?'Comparing models…':'Compare three models'}</button>
      {pairs.length>256&&<p role="alert">Select at most 256 zone–metric pairs for this experiment.</p>}
      {error&&<p className="notice error" role="alert">{error}</p>}
    </section>}
    {result&&<>
      <section className="panel" aria-label="Experiment results"><h2>Model comparison</h2>
        <p>Condition: <strong>{result.target.zone} · {label(result.target.metric)} {result.target.operator} {result.target.threshold}</strong>, {result.horizon} {unit}{result.horizon>1?'s':''} ahead.</p>
        <div className="grid tiles"><StatTile label="Labeled windows" value={result.training_windows}/><StatTile label="Condition met" value={result.positive_windows} hint={`${(result.positive_rate*100).toFixed(1)}% positive`}/><StatTile label="Condition not met" value={result.negative_windows}/></div>
        {result.warning&&<p className="notice">{result.warning}</p>}
        <p className="notice" data-testid="baseline-verdict">{result.baseline_note}</p>
        {!!result.reconstruction.cases_with_visible_deviation&&<p className="help">{result.reconstruction.cases_with_visible_deviation} of {result.reconstruction.aligned_cases} aligned cases contain visible deviations. Their reconstructed paths include alignment assumptions; inspect the reconstruction record below.</p>}
        <DataTable rows={[
          ...result.models.map(m=>({model:m.model_label,F1:fixed(m.evaluation.f1),precision:fixed(m.evaluation.precision),recall:fixed(m.evaluation.recall),'Evaluated windows':m.evaluation.n_rows,'Actual positives':m.evaluation.positive_rows})),
          ...result.baselines.map(b=>({model:b.model,F1:fixed(b.f1),precision:fixed(b.precision),recall:fixed(b.recall),'Evaluated windows':b.n_rows,'Actual positives':b.positive_rows})),
        ]}/>
        <p className="help">All scores above pool evaluation predictions. Compare rows with matching evaluation support; persistence repeats the current reconstructed condition and may have fewer rows if it is undefined. Precision measures correct positive predictions, recall measures detected positives, and F1 balances both. Undefined denominators use zero. These are exploratory historical scores.</p>
        <p className="help">Training classes: {result.balance_classes?'balanced using training-only weights':'original frequencies'}. Evaluation uses original, unweighted observations.</p>
        <details><summary>Mean scores across temporal folds</summary><DataTable rows={result.models.map(m=>({model:m.model_label,'Mean F1':fixed(m.mean_f1),'Mean precision':fixed(m.mean_precision),'Mean recall':fixed(m.mean_recall),'Valid folds':m.valid_folds}))}/><p className="help">Each valid fold contributes equally to these means. F1 is nonlinear, so mean-fold F1 can differ from pooled F1 above.</p></details>
      </section>
      <section className="panel" aria-label="Model explanation"><h2>Understand a model</h2>
        <div className="row">{result.models.map(m=><button key={m.model_key} aria-pressed={model===m.model_key} onClick={()=>setModel(m.model_key)}>{m.model_label}</button>)}</div>
        {selected&&<><h3>{selected.model_label}</h3>
          {selected.diagnostic&&<p className="notice" data-testid="prediction-diagnostic">{selected.diagnostic}</p>}
          <p>Pooled evaluation: F1 {fixed(selected.evaluation.f1)}, precision {fixed(selected.evaluation.precision)}, recall {fixed(selected.evaluation.recall)} across {selected.evaluation.n_rows} windows.</p>
          <div className="grid tiles"><StatTile label="Correct positives" value={selected.evaluation.confusion.tp}/><StatTile label="Missed positives" value={selected.evaluation.confusion.fn}/><StatTile label="False alarms" value={selected.evaluation.confusion.fp}/><StatTile label="Correct negatives" value={selected.evaluation.confusion.tn}/></div>
          {selected.decision_tree&&<DecisionTree weighted={result.balance_classes} tree={{nodes:selected.decision_tree.nodes.map(n=>({...n,feature:n.feature?featureLabel(n.feature):null}))}}/>}
          <ForecastShap data={{...selected.shap,rows:selected.shap.rows.map(r=>({...r,feature:featureLabel(r.feature)}))}}/>
          {!!selected.feature_importance.length&&<details><summary>Nonzero feature importance</summary><DataTable rows={selected.feature_importance.map(f=>({feature:featureLabel(f.feature),importance:fixed(f.importance)}))}/><p className="help">Final fitted model importance describes its use of features, not a causal process effect.</p></details>}
          <details><summary>Latest-window model estimate · exploratory</summary><p>The final model uses all labeled reconstructed windows and the latest feature row, whose future label is unknown. This estimate is conditional on the reconstructed representation; retrospective evaluation does not establish operational forecast accuracy.</p>
            {selected.estimate.status==='available'?<><p>Feature origin: {selected.estimate.origin}. Target period: [{selected.estimate.target_start}, {selected.estimate.target_end}).</p><p><strong>{selected.estimate.predicted_class===1?'Threshold met':'Threshold not met'}</strong> · class-1 model probability {((selected.estimate.probability??0)*100).toFixed(1)}% (uncalibrated{result.balance_classes?'; fitted with balanced class weights':''}).</p></>:<p>{selected.estimate.reason}</p>}
          </details>
          <details><summary>Inspect temporal folds and predictions</summary><DataTable rows={selected.folds}/><DataTable rows={selected.predictions}/></details>
        </>}
      </section>
      <details className="panel"><summary>Reconstruction and reproducibility</summary><p>{result.reconstruction.source}</p>
        {result.reconstruction.aligned_cases!=null&&<p>{result.reconstruction.aligned_cases} aligned cases · {result.reconstruction.log_only_moves} unmatched observed moves · {result.reconstruction.visible_model_moves} inferred visible model moves · {result.reconstruction.cases_with_visible_deviation} cases with visible deviations. Silent moves are not separately counted in these saved summary tables.</p>}
        <p>{result.reconstruction.timing}</p><p>{result.reconstruction.limitations}</p><p>{result.interpretation}</p><p>Experiment {result.experiment_id} · {result.protocol_version}{result.cached?' · saved result':''}</p>
        <button onClick={()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`retrospective-${result.experiment_id.slice(0,12)}.json`;link.click();URL.revokeObjectURL(url);}}>Download experiment JSON</button>
      </details>
    </>}
  </NeedsAnalysis>;
}
