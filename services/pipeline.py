"""Pipeline orchestration: inputs -> model -> alignments -> zone-feature table.

Logic moved verbatim from the Streamlit app's cached functions so that the
computation is identical whether driven by Streamlit, FastAPI, a script, or a
test. No Streamlit imports are allowed in this module.
"""

import os
import tempfile
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from process_model.conformance import (
    alignment_move_table_from_alignments,
    trace_conformance_table_from_alignments,
)
from process_model.diagnostics import add_leak_diagnostics
from process_model.features import (
    build_case_zone_stays_from_places,
    build_zone_token_features_from_places,
)
from process_model.io import (
    bpmn_from_process_tree,
    bpmn_from_petri_net,
    process_tree_unavailable_reason,
    discover_process_tree_from_log,
    load_any_log,
    load_csv_log,
    load_pnml,
    petri_net_from_process_tree,
    try_process_tree_from_petri_net,
)
from process_model.alignment_backends import compute_alignments
from process_model.replay import token_place_table_from_alignments


@dataclass
class ModelBundle:
    """Everything derived from the uploaded/discovered inputs, pre-analysis."""

    log: object
    net: object
    im: object
    fm: object
    process_tree: Optional[object]
    bpmn_graph: Optional[object]
    model_source: str  # "uploaded_petri_net" | "discovered_from_log"
    model_notice: Optional[str]
    process_tree_notice: Optional[str] = None
    bpmn_notice: Optional[str] = None

    def as_tuple(self):
        """Positional form used by the Streamlit cache wrapper."""
        return (
            self.log,
            self.net,
            self.im,
            self.fm,
            self.process_tree,
            self.bpmn_graph,
            self.model_source,
            self.model_notice,
        )


def load_model_inputs(
    log_bytes: bytes,
    log_suffix: str,
    pnml_bytes: Optional[bytes],
) -> ModelBundle:
    """Load the event log and obtain a Petri net (uploaded PNML or discovered).

    Also derives the optional readable views (process tree, BPMN). A failure to
    derive a readable view is reported via ``model_notice``, never raised — the
    Petri net alone is sufficient for analysis.
    """
    log_path = pn_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=log_suffix) as f:
            f.write(log_bytes)
            log_path = f.name

        if log_suffix.lower() == ".xes":
            log = load_any_log(log_path)
        elif log_suffix.lower() == ".csv":
            log = load_csv_log(log_path)
        else:
            raise ValueError("Unsupported log format (use .xes or .csv)")

        process_tree = None
        bpmn_graph = None
        model_notice = None
        process_tree_notice = None
        bpmn_notice = None
        model_source = "uploaded_petri_net" if pnml_bytes else "discovered_from_log"

        if pnml_bytes:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pnml") as f:
                f.write(pnml_bytes)
                pn_path = f.name
            net, im, fm = load_pnml(pn_path)
            process_tree, tree_error = try_process_tree_from_petri_net(net, im, fm)
            if process_tree is not None:
                try:
                    bpmn_graph = bpmn_from_process_tree(process_tree)
                except Exception as exc:
                    bpmn_notice = "BPMN could not be generated for this model. Use the Petri net to inspect and define zones."
            else:
                process_tree_notice = process_tree_unavailable_reason(tree_error)
            if bpmn_graph is None:
                try:
                    bpmn_graph = bpmn_from_petri_net(net, im, fm)
                    bpmn_notice = None
                except ValueError as exc:
                    bpmn_notice = str(exc) + " Use the Petri net for inspection."
                except Exception:
                    bpmn_notice = "BPMN could not be generated for this model. Use the Petri net to inspect and define zones."
        else:
            process_tree = discover_process_tree_from_log(log)
            net, im, fm = petri_net_from_process_tree(process_tree)
            try:
                bpmn_graph = bpmn_from_process_tree(process_tree)
            except Exception as exc:
                bpmn_notice = "BPMN could not be generated for this model. Use the Petri net to inspect and define zones."

        report = log.attributes.get("zone_analytics:import_order", {})
        if report.get("reordered_cases"):
            notice = (f"Import ordered {report['reordered_cases']:,} cases chronologically "
                      f"({report['moved_events']:,} events changed position). Recorded timestamps were not repaired; "
                      "check source-data inconsistencies before interpreting durations or process order. Equal timestamps retain file order.")
            model_notice = f"{model_notice} {notice}" if model_notice else notice

        return ModelBundle(
            log=log,
            net=net,
            im=im,
            fm=fm,
            process_tree=process_tree,
            bpmn_graph=bpmn_graph,
            model_source=model_source,
            model_notice=model_notice,
            process_tree_notice=process_tree_notice,
            bpmn_notice=bpmn_notice,
        )
    finally:
        for p in [log_path, pn_path]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def compute_alignment_tables(
    log, net, im, fm, backend: Optional[str] = None, progress=None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Alignment replay: token-place intervals + per-trace conformance +
    timed alignment-move table (basis for zone-attributed conformance).

    ``backend`` selects the alignment engine ('pm4py' reference or 'r4pm'
    fast Rust backend; default resolves via the
    ZONE_ANALYTICS_ALIGNMENT_BACKEND env var, falling back to pm4py).
    Everything downstream of the raw alignments is shared code — see
    process_model/alignment_backends.py.
    """
    def emit(stage, status, detail):
        if progress:
            progress(stage, status, detail)
    emit("align", "running", f"{len(log):,} cases; {backend or 'configured'} backend; unique variants reused")
    def aligned_variants(done, total):
        emit("align", "running", f"Aligned {done:,} / {total:,} unique variants ({len(log):,} cases)")
    aligned = compute_alignments(log, net, im, fm, backend=backend, progress=aligned_variants if progress else None)
    emit("align", "done", f"{len(aligned):,} cases aligned")
    emit("replay", "running", f"Reconstructing weighted tokens for {len(log):,} cases")
    token_place_df = token_place_table_from_alignments(log, net, im, fm, aligned=aligned)
    emit("replay", "done", f"{len(token_place_df):,} token-place intervals")
    emit("conformance", "running", "Building trace summaries and timed alignment moves")
    trace_conformance_df = trace_conformance_table_from_alignments(log, aligned)
    alignment_moves_df = alignment_move_table_from_alignments(log, aligned, net)
    emit("conformance", "done", f"{len(alignment_moves_df):,} timed visible moves")
    return token_place_df, trace_conformance_df, alignment_moves_df


def build_zone_analysis(
    token_place_df: pd.DataFrame,
    trace_conformance_df: pd.DataFrame,
    zone_places: dict,
    timeframe: str,
    log=None,
    net=None,
    im=None,
    fm=None,
    alignment_moves_df: Optional[pd.DataFrame] = None,
) -> dict:
    """Build the zone-feature table plus leak diagnostics.

    Returns the same result dict shape the Streamlit app stores in
    ``st.session_state.res`` (model objects included only when passed).
    Pass ``alignment_moves_df`` (+ net) to populate the zone-attributed
    conformance columns; without it they are zeros.
    """
    case_zone_stays = build_case_zone_stays_from_places(token_place_df, zone_places)
    zone_feat = build_zone_token_features_from_places(
        token_place_df,
        zone_places,
        timeframe=timeframe,
        trace_conformance_df=trace_conformance_df,
        alignment_moves_df=alignment_moves_df,
        net=net,
        case_zone_df=case_zone_stays,
    )
    zone_diag, place_diag = add_leak_diagnostics(
        token_place_df,
        zone_feat,
        zone_places,
        fm=fm,
    )
    return {
        "log": log,
        "net": net,
        "im": im,
        "fm": fm,
        "token_place_df": token_place_df,
        "trace_conformance_df": trace_conformance_df,
        "case_zone_stays": case_zone_stays,
        "zone_features": zone_feat,
        "zone_leak_diag": zone_diag,
        "place_leak_diag": place_diag,
    }


def run_demo_pipeline(log_path: str, pnml_path: Optional[str], zone_places: dict, timeframe: str = "D") -> dict:
    """Headless end-to-end run from file paths (baseline recording, demos, tests)."""
    with open(log_path, "rb") as f:
        log_bytes = f.read()
    pnml_bytes = None
    if pnml_path:
        with open(pnml_path, "rb") as f:
            pnml_bytes = f.read()
    suffix = os.path.splitext(log_path)[1]
    bundle = load_model_inputs(log_bytes, suffix, pnml_bytes)
    token_place_df, trace_conformance_df, alignment_moves_df = compute_alignment_tables(
        bundle.log, bundle.net, bundle.im, bundle.fm
    )
    return build_zone_analysis(
        token_place_df,
        trace_conformance_df,
        zone_places,
        timeframe,
        log=bundle.log,
        net=bundle.net,
        im=bundle.im,
        fm=bundle.fm,
        alignment_moves_df=alignment_moves_df,
    )
