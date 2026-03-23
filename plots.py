"""
Visualization layer — all plots produced here.
Uses matplotlib with a consistent dark industrial theme.

SOLID: Each plot function is independent; PlotManager orchestrates them.
"""

import io
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, safe for all environments
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.ticker as ticker
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec

from models import AnomalyFlag, DiagnosticReport, EngineRun, OrderAmplitude
from engine_config import ORDER_DEFINITIONS, FAULT_SIGNATURES, FaultCategory

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  THEME
# ─────────────────────────────────────────────────────────────────────────────

THEME = {
    "bg": "#0d1117",
    "surface": "#161b22",
    "border": "#30363d",
    "text": "#e6edf3",
    "text_muted": "#8b949e",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "yellow": "#d29922",
    "red": "#f85149",
    "orange": "#f0883e",
    "purple": "#bc8cff",
    "colormap": "inferno",
    "ref_color": "#58a6ff",
    "meas_color": "#f0883e",
    "anomaly_color": "#f85149",
    "warning_color": "#d29922",
}

CATEGORY_COLORS = {
    FaultCategory.COMBUSTION: "#e8724a",
    FaultCategory.MECHANICAL: "#f0883e",
    FaultCategory.BEARING: "#bc8cff",
    FaultCategory.GEAR: "#3fb950",
    FaultCategory.IMBALANCE: "#58a6ff",
    FaultCategory.MISALIGNMENT: "#d29922",
    FaultCategory.VALVE: "#f78166",
    FaultCategory.STRUCTURAL: "#8b949e",
}


def _apply_theme(fig: Figure, axes=None) -> None:
    fig.patch.set_facecolor(THEME["bg"])
    if axes is None:
        return
    if not hasattr(axes, "__iter__"):
        axes = [axes]
    for ax in axes:
        ax.set_facecolor(THEME["surface"])
        ax.tick_params(colors=THEME["text_muted"], labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(THEME["border"])
        ax.xaxis.label.set_color(THEME["text_muted"])
        ax.yaxis.label.set_color(THEME["text_muted"])
        ax.title.set_color(THEME["text"])
        ax.grid(True, color=THEME["border"], linewidth=0.5, alpha=0.6)


# ─────────────────────────────────────────────────────────────────────────────
#  WATERFALL PLOT
# ─────────────────────────────────────────────────────────────────────────────

def plot_waterfall(
    run: EngineRun,
    title: str = "",
    freq_max: float = 3000.0,
    annotate_orders: bool = True,
) -> Figure:
    """2D color-map waterfall: X=frequency, Y=RPM, color=amplitude."""
    freq_mask = run.frequencies <= freq_max
    freqs = run.frequencies[freq_mask]
    amps = run.amplitudes[:, freq_mask]

    # dB conversion (add small floor to avoid log(0))
    amps_db = 20 * np.log10(np.maximum(amps, 1e-12))

    fig, ax = plt.subplots(figsize=(12, 6))
    _apply_theme(fig, ax)

    # Meshgrid for pcolormesh
    F, R = np.meshgrid(freqs, run.rpm_values)
    vmin, vmax = np.percentile(amps_db, [5, 99])

    mesh = ax.pcolormesh(
        F, R, amps_db,
        cmap=THEME["colormap"],
        vmin=vmin, vmax=vmax,
        shading="auto",
        rasterized=True,
    )
    cbar = fig.colorbar(mesh, ax=ax, pad=0.01)
    cbar.set_label("Amplitude (dB)", color=THEME["text_muted"], fontsize=8)
    cbar.ax.tick_params(colors=THEME["text_muted"])
    cbar.outline.set_edgecolor(THEME["border"])

    # Overlay order lines
    if annotate_orders:
        rpm_range = run.rpm_values
        for order, odef in ORDER_DEFINITIONS.items():
            order_freqs = order * rpm_range / 60.0
            color = CATEGORY_COLORS.get(odef.category, THEME["text_muted"])
            ax.plot(order_freqs, rpm_range, "--", color=color, linewidth=0.6, alpha=0.55)
            # Label at top of chart
            label_freq = order * run.rpm_values[-1] / 60.0
            if label_freq <= freq_max:
                ax.text(
                    label_freq, run.rpm_values[-1] * 1.001,
                    f"{order}×",
                    color=color, fontsize=6, ha="center", va="bottom", alpha=0.8,
                )

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("RPM")
    ax.set_title(
        title or f"FFT Waterfall — {run.engine_id} / {run.sensor_location}",
        fontsize=10, pad=8,
    )
    ax.set_xlim(0, freq_max)
    fig.tight_layout()
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  ORDER TRACKING COMPARISON PLOT
# ─────────────────────────────────────────────────────────────────────────────

def plot_order_comparison(
    order_data: Dict[float, OrderAmplitude],
    ref_order_data: Dict[float, OrderAmplitude],
    anomalies: List[AnomalyFlag],
    orders_to_plot: Optional[List[float]] = None,
    cols: int = 3,
) -> Figure:
    """Grid of subplots — one per order — showing measured vs reference."""
    if orders_to_plot is None:
        # Show orders that have anomalies + mandatory
        flagged = {a.order for a in anomalies}
        from engine_config import MANDATORY_MONITOR_ORDERS
        orders_to_plot = sorted(set(MANDATORY_MONITOR_ORDERS) | flagged)

    orders_to_plot = [o for o in orders_to_plot if o in order_data]
    if not orders_to_plot:
        orders_to_plot = sorted(order_data.keys())[:12]

    n = len(orders_to_plot)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 2.8))
    fig.patch.set_facecolor(THEME["bg"])

    axes_flat = np.array(axes).flatten()

    anomaly_orders = {a.order: a for a in anomalies}

    for idx, order in enumerate(orders_to_plot):
        ax = axes_flat[idx]
        _apply_theme(fig, ax)

        meas = order_data[order]
        has_ref = order in ref_order_data

        if has_ref:
            ref = ref_order_data[order]
            ax.plot(ref.rpm_values, ref.amplitudes,
                    color=THEME["ref_color"], lw=1.2, alpha=0.7, label="Reference")

        color = THEME["anomaly_color"] if order in anomaly_orders else THEME["meas_color"]
        ax.plot(meas.rpm_values, meas.amplitudes,
                color=color, lw=1.5, label="Measured")

        # Shade the region between
        if has_ref:
            from scipy.interpolate import interp1d
            ref_interp = interp1d(
                ref.rpm_values, ref.amplitudes,
                kind="linear", bounds_error=False,
                fill_value=(ref.amplitudes[0], ref.amplitudes[-1]),
            )
            ref_at_meas = ref_interp(meas.rpm_values)
            above = meas.amplitudes > ref_at_meas
            ax.fill_between(
                meas.rpm_values, ref_at_meas, meas.amplitudes,
                where=above, alpha=0.15, color=THEME["anomaly_color"],
            )

        # Mark anomaly RPM
        if order in anomaly_orders:
            a = anomaly_orders[order]
            ax.axvline(a.rpm, color=THEME["anomaly_color"], lw=0.8, linestyle=":", alpha=0.7)
            ax.text(
                0.97, 0.95,
                f"×{a.amplitude_ratio:.2f}",
                transform=ax.transAxes,
                ha="right", va="top",
                color=THEME["anomaly_color"], fontsize=7, fontweight="bold",
            )

        odef = ORDER_DEFINITIONS.get(order)
        short_name = odef.name if odef else f"Order {order}"
        ax.set_title(f"{short_name}", fontsize=8, pad=4)
        ax.set_xlabel("RPM", fontsize=7)
        ax.set_ylabel("Amplitude", fontsize=7)
        ax.legend(fontsize=6, framealpha=0.2, facecolor=THEME["surface"])

    # Hide unused axes
    for idx in range(len(orders_to_plot), len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle("Order Amplitude Comparison: Measured vs Reference",
                 color=THEME["text"], fontsize=10, y=1.01)
    fig.tight_layout()
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  MULTI-ENGINE COMPARISON BAR CHART
# ─────────────────────────────────────────────────────────────────────────────

def plot_engine_health_comparison(
    reports: Dict[str, DiagnosticReport],
    reference_id: str,
) -> Figure:
    """Bar chart comparing health scores across engines."""
    engine_ids = [eid for eid in reports if eid != reference_id]
    scores = [reports[eid].overall_health_score for eid in engine_ids]
    severities = []
    for eid in engine_ids:
        r = reports[eid]
        if any(d["severity"] == "Critical" for d in r.fault_diagnoses):
            severities.append(THEME["red"])
        elif any(d["severity"] == "Warning" for d in r.fault_diagnoses):
            severities.append(THEME["yellow"])
        else:
            severities.append(THEME["green"])

    fig, ax = plt.subplots(figsize=(max(8, len(engine_ids) * 1.2), 5))
    _apply_theme(fig, ax)

    bars = ax.bar(engine_ids, scores, color=severities, width=0.6, zorder=3)
    ax.axhline(100, color=THEME["ref_color"], lw=1, linestyle="--", alpha=0.5, label="Reference (100)")
    ax.axhline(70, color=THEME["yellow"], lw=0.8, linestyle=":", alpha=0.5, label="Warning threshold")
    ax.axhline(50, color=THEME["red"], lw=0.8, linestyle=":", alpha=0.5, label="Critical threshold")

    for bar, score in zip(bars, scores):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
            f"{score:.0f}",
            ha="center", va="bottom", color=THEME["text"], fontsize=8, fontweight="bold",
        )

    ax.set_ylim(0, 115)
    ax.set_ylabel("Health Score (0–100)")
    ax.set_title("Engine Fleet Health Comparison", fontsize=11)
    ax.legend(fontsize=7, framealpha=0.2, facecolor=THEME["surface"])
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  DIAGNOSTIC SUMMARY CARD
# ─────────────────────────────────────────────────────────────────────────────

def plot_diagnostic_card(report: DiagnosticReport) -> Figure:
    """Single-page diagnostic summary for one engine."""
    fig = plt.figure(figsize=(10, 7))
    fig.patch.set_facecolor(THEME["bg"])

    gs = GridSpec(3, 2, figure=fig, hspace=0.5, wspace=0.3)

    # ── Health Score Gauge ──────────────────────────────────────────────────
    ax_gauge = fig.add_subplot(gs[0, 0], polar=True)
    ax_gauge.set_facecolor(THEME["surface"])
    score = report.overall_health_score
    angle = np.pi * (1 - score / 100)
    theta = np.linspace(0, np.pi, 200)
    for i in range(len(theta) - 1):
        frac = i / (len(theta) - 1)
        c = plt.cm.RdYlGn(frac)
        ax_gauge.fill_between([theta[i], theta[i + 1]], [0.7, 0.7], [1.0, 1.0],
                               color=c, alpha=0.8)
    ax_gauge.plot([angle], [0.85], "o", color="white", markersize=8, zorder=5)
    ax_gauge.plot([angle, angle], [0, 0.85], color="white", lw=2)
    ax_gauge.set_ylim(0, 1.1)
    ax_gauge.set_xticks([])
    ax_gauge.set_yticks([])
    ax_gauge.set_thetamin(0)
    ax_gauge.set_thetamax(180)
    ax_gauge.text(0, -0.3, f"{score:.0f}", ha="center", va="center",
                  color=THEME["text"], fontsize=24, fontweight="bold",
                  transform=ax_gauge.transAxes)
    ax_gauge.text(0, -0.45, "Health Score", ha="center", va="center",
                  color=THEME["text_muted"], fontsize=8,
                  transform=ax_gauge.transAxes)
    ax_gauge.set_title(f"Engine: {report.engine_id}", color=THEME["text"],
                       fontsize=9, pad=6)

    # ── Fault Diagnoses Table ───────────────────────────────────────────────
    ax_faults = fig.add_subplot(gs[0:2, 1])
    _apply_theme(fig, ax_faults)
    ax_faults.axis("off")
    ax_faults.set_title("Top Diagnoses", fontsize=9, color=THEME["text"], pad=4)

    if report.fault_diagnoses:
        top5 = report.fault_diagnoses[:5]
        col_labels = ["Fault", "Conf.", "Sev.", "Max Ratio"]
        table_data = []
        cell_colors = []
        for d in top5:
            sev_color = (
                THEME["red"] if d["severity"] == "Critical"
                else THEME["yellow"] if d["severity"] == "Warning"
                else THEME["green"]
            )
            conf_str = f"{d['confidence']*100:.0f}%"
            ratio_str = f"×{d['max_amplitude_ratio']:.2f}"
            fname = d["fault_name"]
            if len(fname) > 30:
                fname = fname[:28] + "…"
            table_data.append([fname, conf_str, d["severity"], ratio_str])
            cell_colors.append([THEME["surface"]] * 3 + [THEME["surface"]])

        tbl = ax_faults.table(
            cellText=table_data,
            colLabels=col_labels,
            loc="center",
            cellLoc="left",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(7)
        for (row, col), cell in tbl.get_celld().items():
            cell.set_facecolor(THEME["surface"])
            cell.set_edgecolor(THEME["border"])
            cell.set_text_props(color=THEME["text"])
    else:
        ax_faults.text(
            0.5, 0.5, "No faults detected",
            ha="center", va="center",
            color=THEME["green"], fontsize=10,
            transform=ax_faults.transAxes,
        )

    # ── Anomaly Orders Bar ──────────────────────────────────────────────────
    ax_orders = fig.add_subplot(gs[1, 0])
    _apply_theme(fig, ax_orders)
    if report.anomalies:
        sorted_a = sorted(report.anomalies, key=lambda x: x.amplitude_ratio, reverse=True)[:10]
        orders = [f"{a.order}×" for a in sorted_a]
        ratios = [a.amplitude_ratio for a in sorted_a]
        colors = [THEME["red"] if a.severity == "Critical" else THEME["yellow"] for a in sorted_a]
        ax_orders.barh(orders[::-1], ratios[::-1], color=colors[::-1], height=0.5)
        ax_orders.axvline(1.0, color=THEME["text_muted"], lw=0.8, linestyle="--", alpha=0.5)
        ax_orders.set_xlabel("Amplitude Ratio vs Reference")
        ax_orders.set_title("Top Anomalous Orders", fontsize=8)
    else:
        ax_orders.text(0.5, 0.5, "All clear", ha="center", va="center",
                       color=THEME["green"], fontsize=10, transform=ax_orders.transAxes)
        ax_orders.set_title("Anomalous Orders", fontsize=8)

    # ── Recommendations ─────────────────────────────────────────────────────
    ax_rec = fig.add_subplot(gs[2, :])
    _apply_theme(fig, ax_rec)
    ax_rec.axis("off")
    ax_rec.set_title("Recommendations", fontsize=9, color=THEME["text"], pad=4,
                     loc="left")
    recs = report.recommendations[:4]
    if recs:
        rec_text = "\n".join(f"• {r[:110]}" for r in recs)
    else:
        rec_text = "Engine vibration within normal limits. Continue standard monitoring intervals."
    ax_rec.text(
        0.01, 0.85, rec_text,
        transform=ax_rec.transAxes,
        va="top", ha="left",
        color=THEME["text_muted"], fontsize=7,
        wrap=True, multialignment="left",
    )

    fig.suptitle(
        f"Diagnostic Report  ·  {report.engine_id}  ·  {report.sensor_location}  ·  Run: {report.run_id}",
        color=THEME["text"], fontsize=9, y=1.01,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
#  PLOT MANAGER  (saves / returns bytes)
# ─────────────────────────────────────────────────────────────────────────────

class PlotManager:
    """Handles saving figures to disk or returning PNG bytes."""

    def save(self, fig: Figure, path: Path, dpi: int = 150) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("Saved plot: %s", path)

    def to_bytes(self, fig: Figure, dpi: int = 150, fmt: str = "png") -> bytes:
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()
