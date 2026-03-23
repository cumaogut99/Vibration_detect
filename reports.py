"""
Report generation layer.
Produces HTML diagnostic reports combining plots + structured text.
"""

import base64
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from models import DiagnosticReport, EngineRun, OrderAmplitude
from engine_config import ORDER_DEFINITIONS, Severity, ALERT_THRESHOLDS

logger = logging.getLogger(__name__)

_SEVERITY_BADGE = {
    "Critical": '<span style="background:#f85149;color:#fff;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:700">CRITICAL</span>',
    "Warning":  '<span style="background:#d29922;color:#fff;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:700">WARNING</span>',
    "Info":     '<span style="background:#3fb950;color:#fff;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:700">OK</span>',
}


def _fig_to_b64(fig) -> str:
    """Convert matplotlib Figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _health_color(score: float) -> str:
    if score >= 80:
        return "#3fb950"
    if score >= 60:
        return "#d29922"
    return "#f85149"


class HTMLReportGenerator:
    """Generates a self-contained HTML diagnostic report."""

    def generate(
        self,
        report: DiagnosticReport,
        waterfall_fig=None,
        order_fig=None,
        output_path: Optional[Path] = None,
    ) -> str:
        """
        Build HTML string. Optionally write to output_path.
        """
        wf_img = f'<img src="data:image/png;base64,{_fig_to_b64(waterfall_fig)}" style="width:100%;border-radius:6px">' if waterfall_fig else ""
        ord_img = f'<img src="data:image/png;base64,{_fig_to_b64(order_fig)}" style="width:100%;border-radius:6px">' if order_fig else ""

        anomaly_rows = ""
        for a in sorted(report.anomalies, key=lambda x: -x.amplitude_ratio):
            odef = ORDER_DEFINITIONS.get(a.order)
            order_name = odef.name if odef else f"Order {a.order}"
            badge = _SEVERITY_BADGE.get(a.severity, "")
            anomaly_rows += f"""
            <tr>
              <td>{a.order:.1f}×</td>
              <td>{order_name}</td>
              <td>{a.rpm:.0f} RPM</td>
              <td>{a.frequency_hz:.1f} Hz</td>
              <td>{a.measured_amplitude:.4f}</td>
              <td>{a.reference_amplitude:.4f}</td>
              <td><b>×{a.amplitude_ratio:.2f}</b></td>
              <td>{badge}</td>
            </tr>"""

        fault_rows = ""
        for d in report.fault_diagnoses[:8]:
            badge = _SEVERITY_BADGE.get(d["severity"], "")
            primary_str = ", ".join(f"{o}×" for o in d["primary_orders_hit"])
            fault_rows += f"""
            <tr>
              <td><b>{d['fault_name']}</b></td>
              <td>{d['category']}</td>
              <td>{int(d['confidence']*100)}%</td>
              <td>{badge}</td>
              <td>{primary_str}</td>
              <td style="font-size:11px;color:#8b949e">{d['description'][:120]}…</td>
            </tr>"""

        rec_items = "".join(f"<li>{r}</li>" for r in report.recommendations) or "<li>No specific recommendations.</li>"
        score_color = _health_color(report.overall_health_score)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

        if not report.anomalies:
            anomaly_section = "<p style='color:#8b949e'>No anomalies detected.</p>"
        else:
            anomaly_section = (
                "<table><thead><tr>"
                "<th>Order</th><th>Name</th><th>RPM</th><th>Freq (Hz)</th>"
                "<th>Measured</th><th>Reference</th><th>Ratio</th><th>Severity</th>"
                "</tr></thead><tbody>" + anomaly_rows + "</tbody></table>"
            )

        if not report.fault_diagnoses:
            fault_section = "<p style='color:#8b949e'>No fault signatures matched.</p>"
        else:
            fault_section = (
                "<table><thead><tr>"
                "<th>Fault</th><th>Category</th><th>Confidence</th>"
                "<th>Severity</th><th>Orders Hit</th><th>Description</th>"
                "</tr></thead><tbody>" + fault_rows + "</tbody></table>"
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vibration Diagnostic Report — {report.engine_id}</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 13px; padding: 24px; }}
  h1 {{ font-size: 18px; color: var(--accent); margin-bottom: 4px; }}
  h2 {{ font-size: 14px; color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 6px; margin: 24px 0 12px; }}
  .meta {{ color: var(--muted); font-size: 11px; margin-bottom: 20px; }}
  .header-row {{ display: flex; align-items: center; gap: 24px; margin-bottom: 24px; flex-wrap: wrap; }}
  .score-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px 24px; text-align: center; }}
  .score-num {{ font-size: 42px; font-weight: 700; color: {score_color}; }}
  .score-label {{ color: var(--muted); font-size: 11px; }}
  .summary-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 18px; flex: 1; min-width: 280px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface); border-radius: 6px; overflow: hidden; }}
  th {{ background: #21262d; color: var(--muted); font-size: 11px; font-weight: 600; padding: 8px 10px; text-align: left; }}
  td {{ border-top: 1px solid var(--border); padding: 7px 10px; color: var(--text); vertical-align: middle; }}
  tr:hover td {{ background: #1c2128; }}
  .rec-list {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 14px 18px; }}
  .rec-list li {{ margin: 6px 0 6px 16px; color: var(--muted); line-height: 1.5; }}
  .plot-wrap {{ margin: 12px 0; }}
  footer {{ margin-top: 32px; color: var(--muted); font-size: 10px; border-top: 1px solid var(--border); padding-top: 12px; }}
</style>
</head>
<body>

<h1>✈ Vibration Diagnostic Report</h1>
<div class="meta">
  Engine: <b style="color:var(--accent)">{report.engine_id}</b> &nbsp;|&nbsp;
  Run: {report.run_id} &nbsp;|&nbsp;
  Sensor: {report.sensor_location} &nbsp;|&nbsp;
  Reference: {report.reference_engine_id or "N/A"} &nbsp;|&nbsp;
  Generated: {ts}
</div>

<div class="header-row">
  <div class="score-box">
    <div class="score-num">{report.overall_health_score:.0f}</div>
    <div class="score-label">Health Score / 100</div>
  </div>
  <div class="summary-box">
    <div style="color:var(--muted);font-size:11px;margin-bottom:6px">SUMMARY</div>
    <div style="line-height:1.6">{report.summary}</div>
  </div>
</div>

<h2>FFT Waterfall</h2>
<div class="plot-wrap">{wf_img}</div>

<h2>Order Amplitude Comparison</h2>
<div class="plot-wrap">{ord_img}</div>

<h2>Detected Anomalies ({len(report.anomalies)})</h2>
{anomaly_section}

<h2>Fault Diagnoses ({len(report.fault_diagnoses)})</h2>
{fault_section}

<h2>Recommendations</h2>
<div class="rec-list"><ul>{rec_items}</ul></div>

<footer>
  Aircraft Vibration Analyzer &nbsp;·&nbsp; 4-stroke 4-cylinder piston engine &nbsp;·&nbsp;
  Engine config: engine_config.py &nbsp;·&nbsp; Report generated {ts}
</footer>
</body>
</html>"""

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html, encoding="utf-8")
            logger.info("HTML report saved: %s", output_path)

        return html


class FleetReportGenerator:
    """Generates a fleet-level overview HTML page comparing all engines."""

    def generate(
        self,
        reports: Dict[str, DiagnosticReport],
        reference_id: str,
        fleet_plot_fig=None,
        output_path: Optional[Path] = None,
    ) -> str:
        fleet_img = f'<img src="data:image/png;base64,{_fig_to_b64(fleet_plot_fig)}" style="width:100%;border-radius:6px">' if fleet_plot_fig else ""

        rows = ""
        for eid, r in sorted(reports.items(), key=lambda x: x[1].overall_health_score):
            score_color = _health_color(r.overall_health_score)
            worst = "Critical" if any(d["severity"] == "Critical" for d in r.fault_diagnoses) \
                    else "Warning" if r.fault_diagnoses else "OK"
            badge = _SEVERITY_BADGE.get(worst, "")
            top_fault = r.fault_diagnoses[0]["fault_name"] if r.fault_diagnoses else "—"
            n_anomalies = len(r.anomalies)
            rows += f"""
            <tr>
              <td><b>{eid}</b></td>
              <td style="color:{score_color};font-weight:700">{r.overall_health_score:.0f}</td>
              <td>{badge}</td>
              <td>{n_anomalies}</td>
              <td>{top_fault}</td>
              <td style="font-size:11px;color:#8b949e">{r.summary[:100]}</td>
            </tr>"""

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Fleet Vibration Report</title>
<style>
  :root {{ --bg:#0d1117; --surface:#161b22; --border:#30363d; --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; font-size:13px; padding:24px; }}
  h1 {{ font-size:18px; color:var(--accent); margin-bottom:4px; }}
  .meta {{ color:var(--muted); font-size:11px; margin-bottom:20px; }}
  h2 {{ font-size:14px; border-bottom:1px solid var(--border); padding-bottom:6px; margin:24px 0 12px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--surface); border-radius:6px; overflow:hidden; }}
  th {{ background:#21262d; color:var(--muted); font-size:11px; padding:8px 10px; text-align:left; }}
  td {{ border-top:1px solid var(--border); padding:7px 10px; vertical-align:middle; }}
  tr:hover td {{ background:#1c2128; }}
</style>
</head>
<body>
<h1>✈ Fleet Vibration Overview</h1>
<div class="meta">Reference engine: <b style="color:var(--accent)">{reference_id}</b> &nbsp;|&nbsp; {len(reports)} engines &nbsp;|&nbsp; {ts}</div>

<h2>Fleet Health Overview</h2>
{fleet_img}

<h2>Engine Summary Table</h2>
<table>
  <thead>
    <tr><th>Engine</th><th>Score</th><th>Status</th><th>Anomalies</th><th>Top Fault</th><th>Summary</th></tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
</body>
</html>"""

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html, encoding="utf-8")
            logger.info("Fleet report saved: %s", output_path)
        return html
