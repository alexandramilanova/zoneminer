import { useEffect, useRef, useState } from "react";
import { api } from "../api";

/** Each zone owns its activity selection and pending/result state. */
export default function ZonePlaceSuggestions({ datasetId, zoneName, activities, takenElsewhere, onApply }: {
  datasetId: string;
  zoneName: string;
  activities: string[];
  takenElsewhere: Set<string>;
  onApply: (places: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [selectedActivities, setSelectedActivities] = useState<string[]>([]);
  const [suggested, setSuggested] = useState<string[] | null>(null);
  const [selectedPlaces, setSelectedPlaces] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);
  useEffect(() => () => { request.current += 1; }, []);

  const suggest = async () => {
    const version = ++request.current;
    setPending(true);
    setError(null);
    setSuggested(null);
    try {
      const result = await api.suggestPlaces(datasetId, selectedActivities);
      if (request.current !== version) return;
      setSuggested(result.places);
      setSelectedPlaces(result.places);
    } catch (e) {
      if (request.current === version) setError(String(e));
    } finally {
      if (request.current === version) setPending(false);
    }
  };
  const eligible = selectedPlaces.filter((p) => !takenElsewhere.has(p));

  return <details style={{ marginTop: 10 }} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary style={{ cursor: "pointer" }}>Suggest places from activity names</summary>
    {open && <>
    <p className="help">Select activities for “{zoneName}”. The heuristic proposes places around and between them; select which suggestions to add. Places assigned to other zones stay there.</p>
    <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="help">Activities</legend>
      <div className="checkgrid">{activities.map((activity) => <label key={activity}>
        <input type="checkbox" checked={selectedActivities.includes(activity)} onChange={(e) => {
          request.current += 1;
          setPending(false);
          setSuggested(null);
          setSelectedPlaces([]);
          setError(null);
          setSelectedActivities((previous) => e.target.checked ? [...previous, activity] : previous.filter((a) => a !== activity));
        }} />{activity}
      </label>)}</div>
    </fieldset>
    <button style={{ marginTop: 8 }} disabled={!selectedActivities.length || pending} onClick={suggest}>
      {pending ? "Suggesting…" : "Suggest places"}
    </button>
    {error && <p role="alert" className="notice error">Place suggestions unavailable: {error}</p>}
    {suggested?.length === 0 && <p role="status">No places could be derived from that selection.</p>}
    {!!suggested?.length && <>
      <fieldset style={{ border: 0, padding: 0, margin: "8px 0" }}>
        <legend>Suggested places</legend>
        <div className="checkgrid">{suggested.map((place) => <label key={place}>
          <input type="checkbox" disabled={takenElsewhere.has(place)} checked={!takenElsewhere.has(place) && selectedPlaces.includes(place)}
            onChange={(e) => setSelectedPlaces((previous) => e.target.checked ? [...previous, place] : previous.filter((p) => p !== place))} />
          {place}{takenElsewhere.has(place) && " (assigned to another zone)"}
        </label>)}</div>
      </fieldset>
      <button className="primary" disabled={!eligible.length} onClick={() => {
        onApply(eligible);
        setSuggested(null);
        setSelectedPlaces([]);
      }}>Apply selected places to zone</button>
    </>}
    </>}
  </details>;
}
