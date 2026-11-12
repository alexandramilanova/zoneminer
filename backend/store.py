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
import re
import threading
from contextlib import contextmanager
from typing import Optional

import duckdb
import pandas as pd

from backend import config

_lock = threading.Lock()
_con: Optional[duckdb.DuckDBPyConnection] = None
_workspace_connections: dict[str, duckdb.DuckDBPyConnection] = {}


@contextmanager
def _access():
    # Anonymous workers are separate processes. Never leave a DuckDB connection
    # open across calls, and serialize metadata access across those processes.
    with _lock:
        root = config.data_dir()
        if root == config.DATA_DIR:
            yield
            return
        import fcntl
        config.ensure_dirs()
        with open(os.path.join(root, "store.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                connection = _workspace_connections.pop(root, None)
                if connection is not None:
                    connection.close()


def _connect() -> duckdb.DuckDBPyConnection:
    global _con
    root = config.data_dir()
    connection = _con if root == config.DATA_DIR else _workspace_connections.get(root)
    if connection is None:
        config.ensure_dirs()
        connection = duckdb.connect(os.path.join(root, "store.duckdb"))
        if root == config.DATA_DIR:
            _con = connection
        else:
            _workspace_connections[root] = connection
        connection.execute(
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
        connection.execute(
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
    return connection


def close_workspace(root: str) -> None:
    with _lock:
        connection = _workspace_connections.pop(root, None)
        if connection is not None:
            connection.close()


def _safe_id(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier):
        raise ValueError("Invalid artifact identifier")
    return identifier


def discovery_identity_suffix(noise_threshold: float) -> bytes:
    """Keep legacy identities at zero; settings distinguish immutable models."""
    if not 0 <= noise_threshold <= 1:
        raise ValueError("Discovery noise threshold must be between 0 and 1")
    return (b"\x00discovery-noise-v1:" + str(float(noise_threshold)).encode()
            if noise_threshold else b"")


def dataset_id_for(log_bytes: bytes, pnml_bytes: Optional[bytes], noise_threshold: float = 0.0) -> str:
    h = hashlib.sha256()
    h.update(log_bytes)
    h.update(b"\x00")
    h.update(pnml_bytes or b"")
    h.update(discovery_identity_suffix(noise_threshold))
    return h.hexdigest()[:16]


def analysis_id_for(dataset_id: str, zone_places: dict, timeframe: str, backend: str) -> str:
    # Old artifacts may contain guessed silent paths or unit-weight replay.
    # Never serve those as a cache hit under the corrected replay semantics.
    payload = json.dumps(
        ["canonical-alignment-replay-v4", dataset_id, {k: sorted(v) for k, v in sorted(zone_places.items())}, timeframe, backend],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


def dataset_dir(dataset_id: str) -> str:
    return os.path.join(config.data_dir(), "datasets", _safe_id(dataset_id))


def discovery_threshold(dataset_id: str) -> float:
    path = os.path.join(dataset_dir(dataset_id), "discovery.json")
    if not os.path.exists(path):
        return 0.0
    with open(path) as stream:
        value = float(json.load(stream)["noise_threshold"])
    discovery_identity_suffix(value)
    return value


def save_discovery_threshold(dataset_id: str, noise_threshold: float) -> None:
    discovery_identity_suffix(noise_threshold)
    if noise_threshold:
        with open(os.path.join(dataset_dir(dataset_id), "discovery.json"), "w") as stream:
            json.dump({"noise_threshold": noise_threshold}, stream)


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
    with _access():
        con = _connect()
        con.execute(
            "INSERT INTO datasets (id, name, log_filename, pnml_filename) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (id) DO NOTHING",
            [dataset_id, name, log_filename, pnml_filename],
        )
    return get_dataset(dataset_id)


def save_dataset_files(dataset_id, name, log_path, log_filename, pnml_path, pnml_filename):
    """Copy bounded, streamed uploads without materializing them as bytes."""
    import shutil
    directory = dataset_dir(dataset_id)
    os.makedirs(directory, exist_ok=True)
    shutil.copyfile(log_path, os.path.join(directory, "log" + os.path.splitext(log_filename)[1].lower()))
    if pnml_path:
        shutil.copyfile(pnml_path, os.path.join(directory, "model.pnml"))
    with _access():
        _connect().execute("INSERT INTO datasets (id, name, log_filename, pnml_filename) VALUES (?, ?, ?, ?) ON CONFLICT (id) DO NOTHING",
                           [dataset_id, name, log_filename, pnml_filename])
    return get_dataset(dataset_id)


def get_dataset(dataset_id: str) -> Optional[dict]:
    with _access():
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
    with _access():
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

    with _access():
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
    return os.path.join(config.data_dir(), "analyses", _safe_id(analysis_id))


def upsert_analysis(
    analysis_id: str,
    dataset_id: str,
    zone_places: dict,
    timeframe: str,
    backend: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    with _access():
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
    with _access():
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
    with _access():
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
    path = os.path.join(d, f"{_safe_id(name)}.parquet").replace("\\", "/").replace("'", "''")
    with _access(), _connect().cursor() as con:
        con.register("df_out", df)
        try:
            con.execute(f"COPY df_out TO '{path}' (FORMAT PARQUET)").fetchall()
        finally:
            con.unregister("df_out")
    from backend.sessions import check_storage
    try:
        check_storage()
    except Exception:
        os.remove(path.replace("''", "'"))
        raise


def load_frame(analysis_id: str, name: str) -> Optional[pd.DataFrame]:
    path = os.path.join(analysis_dir(analysis_id), f"{_safe_id(name)}.parquet").replace("\\", "/")
    if not os.path.exists(path):
        return None
    # A relation owns its Arrow result. Use a separate cursor so metadata
    # queries that fetched one row on the shared DB-API connection cannot
    # leave an unfinished result in the way of this read.
    with _access(), _connect().cursor() as con:
        # Arrow avoids DuckDB's deprecated pandas inplace conversion path.
        return con.sql("SELECT * FROM read_parquet(?)", params=[path]).to_arrow_table().to_pandas()


def load_frame_page(analysis_id: str, name: str, offset: int, limit: int,
                    *, case_id: str | None = None, zones: list[str] | None = None) -> Optional[tuple[pd.DataFrame, int]]:
    """Read a bounded page in persisted row order without materializing the full frame."""
    path = os.path.join(analysis_dir(analysis_id), f"{_safe_id(name)}.parquet")
    if not os.path.exists(path):
        return None
    # A relation owns its Arrow result. Use a separate cursor so metadata
    # queries that fetched one row on the shared DB-API connection cannot
    # leave an unfinished result in the way of this read.
    with _access(), _connect().cursor() as con:
        filters, arguments = [], [path]
        if case_id is not None:
            filters.append("CAST(case_id AS VARCHAR) = ?")
            arguments.append(case_id)
        if zones:
            filters.append("zone IN (" + ",".join("?" for _ in zones) + ")")
            arguments.extend(zones)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        total = con.execute("SELECT count(*) FROM read_parquet(?)" + where, arguments).fetchall()[0][0]
        if filters:
            page = con.sql(
                "SELECT * EXCLUDE (file_row_number) FROM read_parquet(?, file_row_number=true)" + where +
                " ORDER BY file_row_number LIMIT ? OFFSET ?", params=[*arguments, limit, offset],
            ).to_arrow_table().to_pandas()
        else:
            page = con.sql(
                "SELECT * EXCLUDE (file_row_number) FROM read_parquet(?, file_row_number=true) "
                "WHERE file_row_number >= ? AND file_row_number < ? ORDER BY file_row_number",
                params=[path, offset, offset + limit],
            ).to_arrow_table().to_pandas()
        return page, total


def has_artifacts(analysis_id: str) -> bool:
    d = analysis_dir(analysis_id)
    return os.path.exists(os.path.join(d, "zone_features.parquet"))
