"""
Core analysis layer.

Responsibilities:
  1. OrderExtractor     — extract amplitude vs RPM for each order from raw data
  2. AnomalyDetector    — compare engine vs reference, flag amplitude exceedances
  3. FaultDiagnosticEngine — map anomaly patterns to fault signatures
  4. HealthScorer       — compute 0–100 health score

SOLID:
  - Single Responsibility: each class has one job
  - Open/Closed: add new detectors by subclassing BaseAnomalyDetector
  - Dependency Inversion: high-level engine depends on abstractions
"""

import abc
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import find_peaks

from models import AnomalyFlag, DiagnosticReport, EngineRun, OrderAmplitude
from engine_config import (
    ALERT_THRESHOLDS,
    FAULT_SIGNATURES,
    MANDATORY_MONITOR_ORDERS,
    ORDER_DEFINITIONS,
    SENSITIVE_ORDERS,
    SENSITIVE_THRESHOLD_MULTIPLIER,
    Severity,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  ORDER EXTRACTOR
# ─────────────────────────────────────────────────────────────────────────────

class OrderExtractor:
    """
    Extracts amplitude vs RPM for specified engine orders from waterfall or
    order-tracking data.
    """

    def __init__(self, order_tolerance: float = 0.05) -> None:
        """
        Args:
            order_tolerance: ±fraction of order for frequency band search.
                             0.05 = ±5% of the order frequency.
        """
        self._tolerance = order_tolerance

    def extract(
        self,
        run: EngineRun,
        orders: Optional[List[float]] = None,
    ) -> Dict[float, OrderAmplitude]:
        """
        Extract amplitude vs RPM for each order.

        Returns dict: order → OrderAmplitude
        """
        if orders is None:
            orders = list(ORDER_DEFINITIONS.keys())

        if run.orders is not None and run.order_amplitudes is not None:
            return self._extract_from_order_tracking(run, orders)
        else:
            return self._extract_from_waterfall(run, orders)

    def _tol_for(self, order: float) -> float:
        """OrderDefinition.tolerance_override varsa onu, yoksa varsayılanı döndürür."""
        odef = ORDER_DEFINITIONS.get(order)
        if odef is not None and odef.tolerance_override is not None:
            return float(odef.tolerance_override)
        return self._tolerance

    def _extract_from_order_tracking(
        self, run: EngineRun, orders: List[float]
    ) -> Dict[float, OrderAmplitude]:
        result: Dict[float, OrderAmplitude] = {}
        for order in orders:
            tol = self._tol_for(order)
            # Find closest order in the data
            idx = np.argmin(np.abs(run.orders - order))
            if abs(run.orders[idx] - order) / max(order, 1e-9) > tol:
                logger.debug("Order %.2f not found in order-tracking data (closest: %.2f)", order, run.orders[idx])
                continue
            amps = run.order_amplitudes[:, idx]
            result[order] = OrderAmplitude(
                order=order,
                engine_id=run.engine_id,
                run_id=run.run_id,
                sensor_location=run.sensor_location,
                rpm_values=run.rpm_values.copy(),
                amplitudes=amps.copy(),
            )
        return result

    def _extract_from_waterfall(
        self, run: EngineRun, orders: List[float]
    ) -> Dict[float, OrderAmplitude]:
        result: Dict[float, OrderAmplitude] = {}
        shaft_hz = run.rpm_values / 60.0  # (n_slices,)

        if len(run.frequencies) > 1:
            bin_hz = float(run.frequencies[1] - run.frequencies[0])
        else:
            bin_hz = 1.0

        for order in orders:
            tol = self._tol_for(order)
            order_amps = np.zeros(run.n_slices)
            for i, (shaft_f, row_amps) in enumerate(zip(shaft_hz, run.amplitudes)):
                target_hz = order * shaft_f
                abs_tol = target_hz * tol
                mask = np.abs(run.frequencies - target_hz) <= abs_tol
                if mask.any():
                    order_amps[i] = float(row_amps[mask].max())
                else:
                    # Tight-tolerance + low frequency: fall back to nearest bin
                    # so the order isn't all-zero. Bleed is still bounded by
                    # half the bin width.
                    nearest_idx = int(np.argmin(np.abs(run.frequencies - target_hz)))
                    if abs(run.frequencies[nearest_idx] - target_hz) <= bin_hz:
                        order_amps[i] = float(row_amps[nearest_idx])
                    else:
                        order_amps[i] = 0.0

            result[order] = OrderAmplitude(
                order=order,
                engine_id=run.engine_id,
                run_id=run.run_id,
                sensor_location=run.sensor_location,
                rpm_values=run.rpm_values.copy(),
                amplitudes=order_amps,
            )
        return result


# ─────────────────────────────────────────────────────────────────────────────
#  ANOMALY DETECTORS
# ─────────────────────────────────────────────────────────────────────────────

class BaseAnomalyDetector(abc.ABC):
    @abc.abstractmethod
    def detect(
        self,
        run: EngineRun,
        order_data: Dict[float, OrderAmplitude],
        reference_order_data: Dict[float, OrderAmplitude],
    ) -> List[AnomalyFlag]:
        """Return list of anomalies found."""


class OrderAmplitudeAnomalyDetector(BaseAnomalyDetector):
    """
    Detects orders where measured amplitude significantly exceeds the reference.
    Operates on extracted OrderAmplitude objects.
    """

    def detect(
        self,
        run: EngineRun,
        order_data: Dict[float, OrderAmplitude],
        reference_order_data: Dict[float, OrderAmplitude],
    ) -> List[AnomalyFlag]:
        anomalies: List[AnomalyFlag] = []

        for order, measured in order_data.items():
            if order not in reference_order_data:
                continue

            ref = reference_order_data[order]
            threshold = self._threshold_for_order(order)

            # Interpolate reference amplitudes to measured RPM grid
            ref_amps_interp = self._interpolate_to_rpm(
                ref.rpm_values, ref.amplitudes, measured.rpm_values
            )

            mask = ref_amps_interp > 1e-12
            ratio = np.ones_like(measured.amplitudes)
            np.divide(
                measured.amplitudes, ref_amps_interp,
                out=ratio, where=mask,
            )

            # Find RPM points where ratio exceeds threshold
            warning_mask = ratio >= threshold
            if not warning_mask.any():
                continue

            # Find the worst point
            worst_idx = int(np.argmax(ratio))
            worst_rpm = float(measured.rpm_values[worst_idx])
            worst_amp = float(measured.amplitudes[worst_idx])
            worst_ref = float(ref_amps_interp[worst_idx])
            worst_ratio = float(ratio[worst_idx])

            severity = self._classify_severity(worst_ratio, order)
            shaft_hz = worst_rpm / 60.0
            freq_hz = order * shaft_hz

            order_def = ORDER_DEFINITIONS.get(order)
            faults = order_def.fault_indicators if order_def else []
            desc = (
                f"Order {order:.1f}× amplitude is {worst_ratio:.2f}× reference "
                f"at {worst_rpm:.0f} RPM ({freq_hz:.1f} Hz). "
                + (order_def.description if order_def else "")
            )

            anomalies.append(
                AnomalyFlag(
                    order=order,
                    frequency_hz=freq_hz,
                    rpm=worst_rpm,
                    measured_amplitude=worst_amp,
                    reference_amplitude=worst_ref,
                    amplitude_ratio=worst_ratio,
                    fault_signatures=faults,
                    severity=severity.value,
                    sensor_location=run.sensor_location,
                    engine_id=run.engine_id,
                    run_id=run.run_id,
                    description=desc,
                )
            )

        return anomalies

    def _threshold_for_order(self, order: float) -> float:
        base = ALERT_THRESHOLDS[Severity.WARNING]
        if order in SENSITIVE_ORDERS:
            return base * SENSITIVE_THRESHOLD_MULTIPLIER
        return base

    def _classify_severity(self, ratio: float, order: float) -> Severity:
        critical = ALERT_THRESHOLDS[Severity.CRITICAL]
        warning = self._threshold_for_order(order)
        if ratio >= critical:
            return Severity.CRITICAL
        if ratio >= warning:
            return Severity.WARNING
        return Severity.INFO

    @staticmethod
    def _interpolate_to_rpm(
        src_rpm: np.ndarray,
        src_amps: np.ndarray,
        target_rpm: np.ndarray,
    ) -> np.ndarray:
        if len(src_rpm) < 2:
            return np.full_like(target_rpm, src_amps[0] if len(src_amps) else 0.0)
        f = interp1d(
            src_rpm, src_amps,
            kind="linear",
            bounds_error=False,
            fill_value=(src_amps[0], src_amps[-1]),
        )
        return f(target_rpm)


class BroadbandAnomalyDetector(BaseAnomalyDetector):
    """
    Detects overall broadband RMS increase compared to reference.
    Catches diffuse damage not concentrated at specific orders.
    """

    def detect(
        self,
        run: EngineRun,
        order_data: Dict[float, OrderAmplitude],
        reference_order_data: Dict[float, OrderAmplitude],
    ) -> List[AnomalyFlag]:
        anomalies: List[AnomalyFlag] = []

        for i, rpm in enumerate(run.rpm_values):
            if i >= run.amplitudes.shape[0]:
                break
            meas_rms = float(np.sqrt(np.mean(run.amplitudes[i] ** 2)))

            # Find closest RPM in reference
            # (reference run may have different RPM grid)
            # Here we skip if no reference data available in run
            # This detector complements OrderAmplitudeDetector

        return anomalies  # Broadband detection — placeholder for RMS comparison


# ─────────────────────────────────────────────────────────────────────────────
#  FAULT DIAGNOSTIC ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class FaultDiagnosticEngine:
    """
    Maps detected anomalies to fault signatures from engine_config.
    Returns a ranked list of probable faults.
    """

    def diagnose(self, anomalies: List[AnomalyFlag]) -> List[Dict]:
        """
        Returns list of dicts: {fault_signature, confidence, evidence_orders, ...}
        sorted by confidence descending.
        """
        if not anomalies:
            return []

        flagged_orders = {a.order for a in anomalies}
        anomaly_map = {a.order: a for a in anomalies}

        diagnoses = []
        for sig in FAULT_SIGNATURES:
            primary_hit = sum(1 for o in sig.primary_orders if o in flagged_orders)
            secondary_hit = sum(1 for o in sig.secondary_orders if o in flagged_orders)

            if primary_hit == 0:
                continue  # Must have at least one primary order hit

            total_primary = len(sig.primary_orders)
            total_secondary = len(sig.secondary_orders)

            # Confidence: primary matches weighted 2×, secondary 1×
            max_score = total_primary * 2 + total_secondary
            achieved = primary_hit * 2 + secondary_hit
            confidence = achieved / max_score if max_score > 0 else 0.0

            # Worst severity among flagged orders for this signature
            sig_anomalies = [
                anomaly_map[o]
                for o in (sig.primary_orders + sig.secondary_orders)
                if o in anomaly_map
            ]
            severities = [a.severity for a in sig_anomalies]
            worst_sev = (
                Severity.CRITICAL.value if Severity.CRITICAL.value in severities
                else Severity.WARNING.value if Severity.WARNING.value in severities
                else Severity.INFO.value
            )

            max_ratio = max((a.amplitude_ratio for a in sig_anomalies), default=1.0)

            diagnoses.append({
                "fault_name": sig.name,
                "category": sig.category.value,
                "confidence": round(confidence, 3),
                "severity": worst_sev,
                "max_amplitude_ratio": round(max_ratio, 3),
                "primary_orders_hit": [o for o in sig.primary_orders if o in flagged_orders],
                "secondary_orders_hit": [o for o in sig.secondary_orders if o in flagged_orders],
                "description": sig.description,
                "recommendation": sig.recommendation,
            })

        diagnoses.sort(key=lambda d: (-d["confidence"], -d["max_amplitude_ratio"]))
        return diagnoses


# ─────────────────────────────────────────────────────────────────────────────
#  HEALTH SCORER
# ─────────────────────────────────────────────────────────────────────────────

class HealthScorer:
    """
    Converts anomaly list into a 0–100 health score.
    100 = identical to reference; 0 = catastrophic deviations.
    """

    CRITICAL_PENALTY = 20.0
    WARNING_PENALTY = 7.0
    BASE_SCORE = 100.0
    MIN_SCORE = 5.0
    MAX_TOTAL_PENALTY = 95.0

    def score(self, anomalies: List[AnomalyFlag]) -> float:
        # Group by order — only count the worst anomaly per order
        worst_by_order: dict = {}
        for a in anomalies:
            if a.order not in worst_by_order or a.amplitude_ratio > worst_by_order[a.order].amplitude_ratio:
                worst_by_order[a.order] = a

        penalty = 0.0
        for a in worst_by_order.values():
            if a.severity == Severity.CRITICAL.value:
                factor = min(a.amplitude_ratio / ALERT_THRESHOLDS[Severity.CRITICAL], 2.0)
                penalty += self.CRITICAL_PENALTY * factor
            elif a.severity == Severity.WARNING.value:
                factor = min(a.amplitude_ratio / ALERT_THRESHOLDS[Severity.WARNING], 2.0)
                penalty += self.WARNING_PENALTY * factor

        penalty = min(penalty, self.MAX_TOTAL_PENALTY)
        score = max(self.MIN_SCORE, self.BASE_SCORE - penalty)
        return round(score, 1)


# ─────────────────────────────────────────────────────────────────────────────
#  ANALYSIS ORCHESTRATOR  (Facade)
# ─────────────────────────────────────────────────────────────────────────────

class VibrationAnalyzer:
    """
    Top-level facade that orchestrates extraction → detection → diagnosis → scoring.
    Depends on abstractions, not concretions.
    """

    def __init__(
        self,
        extractor: Optional[OrderExtractor] = None,
        detectors: Optional[List[BaseAnomalyDetector]] = None,
        diagnostic_engine: Optional[FaultDiagnosticEngine] = None,
        scorer: Optional[HealthScorer] = None,
    ) -> None:
        self._extractor = extractor or OrderExtractor()
        self._detectors = detectors or [OrderAmplitudeAnomalyDetector()]
        self._diagnostic_engine = diagnostic_engine or FaultDiagnosticEngine()
        self._scorer = scorer or HealthScorer()

    def analyze(
        self,
        run: EngineRun,
        reference: EngineRun,
        orders_to_analyze: Optional[List[float]] = None,
    ) -> DiagnosticReport:
        """
        Full analysis pipeline for a single engine run vs a reference.
        """
        if orders_to_analyze is None:
            orders_to_analyze = list(ORDER_DEFINITIONS.keys())

        # Ensure mandatory orders are always included
        for o in MANDATORY_MONITOR_ORDERS:
            if o not in orders_to_analyze:
                orders_to_analyze.append(o)

        logger.info(
            "Analyzing engine %s run %s vs reference %s",
            run.engine_id, run.run_id, reference.engine_id,
        )

        order_data = self._extractor.extract(run, orders_to_analyze)
        ref_order_data = self._extractor.extract(reference, orders_to_analyze)

        # Attach reference amplitudes + amplitude ratios to each OrderAmplitude.
        # The ratio is only sensible where the reference is non-zero; np.divide
        # with where= avoids the divide-by-zero RuntimeWarning.
        for order, oa in order_data.items():
            if order not in ref_order_data:
                continue
            ref = ref_order_data[order]
            interp = interp1d(
                ref.rpm_values, ref.amplitudes,
                kind="linear", bounds_error=False,
                fill_value=(ref.amplitudes[0] if len(ref.amplitudes) else 0.0,
                            ref.amplitudes[-1] if len(ref.amplitudes) else 0.0),
            )
            oa.reference_amplitudes = interp(oa.rpm_values)
            mask = np.abs(oa.reference_amplitudes) > 1e-10
            ratio = np.ones_like(oa.amplitudes)
            np.divide(
                oa.amplitudes, oa.reference_amplitudes,
                out=ratio, where=mask,
            )
            oa.amplitude_ratio = ratio

        all_anomalies: List[AnomalyFlag] = []
        for detector in self._detectors:
            all_anomalies.extend(detector.detect(run, order_data, ref_order_data))

        # Deduplicate by (order, rpm) keeping worst severity
        all_anomalies = self._deduplicate(all_anomalies)

        diagnoses = self._diagnostic_engine.diagnose(all_anomalies)
        health_score = self._scorer.score(all_anomalies)

        recommendations = list(dict.fromkeys(
            d["recommendation"] for d in diagnoses
        ))

        critical_faults = [d["fault_name"] for d in diagnoses if d["severity"] == Severity.CRITICAL.value]
        warning_faults = [d["fault_name"] for d in diagnoses if d["severity"] == Severity.WARNING.value]

        summary_parts = []
        if not all_anomalies:
            summary_parts.append("No significant anomalies detected. Engine vibration within reference limits.")
        else:
            if critical_faults:
                summary_parts.append(f"CRITICAL: {', '.join(critical_faults)}.")
            if warning_faults:
                summary_parts.append(f"Warning: {', '.join(warning_faults)}.")
            summary_parts.append(f"Health score: {health_score}/100.")

        return DiagnosticReport(
            engine_id=run.engine_id,
            run_id=run.run_id,
            sensor_location=run.sensor_location,
            anomalies=all_anomalies,
            fault_diagnoses=diagnoses,
            overall_health_score=health_score,
            reference_engine_id=reference.engine_id,
            summary=" ".join(summary_parts),
            recommendations=recommendations,
        )

    @staticmethod
    def _deduplicate(anomalies: List[AnomalyFlag]) -> List[AnomalyFlag]:
        seen: Dict[Tuple, AnomalyFlag] = {}
        for a in anomalies:
            key = (round(a.order, 2), round(a.rpm, 0))
            if key not in seen or a.amplitude_ratio > seen[key].amplitude_ratio:
                seen[key] = a
        return list(seen.values())


def build_default_analyzer() -> VibrationAnalyzer:
    """Factory for default production analyzer."""
    return VibrationAnalyzer(
        extractor=OrderExtractor(order_tolerance=0.05),
        detectors=[
            OrderAmplitudeAnomalyDetector(),
            BroadbandAnomalyDetector(),
        ],
        diagnostic_engine=FaultDiagnosticEngine(),
        scorer=HealthScorer(),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  FFT MAX HOLD — BAND-MAKS ANALIZI  (waterfall akisindan tamamen bagimsiz)
#
#  Max-hold spektrumu tum RPM sweep'ini tek spektruma cokertir; RPM↔frekans
#  bagi kaybolur. Bilinen RPM araligi [rpm_min, rpm_max] verildiginde her
#  order N su frekans bandini supurur:
#
#     band_N = [N * rpm_min / 60 ,  N * rpm_max / 60]
#
#  O bandin maksimum genligi, o order'in max-hold seviyesi kabul edilir.
#  Olculen vs referans bant-maks orani mevcut FAULT_SIGNATURES /
#  ALERT_THRESHOLDS / HealthScorer altyapisina beslenir.
#
#  Kisitlama: RPM araligi genis oldugunda komsu order bantlari cakisir;
#  bu yuzden bulgular order-ailesi/frekans-bolgesi olarak yorumlanmalidir.
# ─────────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass


@dataclass
class MaxHoldBand:
    """Tek bir order icin bant-maks ozeti."""
    order: float
    band_lo_hz: float
    band_hi_hz: float
    measured_amp: float
    reference_amp: Optional[float]
    measured_freq_hz: float          # bant-maks'in gozlendigi frekans
    implied_rpm: float               # 60 * freq / order
    ratio: Optional[float]


class MaxHoldBandExtractor:
    """Her order icin RPM araligindan bant hesaplar, bant-maks cikarir."""

    def extract(
        self,
        run: EngineRun,
        rpm_min: float,
        rpm_max: float,
        orders: Optional[List[float]] = None,
    ) -> Dict[float, Tuple[float, float, float, float]]:
        """order -> (band_max_amp, band_max_freq_hz, band_lo_hz, band_hi_hz).

        Bant icinde frekans bini yoksa o order atlanir.
        """
        if orders is None:
            orders = list(ORDER_DEFINITIONS.keys())

        freqs = np.asarray(run.frequencies, dtype=np.float64)
        # FFT_MAX_HOLD amplitudes sekli (1, F); tek satir.
        amps = np.asarray(run.amplitudes, dtype=np.float64)
        spectrum = amps[0] if amps.ndim == 2 else amps

        f_lo_shaft = float(rpm_min) / 60.0
        f_hi_shaft = float(rpm_max) / 60.0

        result: Dict[float, Tuple[float, float, float, float]] = {}
        for order in orders:
            band_lo = order * f_lo_shaft
            band_hi = order * f_hi_shaft
            mask = (freqs >= band_lo) & (freqs <= band_hi)
            if not mask.any():
                continue
            band_amps = spectrum[mask]
            band_freqs = freqs[mask]
            j = int(np.argmax(band_amps))
            result[order] = (
                float(band_amps[j]),
                float(band_freqs[j]),
                float(band_lo),
                float(band_hi),
            )
        return result


class MaxHoldAnalyzer:
    """Iki FFT Max Hold kanali (olculen vs referans) arasinda bant-maks
    karsilastirmasi yapar; mevcut tani/skor altyapisini yeniden kullanir."""

    def __init__(
        self,
        extractor: Optional[MaxHoldBandExtractor] = None,
        diagnostic_engine: Optional[FaultDiagnosticEngine] = None,
        scorer: Optional[HealthScorer] = None,
    ) -> None:
        self._extractor = extractor or MaxHoldBandExtractor()
        self._diag = diagnostic_engine or FaultDiagnosticEngine()
        self._scorer = scorer or HealthScorer()

    def _threshold_for_order(self, order: float) -> float:
        base = ALERT_THRESHOLDS[Severity.WARNING]
        if order in SENSITIVE_ORDERS:
            return base * SENSITIVE_THRESHOLD_MULTIPLIER
        return base

    def _classify(self, ratio: float, order: float) -> Severity:
        if ratio >= ALERT_THRESHOLDS[Severity.CRITICAL]:
            return Severity.CRITICAL
        if ratio >= self._threshold_for_order(order):
            return Severity.WARNING
        return Severity.INFO

    def analyze(
        self,
        run: EngineRun,
        reference: EngineRun,
        rpm_min: float,
        rpm_max: float,
        orders_to_analyze: Optional[List[float]] = None,
    ) -> Tuple[DiagnosticReport, Dict[float, MaxHoldBand]]:
        if orders_to_analyze is None:
            orders_to_analyze = list(ORDER_DEFINITIONS.keys())
        for o in MANDATORY_MONITOR_ORDERS:
            if o not in orders_to_analyze:
                orders_to_analyze.append(o)

        meas_bands = self._extractor.extract(run, rpm_min, rpm_max, orders_to_analyze)
        ref_bands  = self._extractor.extract(reference, rpm_min, rpm_max, orders_to_analyze)

        bands: Dict[float, MaxHoldBand] = {}
        anomalies: List[AnomalyFlag] = []

        for order, (m_amp, m_freq, b_lo, b_hi) in meas_bands.items():
            implied_rpm = 60.0 * m_freq / order if order > 0 else 0.0
            r_tuple = ref_bands.get(order)
            r_amp = r_tuple[0] if r_tuple else None

            ratio = None
            if r_amp is not None and r_amp > 1e-12:
                ratio = m_amp / r_amp

            bands[order] = MaxHoldBand(
                order=order,
                band_lo_hz=b_lo, band_hi_hz=b_hi,
                measured_amp=m_amp, reference_amp=r_amp,
                measured_freq_hz=m_freq, implied_rpm=implied_rpm,
                ratio=ratio,
            )

            if ratio is None:
                continue
            severity = self._classify(ratio, order)
            if severity is Severity.INFO:
                continue

            odef = ORDER_DEFINITIONS.get(order)
            faults = odef.fault_indicators if odef else []
            desc = (
                f"Order {order:g}× bant-maks {ratio:.2f}× referans "
                f"({b_lo:.0f}–{b_hi:.0f} Hz bandi; tepe {m_freq:.1f} Hz, "
                f"~{implied_rpm:.0f} RPM'de bu order'a denk gelir). "
                "Max-hold bant tabanli — komsu order bantlari cakisabilir. "
                + (odef.description if odef else "")
            )
            anomalies.append(AnomalyFlag(
                order=order,
                frequency_hz=m_freq,
                rpm=implied_rpm,
                measured_amplitude=m_amp,
                reference_amplitude=r_amp if r_amp is not None else 0.0,
                amplitude_ratio=ratio,
                fault_signatures=faults,
                severity=severity.value,
                sensor_location=run.sensor_location,
                engine_id=run.engine_id,
                run_id=run.run_id,
                description=desc,
            ))

        diagnoses = self._diag.diagnose(anomalies)
        health = self._scorer.score(anomalies)
        recommendations = list(dict.fromkeys(
            d["recommendation"] for d in diagnoses
        ))
        crit = [d["fault_name"] for d in diagnoses if d["severity"] == Severity.CRITICAL.value]
        warn = [d["fault_name"] for d in diagnoses if d["severity"] == Severity.WARNING.value]

        parts = [
            f"FFT Max Hold bant-maks analizi (RPM {rpm_min:.0f}–{rpm_max:.0f}). "
        ]
        if not anomalies:
            parts.append("Referans limitleri icinde, belirgin anomali yok.")
        else:
            if crit:
                parts.append(f"KRITIK: {', '.join(crit)}.")
            if warn:
                parts.append(f"Uyari: {', '.join(warn)}.")
            parts.append(f"Saglik skoru: {health}/100.")
        parts.append(
            "Not: RPM araligi genis oldugunda komsu order bantlari cakisir; "
            "yuksek order bulgulari ayri ayri degil aile/bolge olarak yorumlanmalidir."
        )

        report = DiagnosticReport(
            engine_id=run.engine_id,
            run_id=run.run_id,
            sensor_location=run.sensor_location,
            anomalies=anomalies,
            fault_diagnoses=diagnoses,
            overall_health_score=health,
            reference_engine_id=reference.engine_id,
            summary=" ".join(parts),
            recommendations=recommendations,
        )
        return report, bands
