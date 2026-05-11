"""
ui_worker.py — Arka plan analiz thread'leri.
Analiz islemi UI'yi bloke etmemek icin QThread uzerinde calisir.
"""

import logging
import traceback
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

# Backend importlari — models en once yuklenmeli
from models import DataType, EngineRun
from engine_config import ORDER_DEFINITIONS
from importers import ImporterFactory
from analysis import build_default_analyzer, OrderExtractor
from db_layer import DataStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  DEMO
# ---------------------------------------------------------------------------

class DemoWorker(QThread):
    """Sentetik veri uretip analiz eden demo thread'i."""

    progress    = Signal(str)
    engine_done = Signal(str, float)
    finished    = Signal(object, object)
    error       = Signal(str)

    def run(self):
        try:
            import numpy as np
            from models import DataType, EngineRun

            self.progress.emit("Sentetik referans verisi olusturuluyor...")

            rpm_values  = np.linspace(1800, 2700, 60)
            frequencies = np.linspace(1, 3000, 800)

            BASE_AMPS = {
                0.5: 0.02, 0.59: 0.04, 1.0: 0.05, 1.77: 0.018,
                2.0: 0.08, 3.0: 0.006, 4.0: 0.03, 4.13: 0.008,
                5.9: 0.007, 6.0: 0.012, 8.0: 0.010,
                28.0: 0.004, 28.41: 0.003,
                29.0: 0.015,
                29.59: 0.003, 30.0: 0.004,
            }

            def build_spectrum(rpm_arr, fault_orders=None):
                n_rpm  = len(rpm_arr)
                n_freq = len(frequencies)
                amps   = np.full((n_rpm, n_freq), 0.00008)
                for o, base_amp in BASE_AMPS.items():
                    for i, rpm in enumerate(rpm_arr):
                        target = o * rpm / 60.0
                        idx    = np.argmin(np.abs(frequencies - target))
                        amps[i, max(0, idx-1):idx+2] += base_amp * (
                            1.0 + np.random.uniform(-0.03, 0.03)
                        )
                if fault_orders:
                    for fo, mult in fault_orders.items():
                        for i, rpm in enumerate(rpm_arr):
                            target = fo * rpm / 60.0
                            idx    = np.argmin(np.abs(frequencies - target))
                            amps[i, max(0, idx-1):idx+2] *= mult
                return amps

            ref_amps = build_spectrum(rpm_values)
            ref_run  = EngineRun(
                engine_id="REF-001", run_id="BASELINE",
                sensor_location="BLOK_3YAK", axis="Y",
                data_type=DataType.FFT_WATERFALL,
                rpm_values=rpm_values, frequencies=frequencies,
                amplitudes=ref_amps, is_reference=True,
            )

            engines = {
                "ENG-042 (Disli Kutusu Asinmasi)":   {29.0: 3.2, 58.0: 2.1, 28.0: 1.8, 30.0: 1.8},
                "ENG-043 (Pervane Dengesizligi)":    {0.59: 2.8, 1.77: 2.0},
                "ENG-044 (Yanma Anomalisi)":         {0.5: 2.8, 2.0: 2.2},
                "ENG-045 (Saglikli)":                {},
            }

            analyzer  = build_default_analyzer()
            extractor = OrderExtractor()
            orders    = list(ORDER_DEFINITIONS.keys())
            ref_order_data = extractor.extract(ref_run, orders)
            reports: dict = {}

            for i, (eid, faults) in enumerate(engines.items()):
                self.progress.emit(f"[{i+1}/{len(engines)}]  {eid} simule ediliyor...")
                amps = build_spectrum(rpm_values, fault_orders=faults)
                run  = EngineRun(
                    engine_id=eid, run_id="DEMO",
                    sensor_location="BLOK_3YAK", axis="Y",
                    data_type=DataType.FFT_WATERFALL,
                    rpm_values=rpm_values, frequencies=frequencies,
                    amplitudes=amps,
                )
                report = analyzer.analyze(run, ref_run)
                # PageResults bundle for waterfall + order tabs
                report.bundle = {
                    "meas_run": run,
                    "ref_run":  ref_run,
                    "order_data":     extractor.extract(run, orders),
                    "ref_order_data": ref_order_data,
                }
                reports[eid] = report
                self.engine_done.emit(eid, report.overall_health_score)

            self.progress.emit("Demo tamamlandi.")
            self.finished.emit(reports, ref_run)

        except Exception as exc:
            logger.error("DemoWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
#  TEK MOTOR ANALİZİ — DB tabanlı
# ---------------------------------------------------------------------------

class DbAnalysisWorker(QThread):
    """
    DuckDB'den iki run id alir (referans + olcum), analiz pipeline'ini
    calistirir, PageResults'in bekledigi tum verileri yayar.

    Sinyaller:
      progress(str)
      finished(report, order_data, ref_order_data, run, ref_run)
      error(str)
    """

    progress = Signal(str)
    finished = Signal(object, object, object, object, object)
    error    = Signal(str)

    def __init__(
        self,
        ref_run_id: int,
        meas_run_id: int,
        db_path: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._ref_id  = int(ref_run_id)
        self._meas_id = int(meas_run_id)
        self._db_path = db_path

    def run(self):
        try:
            self.progress.emit(f"DB'den runlar yukleniyor (ref={self._ref_id}, meas={self._meas_id})...")
            with DataStore(db_path=self._db_path) as store:
                ref_run  = store.get_run(self._ref_id)
                meas_run = store.get_run(self._meas_id)

            # Calistirilan run referans flag'i kullanmamakla birlikte tutarlilik icin set ediyoruz
            ref_run.is_reference = True

            self.progress.emit("Analiz calistiriliyor...")
            analyzer = build_default_analyzer()
            report   = analyzer.analyze(meas_run, ref_run)

            self.progress.emit("Order amplitudleri hesaplaniyor...")
            extractor      = OrderExtractor()
            orders         = list(ORDER_DEFINITIONS.keys())
            order_data     = extractor.extract(meas_run, orders)
            ref_order_data = extractor.extract(ref_run,  orders)

            self.progress.emit("Tamamlandi.")
            self.finished.emit(report, order_data, ref_order_data, meas_run, ref_run)

        except Exception as exc:
            logger.error("DbAnalysisWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
#  FILO ANALİZİ — DB tabanlı
# ---------------------------------------------------------------------------

class DbFleetAnalysisWorker(QThread):
    """
    Bir liste DB run id'sini (olcum runlari) alir, her biri icin kanal-bazli
    referans bulup analiz calistirir.

    Referans secim stratejisi:
      1. Once aynı motor + kanal + is_reference=TRUE.
      2. Yoksa herhangi bir motor + aynı kanal + is_reference=TRUE.
      3. O da yoksa run skip edilir ve "no reference" mesaji loglanir.

    Sinyaller:
      progress(str)
      engine_done(engine_id, score)
      finished(reports: dict[str, DiagnosticReport], ref_run: Optional[EngineRun])
      error(str)
    """

    progress     = Signal(str)
    engine_done  = Signal(str, float)
    finished     = Signal(object, object)
    error        = Signal(str)

    def __init__(
        self,
        meas_run_ids: List[int],
        db_path: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._meas_ids = [int(x) for x in meas_run_ids]
        self._db_path  = db_path

    def _resolve_reference(self, store: "DataStore", meas: EngineRun) -> Optional[int]:
        # Tier 1: aynı motorda referans
        same = store.list_runs(
            engine_id=meas.engine_id,
            sensor_location=meas.sensor_location,
            axis=meas.axis,
            is_reference=True,
        )
        if same:
            return same[0].id
        # Tier 2: herhangi bir motorda aynı kanalda referans
        glob = store.list_runs(
            sensor_location=meas.sensor_location,
            axis=meas.axis,
            is_reference=True,
        )
        if glob:
            return glob[0].id
        return None

    def run(self):
        try:
            analyzer = build_default_analyzer()
            extractor = OrderExtractor()
            orders    = list(ORDER_DEFINITIONS.keys())

            reports: Dict[str, Any] = {}
            ref_run: Optional[EngineRun] = None

            with DataStore(db_path=self._db_path) as store:
                total = len(self._meas_ids)
                for i, meas_id in enumerate(self._meas_ids, start=1):
                    try:
                        meas_run = store.get_run(meas_id)
                    except Exception as exc:
                        self.progress.emit(f"[{i}/{total}]  id={meas_id} yuklenemedi: {exc}")
                        continue

                    self.progress.emit(
                        f"[{i}/{total}]  {meas_run.engine_id} "
                        f"({meas_run.sensor_location}/{meas_run.axis}) analiz ediliyor..."
                    )

                    ref_id = self._resolve_reference(store, meas_run)
                    if ref_id is None:
                        self.progress.emit(
                            f"  Atlandi [{meas_run.engine_id}]: "
                            f"{meas_run.sensor_location}/{meas_run.axis} icin referans bulunamadi."
                        )
                        continue

                    try:
                        cur_ref = store.get_run(ref_id)
                        cur_ref.is_reference = True
                    except Exception as exc:
                        self.progress.emit(f"  Atlandi: referans yuklenemedi ({exc})")
                        continue

                    try:
                        report = analyzer.analyze(meas_run, cur_ref)
                        # Attach raw arrays so PageResults can draw the waterfall
                        # + order-comparison tabs when this engine is selected.
                        report.bundle = {
                            "meas_run": meas_run,
                            "ref_run":  cur_ref,
                            "order_data":     extractor.extract(meas_run, orders),
                            "ref_order_data": extractor.extract(cur_ref,  orders),
                        }
                        reports[meas_run.engine_id] = report
                        ref_run = cur_ref  # PageResults için en son kullandığımız ref
                        self.engine_done.emit(meas_run.engine_id, report.overall_health_score)
                    except Exception as exc:
                        logger.warning("Analiz hatasi (%s): %s", meas_run.engine_id, exc)
                        self.progress.emit(f"  Atlandi [{meas_run.engine_id}]: {exc}")

            self.progress.emit(f"Tamamlandi. {len(reports)}/{len(self._meas_ids)} motor analiz edildi.")
            self.finished.emit(reports, ref_run)

        except Exception as exc:
            logger.error("DbFleetAnalysisWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
#  DATA INGEST  (CSV -> DuckDB)
# ---------------------------------------------------------------------------

class DataIngestWorker(QThread):
    """
    Bir CSV/NPZ/TXT dosyasini ImporterFactory ile yukleyip DataStore'a yazar.

    DuckDB baglantisi thread-safe degildir; DataStore instance worker'in
    kendi run() metodu icinde acilir.

    Sinyaller:
      progress(str)
      finished(new_id: int, engine_id: str, run_id: str)
      error(str)
    """

    progress = Signal(str)
    finished = Signal(int, str, str)
    error    = Signal(str)

    def __init__(
        self,
        file_path: str,
        engine_id: str,
        run_id: str,
        sensor_location: str,
        axis: str,
        is_reference: bool,
        measurement_date: Optional[date] = None,
        db_path: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._file_path  = file_path
        self._engine_id  = engine_id
        self._run_id     = run_id
        self._sensor     = sensor_location
        self._axis       = axis
        self._is_ref     = bool(is_reference)
        self._meas_date  = measurement_date
        self._db_path    = db_path

    def run(self):
        try:
            self.progress.emit(f"Dosya yukleniyor: {Path(self._file_path).name}")
            factory = ImporterFactory()
            run = factory.load(
                Path(self._file_path),
                self._engine_id,
                self._run_id,
                self._sensor,
                self._axis,
                is_reference=self._is_ref,
            )

            self.progress.emit("Veritabanina yaziliyor...")
            with DataStore(db_path=self._db_path) as store:
                new_id = store.insert_run(
                    run,
                    source_file=str(self._file_path),
                    measurement_date=self._meas_date,
                )

            self.progress.emit(
                f"OK — id={new_id} engine={self._engine_id} "
                f"ch={self._sensor}/{self._axis} ({run.n_slices} slice)"
            )
            self.finished.emit(int(new_id), self._engine_id, self._run_id)

        except Exception as exc:
            logger.error("DataIngestWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
