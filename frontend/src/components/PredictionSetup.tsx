import { useEffect, useRef, useState } from 'react';
import { api, type ForecastOptions, type ZoneDraft } from '../api';
import PetriNetView from './PetriNetView';

export default function PredictionSetup({analysisId, windows, frozen, onStudy}: {
  analysisId: string; windows: string[]; frozen: ForecastOptions['study']; onStudy: (id:string|null)=>void;
}) {
  const [end,setEnd] = useState('');
  const [graph,setGraph] = useState<Awaited<ReturnType<typeof api.calibratePrediction>>|null>(null);
  const [zones,setZones] = useState<ZoneDraft[]>([{name:'Prediction zone 1',places:[]}]);
  const [active,setActive] = useState(0);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState<string|null>(null);
  const revision = useRef(0);
  useEffect(()=>()=>{revision.current++},[]);
  const edit = (next:ZoneDraft[]) => {revision.current++;setZones(next);setError(null);};
  const prepare = async () => {
    const request=++revision.current;setBusy(true);setError(null);setGraph(null);
    try {const next=await api.calibratePrediction(analysisId,end);if(request===revision.current){setGraph(next);setZones([{name:'Prediction zone 1',places:[]}]);setActive(0);}}
    catch(e){if(request===revision.current)setError(String(e));}
    finally{if(request===revision.current)setBusy(false);}
  };
  const freeze = async () => {
    if(!graph)return;const request=++revision.current;setBusy(true);setError(null);
    try{const next=await api.freezePrediction(analysisId,graph.calibration.id,zones);if(request===revision.current)onStudy(next.id);}
    catch(e){if(request===revision.current)setError(String(e));}
    finally{setBusy(false);}
  };
  const toggle=(place:string)=>{
    if(busy||!zones[active]||zones.some((z,i)=>i!==active&&z.places.includes(place)))return;
    edit(zones.map((z,i)=>i===active?{...z,places:z.places.includes(place)?z.places.filter(p=>p!==place):[...z.places,place]}:z));
  };
  return <section className="panel" aria-label="Prediction model and zones">
    <h2>Prediction model and zones</h2>
    <p>Learn a separate model from events strictly before a calibration cutoff. Then define and freeze zones on that model. Calibration events are excluded from experimental feature windows. The descriptive model and zones remain unchanged.</p>
    {frozen ? <><p role="status">Frozen prediction study · calibration ended {frozen.calibration_end}. {Object.keys(frozen.zone_places).length} prediction zones.</p>
      <button onClick={()=>{revision.current++;setGraph(null);setEnd('');onStudy(null);}}>Change prediction study</button></> : <>
      <label>Calibration cutoff (UTC) <select value={end} disabled={busy} onChange={e=>{revision.current++;setEnd(e.target.value);setGraph(null);}}>
        <option value="">Choose before the experiment</option>{windows.slice(0,-1).map(w=><option key={w}>{w}</option>)}
      </select></label>{' '}<button onClick={prepare} disabled={!end||busy}>Discover prediction model</button>
      {graph && <>
        <p>{graph.calibration.observed_events} observed calibration events in {graph.calibration.observed_cases} case prefixes. No future case-completion information was used. Full-log place selections are not transferred.</p>
        <label>Active prediction zone <select value={active} disabled={busy} onChange={e=>setActive(Number(e.target.value))}>{zones.map((z,i)=><option value={i} key={i}>{z.name||`Zone ${i+1}`}</option>)}</select></label>{' '}
        <button disabled={busy} onClick={()=>{edit([...zones,{name:`Prediction zone ${zones.length+1}`,places:[]}]);setActive(zones.length);}}>Add prediction zone</button>
        {zones.map((z,i)=><div className="row" key={i}><label>Prediction zone {i+1} name <input disabled={busy} value={z.name} onChange={e=>edit(zones.map((q,j)=>i===j?{...q,name:e.target.value}:q))}/></label>
          <span>{z.places.length} places</span><button disabled={busy} onClick={()=>{edit(zones.filter((_,j)=>j!==i));setActive(0);}}>Remove prediction zone {i+1}</button></div>)}
        <PetriNetView graph={graph} zoneOf={Object.fromEntries(zones.flatMap(z=>z.places.map(p=>[p,z.name])))} zoneColorOf={name=>`var(--zone-${(zones.findIndex(z=>z.name===name)%8)+1})`} onPlaceClick={toggle} height={320}/>
        <details><summary>Select prediction places by name</summary><div className="checkgrid" style={{maxHeight:240,overflow:'auto'}}>{graph.places.map(p=><label key={p}>
          <input type="checkbox" aria-label={`Prediction place ${p}`} disabled={busy||!zones[active]||zones.some((z,i)=>i!==active&&z.places.includes(p))} checked={zones[active]?.places.includes(p)??false} onChange={()=>toggle(p)}/>{p}</label>)}</div></details>
        <p>Zones must be nonempty, disjoint and connected, as in descriptive analytics. Grouping places across silent alternatives can make occupancy identifiable; a single place may remain ambiguous. Final-place occupancy persists after process completion.</p>
        <button className="primary" disabled={busy} onClick={freeze}>Validate and freeze prediction zones</button>
      </>}
    </>}
    {busy&&<p role="status">Preparing prediction study…</p>}{error&&<p role="alert">{error}</p>}
  </section>;
}
