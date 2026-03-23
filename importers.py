"""
importers.py
============
Veri import katmanı. Her format için ayrı importer sınıfı (SOLID - OCP).

Desteklenen formatlar:
  1. DEWESoft Order Tracking CSV  <- birincil format (mevcut veriler)
  2. DEWESoft FFT Waterfall CSV
  3. NumPy NPZ (hızlı arşiv)
  4. Genel TXT/DAT

DEWESoft Order Tracking CSV formatı (görselden):
  Satır 1 : "OT 1/GovX_orto/Order"   (kanal adı)
  Satır 2 : "waterfall (g (peak))"   (birim)
  Satır 3 : "Speed (rpm)/Orders (-)" | 0 | 0.125 | 0.25 | ...
  Satır 4+: rpm_degeri | amp_0 | amp_0.125 | ...

Dosya isimlendirme standardı:
  <MOTOR_ID>__<YYYYMMDD>__<LOKASYON_KODU>__<EKSEN>__<RUN_ID>.csv
  Örnek: ENG-042__20260318__DISLI_GOV__X__RUN-001.csv
"""

import abc
import csv
import io
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from models import DataType, EngineRun

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  DOSYA ADI PARSER
# ---------------------------------------------------------------------------

_FILENAME_PATTERN = re.compile(
    r"^(?P<engine_id>[^_][^_]*)__"
    r"(?P<date>\d{8}|baseline|ref)__"
    r"(?P<location>[A-Z0-9_]+)__"
    r"(?P<axis>[XYZ])__"
    r"(?P<run_id>.+)$",
    re.IGNORECASE,
)


def parse_filename(path: Path) -> Optional[Dict[str, str]]:
    m = _FILENAME_PATTERN.match(path.stem)
    if not m:
        return None
    return {
        "engine_id":   m.group("engine_id").upper(),
        "date":        m.group("date"),
        "location":    m.group("location").upper(),
        "axis":        m.group("axis").upper(),
        "run_id":      m.group("run_id"),
        "channel_key": f"{m.group('location').upper()}_{m.group('axis').upper()}",
    }


# ---------------------------------------------------------------------------
#  ABSTRACT BASE
# ---------------------------------------------------------------------------

class BaseImporter(abc.ABC):

    @abc.abstractmethod
    def can_handle(self, path: Path) -> bool:
        pass

    @abc.abstractmethod
    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:
        pass


# ---------------------------------------------------------------------------
#  DEWESOFT ORDER TRACKING CSV
# ---------------------------------------------------------------------------

class DewesoftOrderTrackingImporter(BaseImporter):
    """
    Birincil format. Satir 3'te "Speed/RPM" VE "Order" kelimesi olmalı.
    """

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".csv":
            return False
        try:
            with path.open(encoding="utf-8-sig", errors="replace") as f:
                for _ in range(2):
                    f.readline()
                row3 = f.readline().lower()
            return (
                any(k in row3 for k in ("speed", "rpm", "devir")) and
                "order" in row3 and
                "freq" not in row3
            )
        except Exception:
            return False

    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:

        logger.info("DEWESoft OT yukleniyor: %s", path.name)
        rows = list(csv.reader(
            io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))
        ))

        if len(rows) < 4:
            raise ValueError(f"Yetersiz satir ({len(rows)}): {path.name}")

        channel_header = rows[0][0].strip() if rows[0] else ""
        unit_str       = rows[1][0].strip() if len(rows) > 1 else ""

        # Satir 3: order degerleri
        orders: List[float] = []
        for cell in rows[2][1:]:
            c = cell.strip()
            if not c:
                continue
            try:
                orders.append(float(c))
            except ValueError:
                logger.warning("Order baslik parse hatasi: '%s'", c)

        if not orders:
            raise ValueError(f"Order sutunlari bulunamadi: {path.name}")

        orders_arr = np.array(orders, dtype=np.float64)
        n_orders   = len(orders_arr)

        rpm_list: List[float] = []
        amp_rows: List[List[float]] = []

        for row in rows[3:]:
            if not row or not row[0].strip():
                continue
            try:
                rpm = float(row[0].strip())
            except ValueError:
                continue

            amps = []
            for cell in row[1: n_orders + 1]:
                try:
                    amps.append(float(cell.strip()) if cell.strip() else 0.0)
                except ValueError:
                    amps.append(0.0)
            while len(amps) < n_orders:
                amps.append(0.0)
            rpm_list.append(rpm)
            amp_rows.append(amps[:n_orders])

        if not rpm_list:
            raise ValueError(f"Veri satiri yok: {path.name}")

        rpm_values       = np.array(rpm_list, dtype=np.float64)
        order_amplitudes = np.array(amp_rows,  dtype=np.float64)

        mean_shaft_hz = float(rpm_values.mean()) / 60.0
        frequencies   = orders_arr * mean_shaft_hz

        meta = dict(metadata or {})
        meta.update({"channel_header": channel_header, "unit": unit_str,
                     "source_format": "dewesoft_order_tracking", "axis": axis})

        logger.info("  -> %d RPM x %d order | RPM: %.0f-%.0f",
                    len(rpm_list), n_orders, rpm_values.min(), rpm_values.max())

        return EngineRun(
            engine_id=engine_id, run_id=run_id,
            sensor_location=sensor_location, axis=axis,
            data_type=DataType.ORDER_TRACKING,
            rpm_values=rpm_values, frequencies=frequencies,
            amplitudes=order_amplitudes,
            orders=orders_arr, order_amplitudes=order_amplitudes,
            is_reference=is_reference, metadata=meta,
        )


# ---------------------------------------------------------------------------
#  DEWESOFT FFT WATERFALL CSV
# ---------------------------------------------------------------------------

class DewesoftWaterfallImporter(BaseImporter):

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".csv":
            return False
        try:
            with path.open(encoding="utf-8-sig", errors="replace") as f:
                for _ in range(2):
                    f.readline()
                row3 = f.readline().lower()
            return (
                any(k in row3 for k in ("speed", "rpm", "devir")) and
                any(k in row3 for k in ("freq", "hz", "frequency"))
            )
        except Exception:
            return False

    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:

        logger.info("DEWESoft FFT Waterfall yukleniyor: %s", path.name)
        rows = list(csv.reader(
            io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))
        ))

        if len(rows) < 4:
            raise ValueError(f"Yetersiz satir: {path.name}")

        channel_header = rows[0][0].strip() if rows[0] else ""
        unit_str       = rows[1][0].strip() if len(rows) > 1 else ""

        freq_values: List[float] = []
        for cell in rows[2][1:]:
            c = cell.strip()
            if not c:
                continue
            try:
                freq_values.append(float(c))
            except ValueError:
                pass

        if not freq_values:
            raise ValueError(f"Frekans sutunlari bulunamadi: {path.name}")

        frequencies = np.array(freq_values, dtype=np.float64)
        n_freqs     = len(frequencies)

        rpm_list: List[float] = []
        amp_rows: List[List[float]] = []

        for row in rows[3:]:
            if not row or not row[0].strip():
                continue
            try:
                rpm = float(row[0].strip())
            except ValueError:
                continue
            amps = []
            for cell in row[1: n_freqs + 1]:
                try:
                    amps.append(float(cell.strip()) if cell.strip() else 0.0)
                except ValueError:
                    amps.append(0.0)
            while len(amps) < n_freqs:
                amps.append(0.0)
            rpm_list.append(rpm)
            amp_rows.append(amps[:n_freqs])

        if not rpm_list:
            raise ValueError(f"Veri satiri yok: {path.name}")

        rpm_values = np.array(rpm_list, dtype=np.float64)
        amplitudes = np.array(amp_rows,  dtype=np.float64)

        meta = dict(metadata or {})
        meta.update({"channel_header": channel_header, "unit": unit_str,
                     "source_format": "dewesoft_fft_waterfall", "axis": axis})

        logger.info("  -> %d RPM x %d frekans | RPM: %.0f-%.0f",
                    len(rpm_list), n_freqs, rpm_values.min(), rpm_values.max())

        return EngineRun(
            engine_id=engine_id, run_id=run_id,
            sensor_location=sensor_location, axis=axis,
            data_type=DataType.FFT_WATERFALL,
            rpm_values=rpm_values, frequencies=frequencies,
            amplitudes=amplitudes,
            is_reference=is_reference, metadata=meta,
        )


# ---------------------------------------------------------------------------
#  NPZ IMPORTER
# ---------------------------------------------------------------------------

class NPZImporter(BaseImporter):

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".npz"

    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:

        logger.info("NPZ yukleniyor: %s", path.name)
        data = np.load(path, allow_pickle=False)

        missing = {"rpm", "frequencies", "amplitudes"} - set(data.files)
        if missing:
            raise ValueError(f"NPZ eksik: {missing}")

        has_orders = "orders" in data.files and "order_amplitudes" in data.files
        saved_axis = str(data["axis"]) if "axis" in data.files else axis

        return EngineRun(
            engine_id=engine_id, run_id=run_id,
            sensor_location=sensor_location, axis=saved_axis,
            data_type=DataType.ORDER_TRACKING if has_orders else DataType.FFT_WATERFALL,
            rpm_values=data["rpm"].astype(np.float64),
            frequencies=data["frequencies"].astype(np.float64),
            amplitudes=data["amplitudes"].astype(np.float64),
            time_axis=data["time"].astype(np.float64) if "time" in data.files else None,
            orders=data["orders"].astype(np.float64) if has_orders else None,
            order_amplitudes=data["order_amplitudes"].astype(np.float64) if has_orders else None,
            is_reference=is_reference, metadata=dict(metadata or {}),
        )


# ---------------------------------------------------------------------------
#  TXT / DAT IMPORTER
# ---------------------------------------------------------------------------

class TXTImporter(BaseImporter):

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".dat"}

    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:

        logger.info("TXT/DAT yukleniyor: %s", path.name)
        lines = [
            l.strip() for l in
            path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            if l.strip() and not l.strip().startswith(("#", "%", ";"))
        ]
        if not lines:
            raise ValueError(f"Veri yok: {path.name}")

        matrix = []
        for line in lines:
            try:
                matrix.append([float(v) for v in line.split()])
            except ValueError:
                continue

        arr = np.array(matrix)
        if arr.ndim != 2 or arr.shape[1] < 2:
            raise ValueError(f"Beklenmeyen sekil: {arr.shape}")

        frequencies    = arr[:, 0]
        amplitude_data = arr[:, 1:]

        if amplitude_data.shape[1] == 1:
            amplitudes = amplitude_data.T
            rpm_values = np.array([2000.0])
            data_type  = DataType.SINGLE_FFT
        else:
            amplitudes = amplitude_data.T
            rpm_values = np.linspace(1800, 2700, amplitudes.shape[0])
            data_type  = DataType.FFT_WATERFALL
            logger.warning("TXT: RPM bilgisi yok, 1800-2700 varsayildi: %s", path.name)

        return EngineRun(
            engine_id=engine_id, run_id=run_id,
            sensor_location=sensor_location, axis=axis,
            data_type=data_type,
            rpm_values=rpm_values, frequencies=frequencies,
            amplitudes=amplitudes,
            is_reference=is_reference, metadata=dict(metadata or {}),
        )


# ---------------------------------------------------------------------------
#  IMPORTER FACTORY
# ---------------------------------------------------------------------------

class ImporterFactory:
    """Dogru importer'i secer. Oncelik: DEWESoft OT > FFT > NPZ > TXT"""

    def __init__(self) -> None:
        self._importers: List[BaseImporter] = [
            DewesoftOrderTrackingImporter(),
            DewesoftWaterfallImporter(),
            NPZImporter(),
            TXTImporter(),
        ]

    def get_importer(self, path: Path) -> BaseImporter:
        for imp in self._importers:
            if imp.can_handle(path):
                return imp
        raise ValueError(
            f"Desteklenmeyen format: {path.suffix} ({path.name})\n"
            f"Desteklenen: .csv (DEWESoft OT/Waterfall), .npz, .txt, .dat"
        )

    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:
        path = Path(path)
        return self.get_importer(path).load(
            path, engine_id, run_id, sensor_location,
            axis, is_reference, metadata,
        )

    def load_from_filename(self, path: Path,
                           is_reference: bool = False,
                           metadata: Optional[Dict] = None,
                           fallback_engine_id: str = "UNKNOWN",
                           fallback_run_id: str = "RUN-001") -> EngineRun:
        """
        Dosya adindan motor_id, lokasyon, eksen, run_id otomatik parse eder.
        Format: ENG-042__20260318__DISLI_GOV__X__RUN-001.csv
        """
        path   = Path(path)
        parsed = parse_filename(path)

        if parsed:
            eid  = parsed["engine_id"]
            rid  = parsed["run_id"]
            loc  = parsed["location"]
            axis = parsed["axis"]
            meta = dict(metadata or {})
            meta["date"] = parsed["date"]
            logger.info("Parse: motor=%s  lokasyon=%s  eksen=%s  run=%s",
                        eid, loc, axis, rid)
        else:
            eid  = fallback_engine_id
            rid  = fallback_run_id
            loc  = path.stem
            axis = "X"
            meta = dict(metadata or {})
            logger.warning(
                "Standart olmayan dosya adi: '%s'\n"
                "  Beklenen: ENG-042__20260318__DISLI_GOV__X__RUN-001.csv\n"
                "  Fallback: motor=%s  lokasyon=%s", path.name, eid, loc,
            )

        return self.load(path, eid, rid, loc, axis, is_reference, meta)


# ---------------------------------------------------------------------------
#  FLEET SCANNER
# ---------------------------------------------------------------------------

class FleetScanner:
    """
    Klasoru tarar, tum kanallari gruplar.
    Donus: {motor_id: {lokasyon: {eksen: [EngineRun, ...]}}}
    Listeler tarih sirali (dosya adinda YYYYMMDD varsa).
    """

    SUPPORTED_EXT = {".csv", ".npz", ".txt", ".dat"}

    def __init__(self, data_dir) -> None:
        self._dir     = Path(data_dir)
        self._factory = ImporterFactory()

    def scan(self, recursive: bool = False,
             skip_errors: bool = True) -> Dict:

        if not self._dir.exists():
            raise FileNotFoundError(f"Klasor bulunamadi: {self._dir}")

        pattern   = "**/*" if recursive else "*"
        all_files = sorted(
            f for f in self._dir.glob(pattern)
            if f.is_file() and f.suffix.lower() in self.SUPPORTED_EXT
        )
        logger.info("%d dosya bulundu: %s", len(all_files), self._dir)

        fleet: Dict = {}
        for f in all_files:
            try:
                run  = self._factory.load_from_filename(f)
                eid  = run.engine_id
                loc  = run.sensor_location
                axis = run.axis
                fleet.setdefault(eid, {}).setdefault(loc, {}).setdefault(axis, [])
                fleet[eid][loc][axis].append(run)
            except Exception as exc:
                if skip_errors:
                    logger.warning("Atlandi [%s]: %s", f.name, exc)
                else:
                    raise

        # Tarih sirasi
        for eid in fleet:
            for loc in fleet[eid]:
                for axis in fleet[eid][loc]:
                    fleet[eid][loc][axis].sort(
                        key=lambda r: r.metadata.get("date", "00000000")
                    )

        n_channels = sum(
            len(ax) for locs in fleet.values() for ax in locs.values()
        )
        logger.info("Tarama tamam: %d motor, %d kanal grubu",
                    len(fleet), n_channels)
        return fleet

    def list_engines(self) -> List[str]:
        ids = set()
        for f in self._dir.iterdir():
            if f.suffix.lower() in self.SUPPORTED_EXT:
                p = parse_filename(f)
                if p:
                    ids.add(p["engine_id"])
        return sorted(ids)
