"""Selected lagged flow associations from completed public-log runs.
No input or application files are modified. Run inside the application runtime.
"""
import json,sys
from pathlib import Path
sys.path.insert(0,'/app')
import numpy as np
import pandas as pd
from scipy import stats
from analytics.dependencies import lagged_best_corr
r=Path('/results');summary=[]
manifest = json.loads((r/'results.json').read_text()) if (r/'results.json').exists() else [dict(name=s['log'], folder=s['folder']) for s in json.loads((r/'correlation-summary.json').read_text())]
for run in manifest:
 folder=r/run['folder'];f=pd.read_csv(folder/'zone_features.csv')
 x=f.pivot(index='window_start',columns='zone',values='case_enter').sort_index()
 y=f.pivot(index='window_start',columns='zone',values='case_exit').sort_index().reindex(index=x.index,columns=x.columns)
 assert x.notna().all().all() and y.notna().all().all()
 ncols=len(x.columns);best=np.full((ncols,ncols),np.nan);lagbest=np.zeros((ncols,ncols),dtype=int);ns=np.zeros_like(lagbest)
 for lag in range(1,8):
  a=x.to_numpy(dtype=float)[:-lag];b=y.to_numpy(dtype=float)[lag:];n=len(a)
  if n<8:continue
  with np.errstate(invalid='ignore',divide='ignore'):
   ac=a-a.mean(axis=0);bc=b-b.mean(axis=0);corr=ac.T@bc/np.sqrt((ac*ac).sum(axis=0)[:,None]*(bc*bc).sum(axis=0)[None,:])
  corr=np.clip(corr,-1,1)
  change=np.isfinite(corr)&(~np.isfinite(best)|(np.abs(corr)>np.abs(best)))
  best[change]=corr[change];lagbest[change]=lag;ns[change]=n
 rows=[]
 for i,z0 in enumerate(x.columns):
  for j,z1 in enumerate(x.columns):
   if i==j or not np.isfinite(best[i,j]):continue
   rho=float(best[i,j]);n=int(ns[i,j]);lag=int(lagbest[i,j]);p=0. if abs(rho)>=1 else float(2*stats.t.sf(abs(rho)*np.sqrt((n-2)/(1-rho*rho)),n-2));p=min(1.,p*7)
   rows.append(dict(log=run['name'],from_zone=z0,to_zone=z1,src_metric='case_enter',tgt_metric='case_exit',best_corr=rho,best_lag_windows=lag,overlap_points=n,source_active_windows=int((x[z0].iloc[:-lag]>0).sum()),target_active_windows=int((y[z1].iloc[lag:]>0).sum()),p_value_lag_adjusted=p))
 allrows=pd.DataFrame(rows);pv=allrows.p_value_lag_adjusted.to_numpy();order=np.argsort(pv);ordered=pv[order]*len(pv)/np.arange(1,len(pv)+1);adjusted=np.minimum.accumulate(ordered[::-1])[::-1].clip(0,1);q=np.empty(len(pv));q[order]=adjusted;allrows['q_value_nominal_bh']=q
 chosen=allrows[allrows.best_corr.abs()>.65].sort_values('best_corr',key=lambda s:s.abs(),ascending=False)
 # Validate selected examples against the unchanged application function.
 for row in chosen.head(5).to_dict('records'):
  c,l,n=lagged_best_corr(x[row['from_zone']],y[row['to_zone']],max_lag=7,min_lag=1,min_points=8)
  assert np.isclose(c,row['best_corr'],atol=1e-10)
  assert np.isclose(abs(c),abs(row['best_corr']),atol=1e-10) and n==row['overlap_points']
 chosen.to_csv(folder/'selected-correlations.csv',index=False)
 summary.append(dict(log=run['name'],folder=run['folder'],valid_pairs_scanned=len(allrows),selected_pairs=len(chosen),threshold='abs(r) > 0.65',source_metric='case_enter',target_metric='case_exit',lags_days=[1,7],minimum_paired_windows=8,max_abs_r=None if chosen.empty else float(chosen.best_corr.abs().max())))
 print(run['folder'],len(chosen),'of',len(allrows),flush=True)
(r/'correlation-summary.json').write_text(json.dumps(summary,indent=2))
