"""
ui_worker.py — Arka plan analiz thread'leri.
Analiz islemi UI'yi bloke etmemek icin QThread uzerinde calisir.
"""

import logging
import traceback
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QThread, Signal

from models import DataType, EngineRun
from engine_config import ORDER_DEFINITIONS
from importers import ImporterFactory
from analysis import build_default_analyzer, OrderExtractor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  KANAL YUKLEME
# ---------------------------------------------------------------------------

class LoadChannelWorker(QThread):
    """
    Tek bir veri dosyasini arkaplanda yukler.
    Sinyaller:
      progress(str)
      finished(EngineRun)
      error(str)
    """

    progress = Signal(str)
    finished = Signal(object)
    error    = Signal(str)

    def __init__(
        self,
        path: str,
        engine_id: str,
        run_id: str,
        sensor_location: str,
        axis: str = "X",
        is_reference: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._path   = path
        self._engine = engine_id
        self._run    = run_id
        self._sensor = sensor_location
        self._axis   = axis
        self._is_ref = is_reference

    def run(self):
        try:
            factory = ImporterFactory()
            self.progress.emit(f"Yukleniyor: {Path(self._path).name}")
            run = factory.load(
                Path(self._path), self._engine, self._run,
                self._sensor, self._axis, is_reference=self._is_ref,
            )
            self.finished.emit(run)
        except Exception as exc:
            logger.error("LoadChannelWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
#  IKI KANAL KARSILASTIRMA ANALIZI
# ---------------------------------------------------------------------------

class CompareChannelsWorker(QThread):
    """
    Onceden yuklenmis iki EngineRun arasinda analiz calistirir.
    Sinyaller:
      progress(str)
      finished(report, order_data, ref_order_data, meas_run, ref_run)
      error(str)
    """

    progress = Signal(str)
    finished = Signal(object, object, object, object, object)
    error    = Signal(str)

    def __init__(self, meas_run: EngineRun, ref_run: EngineRun, parent=None):
        super().__init__(parent)
        self._meas = meas_run
        self._ref  = ref_run

    def run(self):
        try:
            self.progress.emit("Analiz calistiriliyor...")
            analyzer = build_default_analyzer()
            report   = analyzer.analyze(self._meas, self._ref)

            self.progress.emit("Order amplitudleri hesaplaniyor...")
            extractor      = OrderExtractor()
            orders         = list(ORDER_DEFINITIONS.keys())
            order_data     = extractor.extract(self._meas, orders)
            ref_order_data = extractor.extract(self._ref,  orders)

            self.progress.emit("Tamamlandi.")
            self.finished.emit(report, order_data, ref_order_data, self._meas, self._ref)

        except Exception as exc:
            logger.error("CompareChannelsWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
#  TEK KANAL ON HESAPLAMA
# ---------------------------------------------------------------------------

class SingleChannelWorker(QThread):
    """
    Tek bir kanal icin order amplitudlerini hesaplar (referans gerektirmez).
    Sinyaller:
      progress(str)
      finished(order_data, run)
      error(str)
    """

    progress = Signal(str)
    finished = Signal(object, object)
    error    = Signal(str)

    def __init__(self, run: EngineRun, parent=None):
        super().__init__(parent)
        self._run = run

    def run(self):
        try:
            self.progress.emit("Order amplitudleri hesaplaniyor...")
            extractor  = OrderExtractor()
            orders     = list(ORDER_DEFINITIONS.keys())
            order_data = extractor.extract(self._run, orders)
            self.finished.emit(order_data, self._run)
        except Exception as exc:
            logger.error("SingleChannelWorker hatasi: %s", exc)
            self.error.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
