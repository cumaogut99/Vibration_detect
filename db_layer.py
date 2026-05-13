"""
db_layer.py — DuckDB tabanlı kalıcı veri katmanı.

Tüm EngineRun nesneleri (CSV importer'ların ürettiği) tek bir DuckDB
dosyasında saklanır. Numpy array'ler ``np.save``/``np.load`` ile BLOB
olarak serialize edilir; skalar metadata sütunları normal kolonlardır.

Varsayılan DB konumu: ``~/.vibration_analyzer/vibration_data.duckdb``

Tipik kullanım::

    store = DataStore()
    new_id = store.insert_run(run, source_file="ENG-042__...csv")
    rows   = store.list_runs(engine_id="ENG-042", sensor_location="DISLI_GOV", axis="X")
    run2   = store.get_run(new_id)
    store.set_reference(new_id, True)

Bu modül Qt'ye bağımlı değildir; CLI'dan veya worker thread'lerden
güvenle çağrılabilir.
"""

from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import duckdb
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "duckdb yüklü değil. `pip install duckdb` ile kurun."
    ) from exc

from models import DataType, EngineRun

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Konum / sabitler
# ---------------------------------------------------------------------------

DEFAULT_DB_DIR  = Path.home() / ".vibration_analyzer"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "vibration_data.duckdb"

_ARRAY_COLUMNS = (
    "rpm_values",
    "frequencies",
    "amplitudes",
    "time_axis",
    "orders",
    "order_amplitudes",
)


# ---------------------------------------------------------------------------
#  Yardımcılar
# ---------------------------------------------------------------------------

def _array_to_blob(arr: Optional[np.ndarray]) -> Optional[bytes]:
    if arr is None:
        return None
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(arr), allow_pickle=False)
    return buf.getvalue()


def _blob_to_array(blob: Optional[bytes]) -> Optional[np.ndarray]:
    if blob is None or len(blob) == 0:
        return None
    return np.load(io.BytesIO(blob), allow_pickle=False)


def _coerce_date(value: Any) -> Optional[date]:
    """Tarih, string veya datetime'ı ``date``'e çevirir; başarısızsa None."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
#  Sorgu satır objesi
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunSummary:
    """``list_runs`` satırı — EngineRun değil, sadece metadata."""
    id: int
    engine_id: str
    run_id: str
    sensor_location: str
    axis: str
    data_type: str
    measurement_date: Optional[date]
    is_reference: bool
    n_slices: int
    n_freqs: int
    rpm_min: float
    rpm_max: float
    source_file: Optional[str]
    created_at: datetime

    @property
    def channel_key(self) -> str:
        return f"{self.sensor_location}_{self.axis}"


# ---------------------------------------------------------------------------
#  DataStore
# ---------------------------------------------------------------------------

class DataStore:
    """
    DuckDB tabanlı EngineRun deposu.

    Thread-safety: DuckDB bağlantısı thread-safe **değildir**. Worker
    thread'lerden çağırılacaksa her thread kendi ``DataStore`` instance'ını
    oluşturmalıdır (dosya kilidi paylaşımlı okumalara izin verir).
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._ensure_schema()
        logger.info("DataStore açıldı: %s", self._db_path)

    # ── Bağlantı yaşam döngüsü ────────────────────────────────────────────

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DataStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ── Şema ──────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE SEQUENCE IF NOT EXISTS seq_engine_runs_id START 1
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS engine_runs (
                id                BIGINT       PRIMARY KEY
                                                DEFAULT nextval('seq_engine_runs_id'),
                engine_id         VARCHAR      NOT NULL,
                run_id            VARCHAR      NOT NULL,
                sensor_location   VARCHAR      NOT NULL,
                axis              VARCHAR      NOT NULL,
                data_type         VARCHAR      NOT NULL,
                measurement_date  DATE,
                is_reference      BOOLEAN      NOT NULL DEFAULT FALSE,
                n_slices          INTEGER      NOT NULL,
                n_freqs           INTEGER      NOT NULL,
                rpm_min           DOUBLE       NOT NULL,
                rpm_max           DOUBLE       NOT NULL,
                source_file       VARCHAR,
                metadata_json     VARCHAR,
                created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                rpm_values        BLOB         NOT NULL,
                frequencies       BLOB         NOT NULL,
                amplitudes        BLOB         NOT NULL,
                time_axis         BLOB,
                orders            BLOB,
                order_amplitudes  BLOB
            )
            """
        )
        # Sık kullanılan filtreler için indeks
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_engine_runs_channel
            ON engine_runs (engine_id, sensor_location, axis)
            """
        )

    # ── Insert ────────────────────────────────────────────────────────────

    def insert_run(
        self,
        run: EngineRun,
        source_file: Optional[str] = None,
        measurement_date: Any = None,
    ) -> int:
        """
        ``EngineRun``'ı kalıcılaştırır. Dönüş: yeni satırın ``id``'si.

        Args:
            run: Persisted edilecek run.
            source_file: Kaynak CSV/NPZ dosya yolu (opsiyonel, audit için).
            measurement_date: ``date`` / ``datetime`` / ``"YYYY-MM-DD"`` /
                ``"YYYYMMDD"`` formatlarından biri. ``None`` ise
                ``run.metadata['date']`` denenir.
        """
        meas_date = _coerce_date(measurement_date)
        if meas_date is None:
            meas_date = _coerce_date(run.metadata.get("date"))

        metadata_json = json.dumps(
            {k: v for k, v in run.metadata.items() if _is_json_safe(v)},
            ensure_ascii=False,
        )

        rpm_min, rpm_max = run.rpm_range

        row = (
            run.engine_id,
            run.run_id,
            run.sensor_location,
            run.axis,
            run.data_type.value,
            meas_date,
            bool(run.is_reference),
            int(run.n_slices),
            int(run.n_freqs),
            float(rpm_min),
            float(rpm_max),
            source_file,
            metadata_json,
            _array_to_blob(run.rpm_values),
            _array_to_blob(run.frequencies),
            _array_to_blob(run.amplitudes),
            _array_to_blob(run.time_axis),
            _array_to_blob(run.orders),
            _array_to_blob(run.order_amplitudes),
        )

        # DuckDB RETURNING desteği vardır
        result = self._conn.execute(
            """
            INSERT INTO engine_runs (
                engine_id, run_id, sensor_location, axis, data_type,
                measurement_date, is_reference, n_slices, n_freqs,
                rpm_min, rpm_max, source_file, metadata_json,
                rpm_values, frequencies, amplitudes,
                time_axis, orders, order_amplitudes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            row,
        ).fetchone()
        new_id = int(result[0])
        logger.info(
            "DB insert: id=%d engine=%s run=%s ch=%s/%s (%d slices)",
            new_id, run.engine_id, run.run_id,
            run.sensor_location, run.axis, run.n_slices,
        )
        return new_id

    # ── Get ───────────────────────────────────────────────────────────────

    def get_run(self, run_db_id: int) -> EngineRun:
        """ID'den tam ``EngineRun``'ı (array'ler dâhil) çekiştir."""
        row = self._conn.execute(
            """
            SELECT engine_id, run_id, sensor_location, axis, data_type,
                   is_reference, metadata_json,
                   rpm_values, frequencies, amplitudes,
                   time_axis, orders, order_amplitudes
            FROM engine_runs WHERE id = ?
            """,
            (int(run_db_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"engine_runs.id={run_db_id} bulunamadı")

        (engine_id, run_id, location, axis, data_type_str,
         is_reference, metadata_json,
         rpm_blob, freq_blob, amp_blob,
         time_blob, orders_blob, order_amp_blob) = row

        metadata = json.loads(metadata_json) if metadata_json else {}

        return EngineRun(
            engine_id=engine_id,
            run_id=run_id,
            sensor_location=location,
            axis=axis,
            data_type=DataType(data_type_str),
            rpm_values=_blob_to_array(rpm_blob),
            frequencies=_blob_to_array(freq_blob),
            amplitudes=_blob_to_array(amp_blob),
            time_axis=_blob_to_array(time_blob),
            orders=_blob_to_array(orders_blob),
            order_amplitudes=_blob_to_array(order_amp_blob),
            metadata=metadata,
            is_reference=bool(is_reference),
        )

    # ── List / arama ──────────────────────────────────────────────────────

    def list_runs(
        self,
        engine_id: Optional[str] = None,
        sensor_location: Optional[str] = None,
        axis: Optional[str] = None,
        is_reference: Optional[bool] = None,
    ) -> List[RunSummary]:
        """Filtrelenmiş metadata satırları (array'siz, hızlı)."""
        clauses = []
        params: List[Any] = []
        if engine_id is not None:
            clauses.append("engine_id = ?")
            params.append(engine_id)
        if sensor_location is not None:
            clauses.append("sensor_location = ?")
            params.append(sensor_location)
        if axis is not None:
            clauses.append("axis = ?")
            params.append(axis)
        if is_reference is not None:
            clauses.append("is_reference = ?")
            params.append(bool(is_reference))

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT id, engine_id, run_id, sensor_location, axis, data_type,
                   measurement_date, is_reference, n_slices, n_freqs,
                   rpm_min, rpm_max, source_file, created_at
            FROM engine_runs
            {where}
            ORDER BY measurement_date DESC NULLS LAST, created_at DESC
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [RunSummary(*r) for r in rows]

    def list_engines(self) -> List[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT engine_id FROM engine_runs ORDER BY engine_id"
        ).fetchall()
        return [r[0] for r in rows]

    def list_channels(self, engine_id: str) -> List[Dict[str, Any]]:
        """
        Bir motor için (sensor_location, axis) kanallarını ve her kanalın
        run sayısını / referans run sayısını döner.
        """
        rows = self._conn.execute(
            """
            SELECT sensor_location, axis,
                   COUNT(*)                                  AS n_runs,
                   SUM(CASE WHEN is_reference THEN 1 ELSE 0 END) AS n_refs
            FROM engine_runs
            WHERE engine_id = ?
            GROUP BY sensor_location, axis
            ORDER BY sensor_location, axis
            """,
            (engine_id,),
        ).fetchall()
        return [
            {
                "sensor_location": r[0],
                "axis": r[1],
                "n_runs": int(r[2]),
                "n_refs": int(r[3]),
            }
            for r in rows
        ]

    def find_reference(
        self,
        engine_id: str,
        sensor_location: str,
        axis: str,
    ) -> Optional[int]:
        """En son referans run'ın id'si — yoksa ``None``."""
        row = self._conn.execute(
            """
            SELECT id FROM engine_runs
            WHERE engine_id = ?
              AND sensor_location = ?
              AND axis = ?
              AND is_reference = TRUE
            ORDER BY measurement_date DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (engine_id, sensor_location, axis),
        ).fetchone()
        return int(row[0]) if row else None

    # ── Update / delete ───────────────────────────────────────────────────

    def set_reference(self, run_db_id: int, is_reference: bool) -> None:
        self._conn.execute(
            "UPDATE engine_runs SET is_reference = ? WHERE id = ?",
            (bool(is_reference), int(run_db_id)),
        )

    def delete_run(self, run_db_id: int) -> None:
        self._conn.execute(
            "DELETE FROM engine_runs WHERE id = ?", (int(run_db_id),)
        )

    def count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) FROM engine_runs").fetchone()[0]
        )


# ---------------------------------------------------------------------------
#  Yardımcı
# ---------------------------------------------------------------------------

def _is_json_safe(value: Any) -> bool:
    """Sadece JSON-serileştirilebilir basit tipleri kabul et."""
    if value is None:
        return True
    if isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_json_safe(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json_safe(v) for k, v in value.items())
    return False


# ---------------------------------------------------------------------------
#  Self-test (round-trip)
# ---------------------------------------------------------------------------

def _self_test() -> None:
    """Geçici bir DB dosyasıyla insert → get round-trip testi."""
    import tempfile

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    tmpdir = Path(tempfile.mkdtemp(prefix="vibdb_test_"))
    db_path = tmpdir / "test.duckdb"

    rpm_values  = np.linspace(1800.0, 2700.0, 60).astype(np.float64)
    frequencies = np.linspace(1.0, 3000.0, 800).astype(np.float64)
    amplitudes  = np.random.RandomState(42).rand(len(rpm_values), len(frequencies)).astype(np.float64)
    orders      = np.array([0.5, 1.0, 2.0, 4.0, 29.0], dtype=np.float64)
    order_amps  = np.random.RandomState(7).rand(len(rpm_values), len(orders)).astype(np.float64)

    original = EngineRun(
        engine_id="ENG-TEST",
        run_id="RUN-TEST-01",
        sensor_location="DISLI_GOV",
        axis="X",
        data_type=DataType.ORDER_TRACKING,
        rpm_values=rpm_values,
        frequencies=frequencies,
        amplitudes=amplitudes,
        orders=orders,
        order_amplitudes=order_amps,
        is_reference=False,
        metadata={"date": "20260318", "channel_header": "OT 1/GovX_orto/Order",
                  "unit": "g (peak)", "source_format": "dewesoft_order_tracking",
                  "axis": "X"},
    )

    store = DataStore(db_path=db_path)
    new_id = store.insert_run(original, source_file="ENG-TEST__20260318__DISLI_GOV__X__RUN-TEST-01.csv")
    assert isinstance(new_id, int) and new_id > 0, f"insert döndü: {new_id!r}"

    # Listeler
    engines = store.list_engines()
    assert engines == ["ENG-TEST"], engines

    summaries = store.list_runs(engine_id="ENG-TEST")
    assert len(summaries) == 1, summaries
    s = summaries[0]
    assert s.engine_id == "ENG-TEST"
    assert s.sensor_location == "DISLI_GOV" and s.axis == "X"
    assert s.measurement_date == date(2026, 3, 18)
    assert s.is_reference is False
    assert s.n_slices == 60 and s.n_freqs == 800
    assert abs(s.rpm_min - 1800.0) < 1e-6
    assert abs(s.rpm_max - 2700.0) < 1e-6

    # Referans işaretle
    store.set_reference(new_id, True)
    s2 = store.list_runs(engine_id="ENG-TEST")[0]
    assert s2.is_reference is True
    ref_id = store.find_reference("ENG-TEST", "DISLI_GOV", "X")
    assert ref_id == new_id

    # Round-trip
    restored = store.get_run(new_id)
    assert restored.engine_id  == original.engine_id
    assert restored.run_id     == original.run_id
    assert restored.sensor_location == original.sensor_location
    assert restored.axis       == original.axis
    assert restored.data_type  == original.data_type
    assert restored.is_reference is True
    np.testing.assert_array_equal(restored.rpm_values, original.rpm_values)
    np.testing.assert_array_equal(restored.frequencies, original.frequencies)
    np.testing.assert_array_equal(restored.amplitudes, original.amplitudes)
    np.testing.assert_array_equal(restored.orders, original.orders)
    np.testing.assert_array_equal(restored.order_amplitudes, original.order_amplitudes)
    assert restored.time_axis is None
    assert restored.metadata["channel_header"] == "OT 1/GovX_orto/Order"

    # Kanallar
    channels = store.list_channels("ENG-TEST")
    assert channels == [{"sensor_location": "DISLI_GOV", "axis": "X",
                         "n_runs": 1, "n_refs": 1}], channels

    # Delete
    store.delete_run(new_id)
    assert store.count() == 0
    store.close()

    # Temizlik
    for f in tmpdir.iterdir():
        f.unlink()
    tmpdir.rmdir()

    print("OK — DataStore round-trip testi geçti.")


if __name__ == "__main__":
    _self_test()
