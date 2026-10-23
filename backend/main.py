"""FastAPI application: routers, CORS, demo-dataset registration, static frontend.

Run in development with:
    uvicorn backend.main:app --reload --port 8000

In the local Docker application the built React frontend (frontend/dist) is
served by this same app, so one free-tier container hosts everything.
"""

from __future__ import annotations

import json
import mimetypes
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Python's mimetypes reads the Windows registry, which frequently maps .js to
# text/plain — browsers then refuse to execute module scripts and the SPA
# renders as a blank page. Register the correct types explicitly so serving
# the frontend works on every host OS.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/wasm", ".wasm")

from backend import config, store
from backend.routers import analyses, datasets


def _register_bundled(dataset_id: str, name: str, log_filename: str) -> None:
    if store.get_dataset(dataset_id) is not None:
        return
    log_path = os.path.join(config.DEMO_DIR, log_filename)
    pnml_path = os.path.join(config.DEMO_DIR, "order_process.pnml")
    if not (os.path.exists(log_path) and os.path.exists(pnml_path)):
        return
    with open(log_path, "rb") as f:
        log_bytes = f.read()
    with open(pnml_path, "rb") as f:
        pnml_bytes = f.read()
    store.save_dataset(dataset_id, name, log_bytes, log_filename, pnml_bytes, "order_process.pnml")


def register_demo_dataset() -> None:
    """Register the bundled datasets: 'demo' (small; CI/baseline) and
    'showcase' (35 days, all four injected drifts; the one-click demo)."""
    _register_bundled(config.DEMO_DATASET_ID, "Demo: Online Order Fulfillment (small)", "demo_log_small.csv")
    _register_bundled(
        config.SHOWCASE_DATASET_ID,
        "Showcase: Online Order Fulfillment (4 drifts, 35 days)",
        "demo_log_showcase.csv",
    )


def demo_zone_places() -> dict:
    with open(os.path.join(config.DEMO_DIR, "zones.json"), encoding="utf-8") as f:
        return json.load(f)


def list_examples() -> list[dict]:
    """Bundled example scenarios: [{dataset_id, title, description,
    highlights, zones, timeframe}], sorted by folder name."""
    out = []
    if not os.path.isdir(config.EXAMPLES_DIR):
        return out
    for entry in sorted(os.listdir(config.EXAMPLES_DIR)):
        d = os.path.join(config.EXAMPLES_DIR, entry)
        meta_path = os.path.join(d, "meta.json")
        zones_path = os.path.join(d, "zones.json")
        if not (os.path.isfile(meta_path) and os.path.isfile(zones_path)):
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        with open(zones_path, encoding="utf-8") as f:
            zones = json.load(f)
        out.append(
            {
                "dataset_id": entry,
                "title": meta.get("title", entry),
                "description": meta.get("description", ""),
                "highlights": meta.get("highlights", []),
                "zones": zones,
                "timeframe": meta.get("timeframe", "D"),
            }
        )
    return out


def register_example_datasets() -> None:
    """Register every bundled example scenario as a dataset (folder name =
    dataset id)."""
    for ex in list_examples():
        dataset_id = ex["dataset_id"]
        if store.get_dataset(dataset_id) is not None:
            continue
        d = os.path.join(config.EXAMPLES_DIR, dataset_id)
        log_path = os.path.join(d, "log.csv")
        pnml_path = os.path.join(d, "model.pnml")
        if not (os.path.exists(log_path) and os.path.exists(pnml_path)):
            continue
        with open(log_path, "rb") as f:
            log_bytes = f.read()
        with open(pnml_path, "rb") as f:
            pnml_bytes = f.read()
        store.save_dataset(
            dataset_id, f"Example: {ex['title']}", log_bytes, "log.csv", pnml_bytes, "model.pnml"
        )


def create_app() -> FastAPI:
    app = FastAPI(
        title="ZoneMiner API",
        description=(
            "Zone-based token-flow analytics over business-process event logs. "
            "Wraps alignment replay, zone-feature construction, and the "
            "descriptive/predictive analyses behind typed HTTP endpoints."
        ),
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(datasets.router)
    app.include_router(analyses.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/demo")
    def demo_info():
        """The one-click demo scenario: the showcase dataset when bundled,
        else the small demo."""
        dataset_id = (
            config.SHOWCASE_DATASET_ID
            if store.get_dataset(config.SHOWCASE_DATASET_ID) is not None
            else config.DEMO_DATASET_ID
        )
        return {
            "dataset_id": dataset_id,
            "zones": demo_zone_places(),
            "timeframe": "D",
        }

    @app.get("/api/examples")
    def examples():
        """Bundled example scenarios, each spotlighting one analysis family."""
        return {"examples": list_examples()}

    @app.on_event("startup")
    def _startup() -> None:
        config.ensure_dirs()
        register_demo_dataset()
        register_example_datasets()

    if os.path.isdir(config.FRONTEND_DIST):
        app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
