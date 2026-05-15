"""
importers.py
============
Veri import katmanı. Her format için ayrı importer sınıfı (SOLID - OCP).

Desteklenen formatlar:
  1. DEWESoft Order Tracking CSV  <- birincil format (mevcut veriler)
  2. DEWESoft FFT Waterfall CSV
  3. NumPy NPZ (hızlı arşiv)
  4. Genel TXT/DAT
  5. FFT Max Hold CSV (cok-kanalli, ``load_max_hold_csv``)

DEWESoft Order Tracking CSV formatı (görselden):
  Satır 1 : "OT 1/GovX_orto/Order"   (kanal adı)
  Satır 2 : "waterfall (g (peak))"   (birim)
  Satır 3 : "Speed (rpm)/Orders (-)" | 0 | 0.125 | 0.25 | ...
  Satır 4+: rpm_degeri | amp_0 | amp_0.125 | ...

FFT Max Hold CSV (cok kanalli):
  Satır 1 : "Freq (Hz)" | "27/BlokA_silindir" | "27/BlokY_krank" | ...
  Satır 2+: freq        | amp_ch1            | amp_ch2          | ...
  Her sutun ayri bir kanal -> ayri EngineRun (data_type=FFT_MAX_HOLD).

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
#  DEWESOFT CSV ORTAK BASLIK TESPITI
# ---------------------------------------------------------------------------

_HEADER_SCAN_LIMIT = 6  # ilk 6 satirda ara

def _find_dewesoft_header_row(rows: List[List[str]]) -> Optional[int]:
    """
    DEWESoft CSV'lerinde "Speed (rpm) / ..." sutununu iceren basligi bulur.

    Bazı varyantlarda satir 0'da, bazilarinda satir 2'de (kanal adi + birim
    satirlari ustte) yer alir. Aranan satir: ilk hucresinde "speed" / "rpm" /
    "devir" gecen VE kalan hucrelerde en az 3 sayisal deger bulunan satir.
    """
    for i in range(min(_HEADER_SCAN_LIMIT, len(rows))):
        row = rows[i]
        if not row or not row[0]:
            continue
        first = row[0].strip().lower()
        if not any(k in first for k in ("speed", "rpm", "devir")):
            continue
        numeric_count = 0
        for cell in row[1:]:
            c = (cell or "").strip()
            if not c:
                continue
            try:
                float(c)
                numeric_count += 1
                if numeric_count >= 3:
                    return i
            except ValueError:
                continue
    return None


def _peek_header_first_cell(path: Path) -> str:
    """Dosyanin ilk _HEADER_SCAN_LIMIT satiri icinde Speed/RPM iceren ilk
    hucreyi dondur (kucuk harfle). Bulamazsa bos string."""
    try:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
            head = []
            for _ in range(_HEADER_SCAN_LIMIT):
                line = f.readline()
                if not line:
                    break
                head.append(line)
        if not head:
            return ""
        reader = csv.reader(io.StringIO("".join(head)))
        rows = list(reader)
        idx = _find_dewesoft_header_row(rows)
        if idx is None:
            return ""
        return rows[idx][0].strip().lower()
    except Exception:
        return ""


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
    DEWESoft Order Tracking CSV.

    Esnek format: baslik satiri ilk 6 satirin herhangi birinde olabilir.
    Tanima kriteri: ilk hucrede "speed"/"rpm"/"devir" + "order" gecmesi VE
    "freq" gecmemesi.
    """

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".csv":
            return False
        header = _peek_header_first_cell(path)
        if not header:
            return False
        return "order" in header and "freq" not in header

    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:

        logger.info("DEWESoft OT yukleniyor: %s", path.name)
        rows = list(csv.reader(
            io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))
        ))

        header_idx = _find_dewesoft_header_row(rows)
        if header_idx is None:
            raise ValueError(f"Baslik satiri bulunamadi: {path.name}")
        if len(rows) <= header_idx + 1:
            raise ValueError(f"Veri satiri yok: {path.name}")

        channel_header = rows[0][0].strip() if header_idx >= 1 and rows[0] else ""
        unit_str       = rows[1][0].strip() if header_idx >= 2 and len(rows) > 1 else ""

        # Baslik satiri: order degerleri
        orders: List[float] = []
        for cell in rows[header_idx][1:]:
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

        for row in rows[header_idx + 1:]:
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
    """
    DEWESoft FFT Waterfall CSV.

    Baslik satiri ilk 6 satirin herhangi birinde olabilir; ilk hucrede
    "speed"/"rpm" + "freq"/"hz"/"frequency" gecmesi yeterli. Eger sadece
    "speed/rpm" varsa (order/freq ayrimi belirsizse) bu importer fallback
    olarak devreye girer (factory'de OT'den sonra siralanir).
    """

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".csv":
            return False
        header = _peek_header_first_cell(path)
        if not header:
            return False
        # Belirgin frekans isareti varsa kesin
        if any(k in header for k in ("freq", "frequency", "hz")):
            return True
        # Sadece "speed/rpm" varsa ve "order" yoksa fallback olarak biz al
        return "order" not in header

    def load(self, path: Path, engine_id: str, run_id: str,
             sensor_location: str, axis: str = "X",
             is_reference: bool = False,
             metadata: Optional[Dict] = None) -> EngineRun:

        logger.info("DEWESoft FFT Waterfall yukleniyor: %s", path.name)
        rows = list(csv.reader(
            io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))
        ))

        header_idx = _find_dewesoft_header_row(rows)
        if header_idx is None:
            raise ValueError(f"Baslik satiri bulunamadi: {path.name}")
        if len(rows) <= header_idx + 1:
            raise ValueError(f"Veri satiri yok: {path.name}")

        channel_header = rows[0][0].strip() if header_idx >= 1 and rows[0] else ""
        unit_str       = rows[1][0].strip() if header_idx >= 2 and len(rows) > 1 else ""

        freq_values: List[float] = []
        for cell in rows[header_idx][1:]:
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

        for row in rows[header_idx + 1:]:
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
            f"Desteklenen uzantilar: .csv, .npz, .txt, .dat"
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


# ---------------------------------------------------------------------------
#  FFT MAX HOLD CSV (cok-kanalli, tek dosya = N kanal)
# ---------------------------------------------------------------------------

def _parse_max_hold_channel_name(name: str) -> tuple[str, str]:
    """``"27/BlokY_krank"`` -> ``("BlokY_krank", "Y")``.

    - Bastaki ``"<sayilar>/"`` prefiksi soyulur.
    - ``"/"`` -> ``"_"``.
    - Tek karakter X/Y/Z (kelime sinirinda) eksen olarak alinir; bulunamazsa
      varsayilan ``"X"``. Kullanici listede her zaman duzenleyebilir.
    """
    s = (name or "").strip()
    s = re.sub(r"^\d+\s*/\s*", "", s)
    s = s.replace("/", "_").strip()
    axis = "X"
    m = re.search(r"([XYZ])(?=[_]|$)", s)
    if m:
        axis = m.group(1).upper()
    return (s or "CH", axis)


def load_max_hold_csv(
    path: Path,
    engine_id: str,
    run_id: str,
    metadata: Optional[Dict] = None,
) -> List[EngineRun]:
    """Cok-kanalli FFT Max Hold CSV'sini her sutun icin bir ``EngineRun``'a
    cevirir.

    Format:
      Satir 1 : ``"Freq (Hz)"`` , kanal_adi_1 , kanal_adi_2 , ...
      Satir 2+: freq            , amp_ch1     , amp_ch2     , ...

    Her kanal icin:
      - ``data_type = FFT_MAX_HOLD``
      - ``rpm_values = [0.0]``  (tek slice yer tutucu)
      - ``frequencies`` = ilk sutun
      - ``amplitudes`` = sutun verisi, sekil ``(1, F)``
      - ``sensor_location`` = sanitize edilmis kanal basligi
      - ``axis`` = kanal adindan tahmini (yoksa ``"X"``)

    Hatalar (bos dosya, eksik sutun) ``ValueError`` firlatir.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))

    # Bos satirlari at
    rows = [r for r in rows if r and any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise ValueError(f"Yetersiz satir: {path.name}")

    header = rows[0]
    if len(header) < 2:
        raise ValueError(
            f"En az 1 kanal sutunu olmali (sutun sayisi={len(header)}): {path.name}"
        )

    n_channels = len(header) - 1
    freqs: List[float] = []
    channel_amps: List[List[float]] = [[] for _ in range(n_channels)]

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        try:
            f = float(row[0].strip().replace(",", "."))
        except ValueError:
            # Belki ek baslik / metin satiri — atla
            continue
        freqs.append(f)
        for i in range(n_channels):
            cell = row[i + 1].strip() if i + 1 < len(row) else ""
            try:
                channel_amps[i].append(
                    float(cell.replace(",", ".")) if cell else 0.0
                )
            except ValueError:
                channel_amps[i].append(0.0)

    if not freqs:
        raise ValueError(f"Veri satiri yok: {path.name}")

    frequencies = np.array(freqs, dtype=np.float64)

    runs: List[EngineRun] = []
    for i, ch_name in enumerate(header[1:]):
        location, axis = _parse_max_hold_channel_name(ch_name)
        amps_1d = np.array(channel_amps[i], dtype=np.float64)
        amps_2d = amps_1d.reshape(1, -1)
        rpm_values = np.zeros(1, dtype=np.float64)

        meta = dict(metadata or {})
        meta.update({
            "channel_header": (ch_name or "").strip(),
            "source_format":  "fft_max_hold",
            "axis":           axis,
        })
        meta.setdefault("source_file", str(path))

        runs.append(EngineRun(
            engine_id=engine_id,
            run_id=run_id,
            sensor_location=location,
            axis=axis,
            data_type=DataType.FFT_MAX_HOLD,
            rpm_values=rpm_values,
            frequencies=frequencies,
            amplitudes=amps_2d,
            metadata=meta,
        ))

    logger.info(
        "FFT Max Hold yuklendi: %s -> %d kanal x %d frekans",
        path.name, n_channels, len(freqs),
    )
    return runs
