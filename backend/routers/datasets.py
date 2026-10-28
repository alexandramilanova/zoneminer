"""Dataset endpoints: upload, listing, model structure, zone validation/suggestions."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend import store
from backend.isolation import endpoint
from backend.runner import get_bundle
from backend.zone_requests import ZoneConfiguration
from process_model.zone_suggestions import (
    readable_activity_labels,
    suggested_places_from_activity_labels,
)
from process_model.zone_validation import validate_zones

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("")
@endpoint
def list_datasets():
    return store.list_datasets()


@router.post("")
async def upload_dataset(
    log: UploadFile = File(...),
    pnml: Optional[UploadFile] = File(None),
    name: Optional[str] = None,
):
    import hashlib
    import os
    from pathlib import Path
    import tempfile
    from backend import config, isolation
    from backend.sessions import check_storage

    log_name = Path(log.filename or "log.csv").name[:200]
    suffix = Path(log_name).suffix.lower()
    if suffix not in {".csv", ".xes"}:
        raise HTTPException(400, "Unsupported log format — upload a .csv or .xes file (uncompressed)")
    dataset_limit = config.optional_limit("MAX_DATASETS")
    if dataset_limit is not None and len(store.list_datasets()) >= dataset_limit:
        raise HTTPException(429, "This workspace has reached its dataset limit.")
    config.ensure_dirs()
    digest = hashlib.sha256()

    async def copy_upload(upload, path, maximum, xml=False):
        total = 0
        tail = b""
        with open(path, "wb") as output:
            while chunk := await upload.read(64 * 1024):
                total += len(chunk)
                if maximum is not None and total > maximum:
                    raise HTTPException(413, "File exceeds the upload limit.")
                if xml:
                    scan = (tail + chunk).replace(b"\x00", b"").lower()
                    if b"<!doctype" in scan or b"<!entity" in scan:
                        raise HTTPException(400, "XML document types and entities are not supported.")
                    tail = chunk[-64:]
                digest.update(chunk)
                output.write(chunk)
                if total // (4 * 1024 * 1024) != (total - len(chunk)) // (4 * 1024 * 1024):
                    check_storage()
        if not total:
            raise HTTPException(400, "Empty upload file")

    with tempfile.TemporaryDirectory(prefix="upload-", dir=config.data_dir()) as tmp:
        log_path = os.path.join(tmp, "log" + suffix)
        model_path = os.path.join(tmp, "model.pnml") if pnml else None
        try:
            upload_limit = config.optional_limit("UPLOAD_MB")
            model_limit = config.optional_limit("MODEL_MB")
            await copy_upload(log, log_path, upload_limit * 1024 * 1024 if upload_limit else None, suffix == ".xes")
            digest.update(b"\x00")
            if pnml:
                await copy_upload(pnml, model_path, model_limit * 1024 * 1024 if model_limit else None, True)
            check_storage()
            dataset_id = digest.hexdigest()[:16]
            existing = store.get_dataset(dataset_id)
            if existing:
                return {**existing, "deduplicated": True}
            meta = store.save_dataset_files(dataset_id, (name or log_name)[:200], log_path, log_name,
                                            model_path, "model.pnml" if pnml else None)
            try:
                if config.data_dir() != config.DATA_DIR:
                    await run_in_threadpool(isolation.run, "backend.isolation", "parse_dataset", dataset_id)
                else:
                    await run_in_threadpool(get_bundle, dataset_id)
                check_storage()
            except Exception as exc:
                store.delete_dataset(dataset_id)
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(422, "Uploaded files could not be parsed. Check the log and model formats.")
            return {**meta, "deduplicated": False}
        finally:
            await log.close()
            if pnml:
                await pnml.close()


@router.get("/{dataset_id}")
@endpoint
def get_dataset(dataset_id: str):
    meta = store.get_dataset(dataset_id)
    if meta is None:
        raise HTTPException(404, "Dataset not found")
    return meta


@router.get("/{dataset_id}/model")
@endpoint
def get_model_graph(dataset_id: str):
    """Petri-net structure as plain JSON for browser-side rendering."""
    try:
        bundle = get_bundle(dataset_id)
    except KeyError:
        raise HTTPException(404, "Dataset not found")
    net, im, fm = bundle.net, bundle.im, bundle.fm

    places = sorted(p.name for p in net.places)
    transitions = [
        {"name": t.name, "label": t.label} for t in sorted(net.transitions, key=lambda t: t.name)
    ]
    arcs = []
    for arc in net.arcs:
        arcs.append({"source": arc.source.name, "target": arc.target.name, "weight": int(arc.weight)})
    return {
        "places": places,
        "transitions": transitions,
        "arcs": arcs,
        "initial_marking": {p.name: int(c) for p, c in im.items()},
        "final_marking": {p.name: int(c) for p, c in fm.items()},
        "activity_labels": readable_activity_labels(bundle.process_tree, net),
        "model_source": bundle.model_source,
        "model_notice": bundle.model_notice,
        "process_tree_available": bundle.process_tree is not None,
        "bpmn_available": getattr(bundle, "bpmn_graph", None) is not None,
        "process_tree_reason": getattr(bundle, "process_tree_notice", None),
        "bpmn_reason": getattr(bundle, "bpmn_notice", None),
    }


class ZoneValidationRequest(ZoneConfiguration):
    pass


@router.post("/{dataset_id}/zones/validate")
@endpoint
def validate_zone_system(dataset_id: str, body: ZoneValidationRequest):
    try:
        bundle = get_bundle(dataset_id)
    except KeyError:
        raise HTTPException(404, "Dataset not found")
    place_names = sorted(p.name for p in bundle.net.places)
    result = validate_zones(
        zone_inputs=body.zone_inputs(),
        place_names=place_names,
        net=bundle.net,
        require_non_empty=True,
        allow_unassigned_places=True,
        require_connected=True,
    )
    return {
        "valid": bool(result["zone_config_valid"]),
        "errors": result["errors"],
        "warnings": result["warnings"],
        "zone_places": result["zone_places"],
    }


@router.get("/{dataset_id}/bpmn.xml")
@endpoint
def get_bpmn_xml(dataset_id: str):
    """BPMN 2.0 XML of the readable model view (for browser-side bpmn-js)."""
    import os
    import tempfile

    from fastapi.responses import Response

    try:
        bundle = get_bundle(dataset_id)
    except KeyError:
        raise HTTPException(404, "Dataset not found")
    if bundle.bpmn_graph is None:
        raise HTTPException(404, bundle.bpmn_notice or "BPMN cannot be generated for this model. Use the Petri net for inspection.")
    import pm4py

    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bpmn") as f:
            path = f.name
        pm4py.write_bpmn(bundle.bpmn_graph, path)
        with open(path, "rb") as f:
            xml = f.read()
    finally:
        if path and os.path.exists(path):
            os.remove(path)
    return Response(content=xml, media_type="application/xml")


@router.get("/{dataset_id}/process-tree.svg")
@endpoint
def get_process_tree_svg(dataset_id: str):
    """Readable process-tree helper view, rendered server-side to SVG."""
    from fastapi.responses import Response
    from pm4py.visualization.process_tree import visualizer as process_tree_visualizer

    try:
        bundle = get_bundle(dataset_id)
    except KeyError:
        raise HTTPException(404, "Dataset not found")
    if bundle.process_tree is None:
        raise HTTPException(404, bundle.process_tree_notice or "This model has no convertible block-structured process tree. Use the Petri net for inspection.")
    gviz = process_tree_visualizer.apply(
        bundle.process_tree, variant=process_tree_visualizer.Variants.SYMBOLIC
    )
    svg = gviz.pipe(format="svg")
    return Response(content=svg, media_type="image/svg+xml")


class ZoneSuggestionRequest(BaseModel):
    activities: list[str]


@router.post("/{dataset_id}/zones/suggest")
@endpoint
def suggest_zone_places(dataset_id: str, body: ZoneSuggestionRequest):
    """Suggest Petri-net places for a zone from selected activity labels."""
    try:
        bundle = get_bundle(dataset_id)
    except KeyError:
        raise HTTPException(404, "Dataset not found")
    places = suggested_places_from_activity_labels(bundle.net, list(body.activities))
    return {"places": places}
