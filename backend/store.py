"""Persistence: DuckDB metadata + Parquet artifacts, keyed by input hashes.

Datasets and analyses are content-addressed: the same log + model always maps
to the same dataset id, and the same (dataset, zones, timeframe, backend)
always maps to the same analysis id. Re-running an analysis whose artifacts
already exist is a cache hit — nothing is computed twice.

DataFrames are written as Parquet through DuckDB itself (no extra Arrow
dependency); queries read them back the same way.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Optional

import duckdb
import pandas as pd

from backend import config

_lock = threading.Lock()
_con: Optional[duckdb.DuckDBPyConnection] = None


def _connect() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        config.ensure_dirs()
        _con = duckdb.connect(config.DB_PATH)
        _con.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                name TEXT,
                log_filename TEXT,
                pnml_filename TEXT,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
        _con.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                zones_json TEXT,
                timeframe TEXT,
                backend TEXT,
                status TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
            """
        )
    return _con


def dataset_id_for(log_bytes: bytes, pnml_bytes: Optional[bytes]) -> str:
    h = hashlib.sha256()
    h.update(log_bytes)
    h.update(b"\x00")
    h.update(pnml_bytes or b"")
    return h.hexdigest()[:16]


def analysis_id_for(dataset_id: str, zone_places: dict, timeframe: str, backend: str) -> str:
    # Old artifacts may contain guessed silent paths or unit-weight replay.
    # Never serve those as a cache hit under the corrected replay semantics.
    payload = json.dumps(
        ["chronological-exact-replay-v2", dataset_id, {k: sorted(v) for k, v in sorted(zone_places.items())}, timeframe, backend],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


def dataset_dir(dataset_id: str) -> str:
    return os.path.join(config.DATASETS_DIR, dataset_id)


def save_dataset(
    dataset_id: str,
    name: str,
    log_bytes: bytes,
    log_filename: str,
    pnml_bytes: Optional[bytes],
    pnml_filename: Optional[str],
) -> dict:
    d = dataset_dir(dataset_id)
    os.makedirs(d, exist_ok=True)
    suffix = os.path.splitext(log_filename)[1].lower() or ".csv"
    with open(os.path.join(d, f"log{suffix}"), "wb") as f:
        f.write(log_bytes)
    if pnml_bytes:
        with open(os.path.join(d, "model.pnml"), "wb") as f:
            f.write(pnml_bytes)
    with _lock:
        con = _connect()
        con.execute(
            "INSERT INTO datasets (id, name, log_filename, pnml_filename) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (id) DO NOTHING",
            [dataset_id, name, log_filename, pnml_filename],
        )
    return get_dataset(dataset_id)


def get_dataset(dataset_id: str) -> Optional[dict]:
    with _lock:
        con = _connect()
        row = con.execute(
            "SELECT id, name, log_filename, pnml_filename, created_at FROM datasets WHERE id = ?",
            [dataset_id],
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "log_filename": row[2],
        "pnml_filename": row[3],
        "created_at": str(row[4]),
    }


def list_datasets() -> list[dict]:
    with _lock:
        con = _connect()
        rows = con.execute(
            "SELECT id, name, log_filename, pnml_filename, created_at "
            "FROM datasets ORDER BY created_at DESC"
        ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "log_filename": r[2],
            "pnml_filename": r[3],
            "created_at": str(r[4]),
        }
        for r in rows
    ]


def delete_dataset(dataset_id: str) -> None:
    """Remove a dataset's row and stored files (used when an upload fails the
    fail-fast parse check, so no orphaned entries linger)."""
    import shutil

    with _lock:
        con = _connect()
        con.execute("DELETE FROM datasets WHERE id = ?", [dataset_id])
    shutil.rmtree(dataset_dir(dataset_id), ignore_errors=True)


def dataset_file_paths(dataset_id: str) -> tuple[Optional[str], Optional[str]]:
    """Return (log_path, pnml_path) for a stored dataset."""
    d = dataset_dir(dataset_id)
    if not os.path.isdir(d):
        return None, None
    log_path = None
    for fn in os.listdir(d):
        if fn.startswith("log."):
            log_path = os.path.join(d, fn)
    pnml_path = os.path.join(d, "model.pnml")
    return log_path, (pnml_path if os.path.exists(pnml_path) else None)


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------


def analysis_dir(analysis_id: str) -> str:
    return os.path.join(config.ANALYSES_DIR, analysis_id)


def upsert_analysis(
    analysis_id: str,
    dataset_id: str,
    zone_places: dict,
    timeframe: str,
    backend: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    with _lock:
        con = _connect()
        con.execute(
            """
            INSERT INTO analyses (id, dataset_id, zones_json, timeframe, backend, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET status = excluded.status, error = excluded.error
            """,
            [analysis_id, dataset_id, json.dumps(zone_places), timeframe, backend, status, error],
        )


def get_analysis(analysis_id: str) -> Optional[dict]:
    with _lock:
        con = _connect()
        row = con.execute(
            "SELECT id, dataset_id, zones_json, timeframe, backend, status, error, created_at "
            "FROM analyses WHERE id = ?",
            [analysis_id],
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "dataset_id": row[1],
        "zone_places": json.loads(row[2]),
        "timeframe": row[3],
        "backend": row[4],
        "status": row[5],
        "error": row[6],
        "created_at": str(row[7]),
    }


def list_analyses(dataset_id: Optional[str] = None) -> list[dict]:
    with _lock:
        con = _connect()
        if dataset_id:
            rows = con.execute(
                "SELECT id FROM analyses WHERE dataset_id = ? ORDER BY created_at DESC",
                [dataset_id],
            ).fetchall()
        else:
            rows = con.execute("SELECT id FROM analyses ORDER BY created_at DESC").fetchall()
    return [get_analysis(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# DataFrame artifacts (Parquet via DuckDB)
# ---------------------------------------------------------------------------


def save_frame(analysis_id: str, name: str, df: pd.DataFrame) -> None:
    d = analysis_dir(analysis_id)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{name}.parquet").replace("\\", "/")
    with _lock:
        con = _connect()
        con.register("df_out", df)
        con.execute(f"COPY df_out TO '{path}' (FORMAT PARQUET)")
        con.unregister("df_out")


def load_frame(analysis_id: str, name: str) -> Optional[pd.DataFrame]:
    path = os.path.join(analysis_dir(analysis_id), f"{name}.parquet").replace("\\", "/")
    if not os.path.exists(path):
        return None
    with _lock:
        con = _connect()
        return con.execute(f"SELECT * FROM '{path}'").df()


def has_artifacts(analysis_id: str) -> bool:
    d = analysis_dir(analysis_id)
    return os.path.exists(os.path.join(d, "zone_features.parquet"))
