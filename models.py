"""
Domain data models for vibration analysis.
Pure data structures — no business logic.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import numpy as np


class DataType(Enum):
    FFT_WATERFALL = "fft_waterfall"
    ORDER_TRACKING = "order_tracking"
    TIME_WAVEFORM = "time_waveform"
    SINGLE_FFT = "single_fft"


@dataclass
class EngineRun:
    """Represents a single engine test run / recording session."""
    engine_id: str
    run_id: str
    sensor_location: str
    axis: str                 # "X" | "Y" | "Z"
    data_type: DataType
    rpm_values: np.ndarray        # Shape: (N,) — RPM at each time slice
    frequencies: np.ndarray       # Shape: (F,) — frequency axis in Hz
    amplitudes: np.ndarray        # Shape: (N, F) or (F,) for single FFT
    time_axis: Optional[np.ndarray] = None   # Shape: (N,) — seconds
    orders: Optional[np.ndarray] = None      # Shape: (O,) — order axis (for order tracking)
    order_amplitudes: Optional[np.ndarray] = None  # Shape: (N, O)
    metadata: Dict = field(default_factory=dict)
    is_reference: bool = False

    @property
    def n_slices(self) -> int:
        return len(self.rpm_values)

    @property
    def n_freqs(self) -> int:
        return len(self.frequencies)

    @property
    def rpm_range(self) -> Tuple[float, float]:
        return float(self.rpm_values.min()), float(self.rpm_values.max())

    @property
    def shaft_frequency_hz(self) -> np.ndarray:
        """Shaft frequency in Hz for each RPM slice."""
        return self.rpm_values / 60.0


@dataclass
class OrderAmplitude:
    """Amplitude at a specific order for a given engine/run."""
    order: float
    engine_id: str
    run_id: str
    sensor_location: str
    rpm_values: np.ndarray
    amplitudes: np.ndarray        # Amplitude vs RPM
    reference_amplitudes: Optional[np.ndarray] = None
    amplitude_ratio: Optional[np.ndarray] = None  # amp / reference


@dataclass
class AnomalyFlag:
    """A detected anomaly at a specific order/frequency."""
    order: float
    frequency_hz: float
    rpm: float
    measured_amplitude: float
    reference_amplitude: float
    amplitude_ratio: float
    fault_signatures: List[str]
    severity: str
    sensor_location: str
    engine_id: str
    run_id: str
    description: str


@dataclass
class DiagnosticReport:
    """Full diagnostic report for one engine run."""
    engine_id: str
    run_id: str
    sensor_location: str
    anomalies: List[AnomalyFlag]
    fault_diagnoses: List[Dict]
    overall_health_score: float   # 0–100
    reference_engine_id: Optional[str]
    summary: str
    recommendations: List[str]


@dataclass
class ComparisonResult:
    """Side-by-side comparison of multiple engines."""
    reference_engine_id: str
    compared_engine_ids: List[str]
    order_comparisons: Dict[float, Dict]   # order → {engine_id: amplitudes}
    reports: Dict[str, DiagnosticReport]   # engine_id → report
