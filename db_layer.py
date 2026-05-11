"""
db_layer.py
===========
DuckDB-based persistent storage for vibration runs.

Default location:  ~/.vibration_analyzer/vibration_data.duckdb
Override via env:  VIBRATION_DB_PATH

Numpy arrays (RPM, frequencies, amplitudes, orders) are stored as BLOBs
serialised with np.save — compact and round-trip-safe.
"""

import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import numpy as np

from models import DataType, EngineRun

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".vibration_analyzer" / "vibration_data.duckdb"


# ---------------------------------------------------------------------------
#  HELPERS
# ---------------------------------------------------------------------------

def _serialize(arr: Optional[np.ndarray]) -> Optional[bytes]:
    if arr is None:
        return None
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr), allow_pickle=False)
    return buf.getvalue()


def _deserialize(b: Optional[bytes]) -> Optional[np.ndarray]:
    if not b:
        return None
    return np.load(io.BytesIO(b), allow_pickle=False)


def _resolve_default_path() -> Path:
    env = os.environ.get("VIBRATION_DB_PATH")
    return Path(env) if env else DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
#  LIGHTWEIGHT VIEW
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunRecord:
    """Run row without the bulky array columns — use for tables/filters."""
    id: int
    engine_id: str
    location_code: str
    axis: str
    run_label: str
    captured_at: Optional[datetime]
    is_reference: bool
    data_type: str
    source_filename: str
    n_rpm: int
    n_freq: int
    notes: str
    ingested_at: datetime

    @property
    def channel_key(self) -> str:
        return f"{self.location_code}_{self.axis}"


# ---------------------------------------------------------------------------
#  DATABASE WRAPPER
# ---------------------------------------------------------------------------

class VibrationDB:
    """
    Wraps a single DuckDB file. One connection per instance.

    Worker threads should not share the same VibrationDB instance; create a
    short-lived instance inside the worker thread or marshal calls back to
    the owning thread.
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = Path(db_path) if db_path else _resolve_default_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._path))
        self._ensure_schema()

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ── Schema ────────────────────────────────────────────────────────────
    def _ensure_schema(self) -> None:
        self._conn.execute("CREATE SEQUENCE IF NOT EXISTS runs_id_seq START 1")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id              BIGINT PRIMARY KEY DEFAULT nextval('runs_id_seq'),
                engine_id       VARCHAR NOT NULL,
                location_code   VARCHAR NOT NULL,
                axis            VARCHAR NOT NULL,
                run_label       VARCHAR DEFAULT '',
                captured_at     TIMESTAMP,
                is_reference    BOOLEAN DEFAULT FALSE,
                data_type       VARCHAR NOT NULL,
                unit            VARCHAR DEFAULT '',
                source_filename VARCHAR DEFAULT '',
                notes           VARCHAR DEFAULT '',
                rpm_values       BLOB NOT NULL,
                frequencies      BLOB NOT NULL,
                amplitudes       BLOB NOT NULL,
                orders           BLOB,
                order_amplitudes BLOB,
                time_axis        BLOB,
                metadata_json    VARCHAR DEFAULT '{}',
                ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_channel
            ON runs (engine_id, location_code, axis)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_reference
            ON runs (is_reference)
        """)

    # ── Insert ────────────────────────────────────────────────────────────
    def insert_run(
        self,
        run: EngineRun,
        *,
        run_label: str = "",
        captured_at: Optional[datetime] = None,
        notes: str = "",
        source_filename: str = "",
    ) -> int:
        import json

        unit = str(run.metadata.get("unit", "")) if run.metadata else ""
        meta_json = json.dumps(run.metadata or {}, default=str, ensure_ascii=False)
        captured = captured_at or datetime.now()

        row = self._conn.execute("""
            INSERT INTO runs (
                engine_id, location_code, axis, run_label, captured_at,
                is_reference, data_type, unit, source_filename, notes,
                rpm_values, frequencies, amplitudes,
                orders, order_amplitudes, time_axis, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, [
            run.engine_id, run.sensor_location, run.axis, run_label, captured,
            bool(run.is_reference), run.data_type.value, unit,
            source_filename, notes,
            _serialize(run.rpm_values), _serialize(run.frequencies),
            _serialize(run.amplitudes),
            _serialize(run.orders), _serialize(run.order_amplitudes),
            _serialize(run.time_axis), meta_json,
        ]).fetchone()
        new_id = int(row[0])
        logger.info("DB insert: run id=%d engine=%s ch=%s_%s ref=%s",
                    new_id, run.engine_id, run.sensor_location, run.axis,
                    run.is_reference)
        return new_id

    # ── Query (lightweight) ───────────────────────────────────────────────
    def list_runs(
        self,
        *,
        engine_id: Optional[str] = None,
        location_code: Optional[str] = None,
        axis: Optional[str] = None,
        is_reference: Optional[bool] = None,
    ) -> List[RunRecord]:
        clauses = []
        params: list = []
        if engine_id is not None:
            clauses.append("engine_id = ?")
            params.append(engine_id)
        if location_code is not None:
            clauses.append("location_code = ?")
            params.append(location_code)
        if axis is not None:
            clauses.append("axis = ?")
            params.append(axis)
        if is_reference is not None:
            clauses.append("is_reference = ?")
            params.append(bool(is_reference))

        sql = """
            SELECT id, engine_id, location_code, axis, run_label, captured_at,
                   is_reference, data_type, source_filename, notes, ingested_at,
                   rpm_values, frequencies
            FROM runs
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY engine_id, location_code, axis, captured_at DESC"

        rows = self._conn.execute(sql, params).fetchall()
        out: List[RunRecord] = []
        for r in rows:
            rpm_arr  = _deserialize(r[11])
            freq_arr = _deserialize(r[12])
            out.append(RunRecord(
                id=int(r[0]),
                engine_id=r[1],
                location_code=r[2],
                axis=r[3],
                run_label=r[4] or "",
                captured_at=r[5],
                is_reference=bool(r[6]),
                data_type=r[7],
                source_filename=r[8] or "",
                notes=r[9] or "",
                ingested_at=r[10],
                n_rpm=int(rpm_arr.size) if rpm_arr is not None else 0,
                n_freq=int(freq_arr.size) if freq_arr is not None else 0,
            ))
        return out

    # ── Query (full run with arrays) ──────────────────────────────────────
    def get_run(self, run_id: int) -> EngineRun:
        import json

        row = self._conn.execute("""
            SELECT engine_id, location_code, axis, run_label,
                   is_reference, data_type,
                   rpm_values, frequencies, amplitudes,
                   orders, order_amplitudes, time_axis,
                   metadata_json, unit
            FROM runs WHERE id = ?
        """, [run_id]).fetchone()
        if row is None:
            raise KeyError(f"Run id {run_id} not found")

        try:
            metadata = json.loads(row[12]) if row[12] else {}
        except (TypeError, ValueError):
            metadata = {}
        if row[13]:
            metadata.setdefault("unit", row[13])

        return EngineRun(
            engine_id=row[0],
            run_id=row[3] or f"DB-{run_id}",
            sensor_location=row[1],
            axis=row[2],
            data_type=DataType(row[5]),
            rpm_values=_deserialize(row[6]),
            frequencies=_deserialize(row[7]),
            amplitudes=_deserialize(row[8]),
            orders=_deserialize(row[9]),
            order_amplitudes=_deserialize(row[10]),
            time_axis=_deserialize(row[11]),
            is_reference=bool(row[4]),
            metadata=metadata,
        )

    def delete_run(self, run_id: int) -> None:
        self._conn.execute("DELETE FROM runs WHERE id = ?", [run_id])

    def set_reference(self, run_id: int, is_reference: bool) -> None:
        self._conn.execute(
            "UPDATE runs SET is_reference = ? WHERE id = ?",
            [bool(is_reference), run_id],
        )

    # ── Aggregates ────────────────────────────────────────────────────────
    def list_engines(self) -> List[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT engine_id FROM runs ORDER BY engine_id"
        ).fetchall()
        return [r[0] for r in rows]

    def channel_summary(self) -> List[Dict]:
        """One row per (engine, location, axis): counts and latest capture."""
        rows = self._conn.execute("""
            SELECT engine_id, location_code, axis,
                   COUNT(*) AS n_runs,
                   SUM(CASE WHEN is_reference THEN 1 ELSE 0 END) AS n_refs,
                   MAX(captured_at) AS latest
            FROM runs
            GROUP BY engine_id, location_code, axis
            ORDER BY engine_id, location_code, axis
        """).fetchall()
        return [
            {
                "engine_id":     r[0],
                "location_code": r[1],
                "axis":          r[2],
                "n_runs":        int(r[3]),
                "n_references":  int(r[4]),
                "latest":        r[5],
            }
            for r in rows
        ]

    def find_reference(
        self, engine_id: str, location_code: str, axis: str,
    ) -> Optional[RunRecord]:
        """Most recent reference run for a given channel, or None."""
        refs = self.list_runs(
            engine_id=engine_id, location_code=location_code,
            axis=axis, is_reference=True,
        )
        return refs[0] if refs else None
