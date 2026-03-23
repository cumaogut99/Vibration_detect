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

    def _extract_from_order_tracking(
        self, run: EngineRun, orders: List[float]
    ) -> Dict[float, OrderAmplitude]:
        result: Dict[float, OrderAmplitude] = {}
        for order in orders:
            # Find closest order in the data
            idx = np.argmin(np.abs(run.orders - order))
            if abs(run.orders[idx] - order) / max(order, 1e-9) > self._tolerance:
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

        # Compute absolute minimum tolerance: at least 1 frequency bin wide
        if len(run.frequencies) > 1:
            min_bin_hz = float(run.frequencies[1] - run.frequencies[0])
        else:
            min_bin_hz = 1.0

        for order in orders:
            order_amps = np.zeros(run.n_slices)
            for i, (shaft_f, row_amps) in enumerate(zip(shaft_hz, run.amplitudes)):
                target_hz = order * shaft_f
                rel_tol = target_hz * self._tolerance
                # Always use at least 1.5 bins to guarantee a hit
                abs_tol = max(rel_tol, min_bin_hz * 1.5)
                mask = np.abs(run.frequencies - target_hz) <= abs_tol
                if mask.any():
                    order_amps[i] = float(row_amps[mask].max())
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

            ratio = np.where(
                ref_amps_interp > 1e-12,
                measured.amplitudes / ref_amps_interp,
                1.0,
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

        # Attach reference amplitudes to order data for downstream use
        for order, oa in order_data.items():
            if order in ref_order_data:
                ref = ref_order_data[order]
                f = interp1d(
                    ref.rpm_values, ref.amplitudes,
                    kind="linear", bounds_error=False,
                    fill_value=(ref.amplitudes[0] if len(ref.amplitudes) else 0.0,
                                ref.amplitudes[-1] if len(ref.amplitudes) else 0.0),
                )
                oa.reference_amplitudes = f(oa.rpm_values)
        oa.amplitude_ratio = np.where(
                    np.abs(oa.reference_amplitudes) > 1e-10,
                    oa.amplitudes / oa.reference_amplitudes,
                    1.0,
                )

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
