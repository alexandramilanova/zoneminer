"""Run inside ZoneMiner's Docker runtime; inputs in /logs, outputs in /results.
Full logs, default discovery, r4pm replay, daily windows, deterministic structural
zones (connected BFS groups of up to 5 places). This is a pipeline smoke test,
not a validation of domain-specific zone choices or interactive responsiveness.
"""
import json, time, hashlib, sys, traceback
from pathlib import Path
sys.path.insert(0,'/app')
import pandas as pd
from services.pipeline import load_model_inputs, compute_alignment_tables, build_zone_analysis
from process_model.zone_validation import build_place_adjacency, validate_zones
p=Path(sys.argv[1]); out=Path('/results')/p.stem; out.mkdir(parents=True,exist_ok=True)
r={'log':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'backend':'r4pm','timeframe':'D','sampling':False}
start=time.perf_counter()
try:
 t=time.perf_counter(); b=load_model_inputs(p.read_bytes(),'.xes',None); r['load_discovery_seconds']=time.perf_counter()-t
 r.update(cases=len(b.log),events=sum(map(len,b.log)),activities=len({e['concept:name'] for c in b.log for e in c}),places=len(b.net.places),transitions=len(b.net.transitions),import_notice=b.model_notice)
 adj=build_place_adjacency(b.net); remaining=set(adj); zones={}
 while remaining:
  queue=[min(remaining)]; group=[]
  while queue and len(group)<5:
   n=queue.pop(0)
   if n not in remaining:continue
   remaining.remove(n);group.append(n);queue.extend(sorted(adj[n]&remaining))
  zones['Zone '+str(len(zones)+1)]=group
 assert validate_zones(list(zones.items()),sorted(adj),b.net)['zone_config_valid']
 (out/'zones.json').write_text(json.dumps(zones,indent=2));r['zones']=len(zones)
 t=time.perf_counter();tokens,traces,moves=compute_alignment_tables(b.log,b.net,b.im,b.fm,backend='r4pm');r['replay_conformance_seconds']=time.perf_counter()-t
 t=time.perf_counter();a=build_zone_analysis(tokens,traces,zones,'D',log=b.log,net=b.net,im=b.im,fm=b.fm,alignment_moves_df=moves);r['aggregation_seconds']=time.perf_counter()-t
 assert len(traces)==len(b.log)
 f=a['zone_features']; assert not f.empty; assert not f.duplicated(['zone','window_start']).any()
 f.to_csv(out/'zone_features.csv',index=False);tokens.head(500).to_csv(out/'token_intervals_preview.csv',index=False)
 a['case_zone_stays'].head(500).to_csv(out/'case_stays_preview.csv',index=False)
 r.update(status='completed',token_intervals=len(tokens),case_stays=len(a['case_zone_stays']),feature_rows=len(f),fitness_mean=float(traces['fitness'].mean()) if 'fitness' in traces else None,feature_sha256=hashlib.sha256((out/'zone_features.csv').read_bytes()).hexdigest())
except Exception as e:
 r.update(status='failed',error=str(e));traceback.print_exc()
r['total_seconds']=time.perf_counter()-start
(out/'result.json').write_text(json.dumps(r,indent=2,default=str));print(json.dumps(r),flush=True)
