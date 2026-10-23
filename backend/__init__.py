"""FastAPI backend for zone-based token-flow analytics.

Wraps the UI-agnostic ``services/`` layer with HTTP routes, a background-job
pattern with progress streaming (SSE) for the expensive alignment step, and
DuckDB/Parquet persistence keyed by input hashes so nothing is ever computed
twice for the same inputs. No analytical logic lives here — see ``services/``,
``process_model/`` and ``analytics/``.
"""
