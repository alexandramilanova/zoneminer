"""Pipeline execution for the API: cached model loading + staged analysis jobs.

The in-memory ``ModelBundle`` cache avoids re-parsing a dataset's log on every
request; computed analysis artifacts are persisted through ``backend.store``
so a finished analysis survives restarts and is never recomputed.
"""

from __future__ import annotations

import os
import fcntl
import threading
from collections import OrderedDict
from typing import Optional

from backend import config, store
from backend.jobs import Job
from services import build_zone_analysis, compute_alignment_tables, load_model_inputs
from services.pipeline import ModelBundle

_bundle_cache: OrderedDict[str, ModelBundle] = OrderedDict()
_bundle_load_locks: dict[str, threading.Lock] = {}
_MODEL_CACHE_SIZE = max(1, int(os.environ.get("ZONE_ANALYTICS_MODEL_CACHE_SIZE", "3")))
_bundle_lock = threading.Lock()


def get_bundle(dataset_id: str) -> ModelBundle:
    # The same input hash in two workspaces must not share an in-memory log.
    cache_key = dataset_id if config.data_dir() == config.DATA_DIR else (config.data_dir(), dataset_id)
    with _bundle_lock:
        loading = _bundle_load_locks.setdefault(cache_key, threading.Lock())
    with loading:
        with _bundle_lock:
            cached = _bundle_cache.get(cache_key)
            if cached is not None:
                _bundle_cache.move_to_end(cache_key)
                return cached
        log_path, pnml_path = store.dataset_file_paths(dataset_id)
        if log_path is None:
            raise KeyError(f"Dataset {dataset_id} not found")
        with open(log_path, "rb") as stream:
            log_bytes = stream.read()
        pnml_bytes = None
        if pnml_path:
            with open(pnml_path, "rb") as stream:
                pnml_bytes = stream.read()
        if pnml_bytes is None:
            # Discovery creates generated place identities. Persist the exact
            # discovered net so LRU eviction/restarts cannot change zone IDs or
            # invalidate a zone-independent replay cache. It remains a discovered
            # model, never misrepresented as an independently supplied PNML.
            from pm4py.objects.petri_net.exporter import exporter as pnml_exporter
            directory = store.dataset_dir(dataset_id)
            discovered = os.path.join(directory, "discovered-chronological-v1.pnml")
            with open(discovered + ".lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if os.path.exists(discovered):
                    with open(discovered, "rb") as stream:
                        saved_model = stream.read()
                    bundle = load_model_inputs(log_bytes, os.path.splitext(log_path)[1], saved_model)
                    bundle.model_source = "discovered_from_log"
                    if bundle.model_notice:
                        bundle.model_notice = bundle.model_notice.replace("uploaded Petri net", "persisted discovered Petri net").replace("uploaded model", "persisted discovered model")
                else:
                    bundle = load_model_inputs(log_bytes, os.path.splitext(log_path)[1], None)
                    pnml_exporter.apply(bundle.net, bundle.im, discovered + ".tmp", final_marking=bundle.fm)
                    os.replace(discovered + ".tmp", discovered)
        else:
            bundle = load_model_inputs(log_bytes, os.path.splitext(log_path)[1], pnml_bytes)
        with _bundle_lock:
            _bundle_cache[cache_key] = bundle
            _bundle_cache.move_to_end(cache_key)
            while len(_bundle_cache) > _MODEL_CACHE_SIZE:
                _bundle_cache.popitem(last=False)
        return bundle


def run_analysis_job(
    job: Optional[Job],
    analysis_id: str,
    dataset_id: str,
    zone_places: dict,
    timeframe: str,
    backend: str,
) -> dict:
    """Execute one analysis end to end, emitting staged progress if a job is given."""

    def emit(stage: str, status: str, detail: str = "") -> None:
        if job is not None:
            job.emit(stage, status, detail)

    try:
        store.upsert_analysis(analysis_id, dataset_id, zone_places, timeframe, backend, "running")

        emit("load", "running", "Parsing event log and model")
        bundle = get_bundle(dataset_id)
        emit("load", "done")

        from backend.replay_cache import get_replay_tables
        token_place_df, trace_conformance_df, alignment_moves_df = get_replay_tables(
            dataset_id, backend,
            lambda: compute_alignment_tables(bundle.log, bundle.net, bundle.im, bundle.fm, backend=backend, progress=emit),
            progress=emit,
        )

        emit("features", "running", "Building zone-feature table")
        res = build_zone_analysis(
            token_place_df,
            trace_conformance_df,
            zone_places,
            timeframe,
            net=bundle.net,
            fm=bundle.fm,
            alignment_moves_df=alignment_moves_df,
        )
        emit("features", "done")

        emit("persist", "running", "Persisting artifacts")
        # time_spent is a Timedelta (recomputable from the two timestamps) —
        # dropped for Parquet friendliness
        store.save_frame(
            analysis_id, "token_place", token_place_df.drop(columns=["time_spent"], errors="ignore")
        )
        store.save_frame(analysis_id, "conformance", trace_conformance_df)
        store.save_frame(analysis_id, "alignment_moves", alignment_moves_df)
        # duration (Timedelta) becomes seconds for Parquet friendliness
        stays = res["case_zone_stays"].copy()
        if not stays.empty:
            stays["duration_s"] = stays["duration"].dt.total_seconds()
        else:
            stays["duration_s"] = []
        store.save_frame(analysis_id, "case_zone_stays", stays.drop(columns=["duration"]))
        store.save_frame(analysis_id, "zone_features", res["zone_features"])
        store.save_frame(analysis_id, "zone_leak_diag", res["zone_leak_diag"])
        store.save_frame(analysis_id, "place_leak_diag", res["place_leak_diag"])
        emit("persist", "done")

        store.upsert_analysis(analysis_id, dataset_id, zone_places, timeframe, backend, "done")
        return {"analysis_id": analysis_id}
    except Exception as exc:
        store.upsert_analysis(
            analysis_id, dataset_id, zone_places, timeframe, backend, "error", error=str(exc)
        )
        raise
