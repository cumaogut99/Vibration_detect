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
#  TEK MOTOR ANALİZİ
# ---------------------------------------------------------------------------

class AnalysisWorker(QThread):
    """
    Tek motor analizi icin arka plan thread'i.
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
        ref_path: str,
        ref_id: str,
        meas_path: str,
        meas_id: str,
        sensor_location: str,
        axis: str = "X",
        run_id: str = "RUN-001",
        freq_max: float = 3000.0,
        parent=None,
    ):
        super().__init__(parent)
        self._ref_path  = ref_path
        self._ref_id    = ref_id
        self._meas_path = meas_path
        self._meas_id   = meas_id
        self._sensor    = sensor_location
        self._axis      = axis
        self._run_id    = run_id
        self._freq_max  = freq_max

    def run(self):
        try:
            factory = ImporterFactory()

            self.progress.emit("Referans veri yukleniyor...")
            ref_run = factory.load(
                Path(self._ref_path), self._ref_id, "REF",
                self._sensor, self._axis, is_reference=True,
            )

            self.progress.emit("Olcum verisi yukleniyor...")
            meas_run = factory.load(
                Path(self._meas_path), self._meas_id, self._run_id,
                self._sensor, self._axis,
            )

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
            logger.error("AnalysisWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
#  FİLO ANALİZİ
# ---------------------------------------------------------------------------

class FleetAnalysisWorker(QThread):
    """
    Filo analizi icin arka plan thread'i.
    Sinyaller:
      progress(str)
      engine_done(engine_id, score)
      finished(reports, ref_run)
      error(str)
    """

    progress    = Signal(str)
    engine_done = Signal(str, float)
    finished    = Signal(object, object)
    error       = Signal(str)

    def __init__(
        self,
        ref_path: str,
        ref_id: str,
        fleet_dir: str,
        sensor_location: str,
        axis: str = "X",
        parent=None,
    ):
        super().__init__(parent)
        self._ref_path  = ref_path
        self._ref_id    = ref_id
        self._fleet_dir = fleet_dir
        self._sensor    = sensor_location
        self._axis      = axis

    def run(self):
        try:
            factory  = ImporterFactory()
            analyzer = build_default_analyzer()

            self.progress.emit("Referans veri yukleniyor...")
            ref_run = factory.load(
                Path(self._ref_path), self._ref_id, "REF",
                self._sensor, self._axis, is_reference=True,
            )

            fleet_dir = Path(self._fleet_dir)
            files = [
                f for f in fleet_dir.iterdir()
                if f.suffix.lower() in {".csv", ".npz", ".txt", ".dat"}
            ]

            if not files:
                self.error.emit(f"Klasorde desteklenen dosya bulunamadi: {fleet_dir}")
                return

            reports: Dict = {}
            for i, ef in enumerate(files):
                eid = ef.stem
                self.progress.emit(f"[{i+1}/{len(files)}]  {eid} analiz ediliyor...")
                try:
                    run    = factory.load(ef, eid, "RUN-001", self._sensor, self._axis)
                    report = analyzer.analyze(run, ref_run)
                    reports[eid] = report
                    self.engine_done.emit(eid, report.overall_health_score)
                except Exception as exc:
                    logger.warning("Fleet: %s basarisiz: %s", eid, exc)
                    self.progress.emit(f"  Atlandi [{eid}]: {exc}")

            self.progress.emit(f"Tamamlandi. {len(reports)}/{len(files)} motor analiz edildi.")
            self.finished.emit(reports, ref_run)

        except Exception as exc:
            logger.error("FleetAnalysisWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


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

            analyzer = build_default_analyzer()
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
                reports[eid] = report
                self.engine_done.emit(eid, report.overall_health_score)

            self.progress.emit("Demo tamamlandi.")
            self.finished.emit(reports, ref_run)

        except Exception as exc:
            logger.error("DemoWorker hatasi: %s", exc)
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
