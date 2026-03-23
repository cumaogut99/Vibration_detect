"""
Main CLI entrypoint for the Aircraft Vibration Analyzer.

Usage examples:

  # Analyze one engine vs a reference
  python main.py analyze \\
      --ref  data/ref_engine.csv       --ref-id  REF-001 \\
      --meas data/engine_42.csv        --meas-id ENG-042 \\
      --sensor front_bearing \\
      --out   reports/

  # Analyze a whole fleet (all CSV files in a folder)
  python main.py fleet \\
      --ref  data/ref_engine.csv       --ref-id  REF-001 \\
      --fleet-dir data/fleet/          --sensor  front_bearing \\
      --out   reports/

  # Generate demo synthetic data and run a full analysis
  python main.py demo --out reports/
"""

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vibration_analyzer",
        description="Aircraft piston engine vibration analysis tool",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── analyze ────────────────────────────────────────────────────────────
    a = sub.add_parser("analyze", help="Analyze one engine vs reference")
    a.add_argument("--ref",       required=True, help="Reference engine data file")
    a.add_argument("--ref-id",    default="REF",  help="Reference engine ID")
    a.add_argument("--meas",      required=True, help="Measured engine data file")
    a.add_argument("--meas-id",   default="ENG",  help="Measured engine ID")
    a.add_argument("--sensor",    default="front_bearing", help="Sensor location label")
    a.add_argument("--run-id",    default="RUN-001")
    a.add_argument("--out",       default="reports/", help="Output directory")
    a.add_argument("--freq-max",  type=float, default=3000.0, help="Max frequency for waterfall plot")
    a.add_argument("--no-html",   action="store_true")

    # ── fleet ──────────────────────────────────────────────────────────────
    f = sub.add_parser("fleet", help="Analyze all engines in a directory vs reference")
    f.add_argument("--ref",       required=True, help="Reference engine data file")
    f.add_argument("--ref-id",    default="REF")
    f.add_argument("--fleet-dir", required=True, help="Directory with engine data files")
    f.add_argument("--sensor",    default="front_bearing")
    f.add_argument("--out",       default="reports/")
    f.add_argument("--freq-max",  type=float, default=3000.0)

    # ── demo ──────────────────────────────────────────────────────────────
    d = sub.add_parser("demo", help="Run with synthetic demo data")
    d.add_argument("--out", default="reports/")

    return p


def cmd_analyze(args) -> None:
    from importers import ImporterFactory
    from analysis import build_default_analyzer
    from plots import PlotManager, plot_waterfall, plot_order_comparison, plot_diagnostic_card
    from reports import HTMLReportGenerator

    factory = ImporterFactory()
    analyzer = build_default_analyzer()
    pm = PlotManager()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ref_run = factory.load(Path(args.ref), args.ref_id, "REF", args.sensor, is_reference=True)
    meas_run = factory.load(Path(args.meas), args.meas_id, args.run_id, args.sensor)

    report = analyzer.analyze(meas_run, ref_run)

    logger.info("Health score: %.1f | Anomalies: %d | Faults: %d",
                report.overall_health_score, len(report.anomalies), len(report.fault_diagnoses))

    # Extract order data for plots
    from analysis import OrderExtractor
    from engine_config import ORDER_DEFINITIONS, MANDATORY_MONITOR_ORDERS
    extractor = OrderExtractor()
    orders = list(ORDER_DEFINITIONS.keys())
    order_data = extractor.extract(meas_run, orders)
    ref_order_data = extractor.extract(ref_run, orders)

    # Plots
    wf_fig   = plot_waterfall(meas_run, freq_max=args.freq_max)
    ord_fig  = plot_order_comparison(order_data, ref_order_data, report.anomalies)
    card_fig = plot_diagnostic_card(report)

    pm.save(wf_fig,   out / f"{args.meas_id}_waterfall.png")
    pm.save(ord_fig,  out / f"{args.meas_id}_orders.png")
    pm.save(card_fig, out / f"{args.meas_id}_diagnostic_card.png")

    if not args.no_html:
        gen = HTMLReportGenerator()
        # Regenerate figs for embedding (already closed above, recreate)
        wf_fig2   = plot_waterfall(meas_run, freq_max=args.freq_max)
        ord_fig2  = plot_order_comparison(order_data, ref_order_data, report.anomalies)
        gen.generate(report, wf_fig2, ord_fig2, output_path=out / f"{args.meas_id}_report.html")

    logger.info("Done. Outputs in: %s", out)


def cmd_fleet(args) -> None:
    from importers import ImporterFactory
    from analysis import build_default_analyzer, OrderExtractor
    from plots import PlotManager, plot_waterfall, plot_order_comparison, plot_engine_health_comparison
    from reports import HTMLReportGenerator, FleetReportGenerator
    from engine_config import ORDER_DEFINITIONS

    factory = ImporterFactory()
    analyzer = build_default_analyzer()
    extractor = OrderExtractor()
    pm = PlotManager()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ref_run = factory.load(Path(args.ref), args.ref_id, "REF", args.sensor, is_reference=True)

    fleet_dir = Path(args.fleet_dir)
    engine_files = [
        f for f in fleet_dir.iterdir()
        if f.suffix.lower() in {".csv", ".npz", ".txt", ".dat"}
    ]

    logger.info("Found %d engine files in fleet directory", len(engine_files))
    orders = list(ORDER_DEFINITIONS.keys())
    reports = {}
    html_gen = HTMLReportGenerator()

    for ef in engine_files:
        eid = ef.stem
        try:
            run = factory.load(ef, eid, "RUN-001", args.sensor)
            report = analyzer.analyze(run, ref_run)
            reports[eid] = report

            order_data = extractor.extract(run, orders)
            ref_order_data = extractor.extract(ref_run, orders)

            wf_fig  = plot_waterfall(run, freq_max=args.freq_max)
            ord_fig = plot_order_comparison(order_data, ref_order_data, report.anomalies)
            pm.save(wf_fig,  out / f"{eid}_waterfall.png")
            pm.save(ord_fig, out / f"{eid}_orders.png")

            # Regenerate for HTML embedding
            wf_fig2  = plot_waterfall(run, freq_max=args.freq_max)
            ord_fig2 = plot_order_comparison(order_data, ref_order_data, report.anomalies)
            html_gen.generate(report, wf_fig2, ord_fig2, output_path=out / f"{eid}_report.html")

            logger.info("  %-20s  score=%.0f  anomalies=%d", eid, report.overall_health_score, len(report.anomalies))
        except Exception as exc:
            logger.error("  Failed to process %s: %s", eid, exc)

    if reports:
        from plots import plot_engine_health_comparison
        fleet_fig = plot_engine_health_comparison(reports, args.ref_id)
        pm.save(fleet_fig, out / "fleet_health.png")

        fleet_fig2 = plot_engine_health_comparison(reports, args.ref_id)
        fleet_gen = FleetReportGenerator()
        fleet_gen.generate(reports, args.ref_id, fleet_fig2, output_path=out / "fleet_report.html")

    logger.info("Fleet analysis complete. Outputs in: %s", out)


def cmd_demo(args) -> None:
    """Generate synthetic demo data and run the full pipeline."""
    import numpy as np
    from analysis import build_default_analyzer, OrderExtractor
    from plots import (PlotManager, plot_waterfall, plot_order_comparison,
                       plot_engine_health_comparison, plot_diagnostic_card)
    from reports import HTMLReportGenerator, FleetReportGenerator
    from models import DataType, EngineRun
    from engine_config import ORDER_DEFINITIONS

    logger.info("Generating synthetic demo data …")

    rpm_values = np.linspace(1800, 2700, 50)
    frequencies = np.linspace(1, 3000, 600)
    shaft_hz = rpm_values / 60.0

    BASE_AMPS = {1.0: 0.05, 2.0: 0.08, 0.5: 0.02, 4.0: 0.03, 29.0: 0.015,
                 22.0: 0.010, 14.0: 0.008, 6.0: 0.012, 8.0: 0.010}

    def build_spectrum(rpm_arr, fault_orders=None, noise_level=0.0003):
        n_rpm = len(rpm_arr)
        n_freq = len(frequencies)
        amps = np.random.exponential(noise_level, (n_rpm, n_freq))
        shaft = rpm_arr / 60.0
        orders_present = list(ORDER_DEFINITIONS.keys())
        for o in orders_present:
            for i, sf in enumerate(shaft):
                target = o * sf
                mask = np.abs(frequencies - target) < target * 0.012
                base_amp = BASE_AMPS.get(o, 0.004)
                amps[i, mask] += base_amp * (1.0 + np.random.uniform(-0.05, 0.05))
        if fault_orders:
            for fo, multiplier in fault_orders.items():
                for i, sf in enumerate(shaft):
                    target = fo * sf
                    mask = np.abs(frequencies - target) < target * 0.012
                    amps[i, mask] *= multiplier
        return amps

    ref_amps = build_spectrum(rpm_values)
    ref_run = EngineRun(
        engine_id="REF-001", run_id="BASELINE", sensor_location="front_bearing",
        data_type=DataType.FFT_WATERFALL, rpm_values=rpm_values,
        frequencies=frequencies, amplitudes=ref_amps, is_reference=True,
    )

    engines = {
        "ENG-042": {29.0: 2.8, 58.0: 1.8},   # Magneto gear wear
        "ENG-043": {1.0: 2.2, 2.0: 1.6},      # Imbalance
        "ENG-044": {0.5: 2.5, 2.0: 2.0},      # Combustion anomaly
        "ENG-045": {},                          # Healthy
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    analyzer = build_default_analyzer()
    extractor = OrderExtractor()
    pm = PlotManager()
    reports = {}
    html_gen = HTMLReportGenerator()
    orders = list(ORDER_DEFINITIONS.keys())

    for eid, faults in engines.items():
        amps = build_spectrum(rpm_values, fault_orders=faults)
        run = EngineRun(
            engine_id=eid, run_id="RUN-001", sensor_location="front_bearing",
            data_type=DataType.FFT_WATERFALL, rpm_values=rpm_values,
            frequencies=frequencies, amplitudes=amps,
        )
        report = analyzer.analyze(run, ref_run)
        reports[eid] = report

        order_data    = extractor.extract(run, orders)
        ref_order_data = extractor.extract(ref_run, orders)

        wf_fig  = plot_waterfall(run)
        ord_fig = plot_order_comparison(order_data, ref_order_data, report.anomalies)
        card_fig = plot_diagnostic_card(report)

        pm.save(wf_fig,   out / f"{eid}_waterfall.png")
        pm.save(ord_fig,  out / f"{eid}_orders.png")
        pm.save(card_fig, out / f"{eid}_card.png")

        wf_fig2  = plot_waterfall(run)
        ord_fig2 = plot_order_comparison(order_data, ref_order_data, report.anomalies)
        html_gen.generate(report, wf_fig2, ord_fig2, output_path=out / f"{eid}_report.html")

        logger.info("  %-10s  score=%.0f  anomalies=%d  faults=%d",
                    eid, report.overall_health_score, len(report.anomalies), len(report.fault_diagnoses))

    fleet_fig = plot_engine_health_comparison(reports, "REF-001")
    pm.save(fleet_fig, out / "fleet_health.png")
    fleet_fig2 = plot_engine_health_comparison(reports, "REF-001")
    FleetReportGenerator().generate(reports, "REF-001", fleet_fig2, output_path=out / "fleet_report.html")

    logger.info("Demo complete. Open %s/fleet_report.html to view results.", out)


def _launch_gui() -> None:
    """PySide6 arayüzünü başlatır."""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError:
        logger.error(
            "PySide6 bulunamadı. Kurmak için: pip install PySide6\n"
            "Arayüzsüz çalıştırmak için: python main.py demo --out reports/"
        )
        sys.exit(1)

    # ui_main modülünü import et — ui_main.py ile aynı klasörde olmalı
    try:
        import ui_main
    except ImportError as e:
        logger.error("ui_main.py bulunamadı: %s", e)
        sys.exit(1)

    ui_main.main()


def main() -> None:
    # Argüman yoksa → GUI aç
    if len(sys.argv) == 1:
        logger.info("Arayüz başlatılıyor…")
        _launch_gui()
        return

    # Argüman varsa → CLI modu
    parser = _build_parser()
    args = parser.parse_args()

    dispatch = {
        "analyze": cmd_analyze,
        "fleet":   cmd_fleet,
        "demo":    cmd_demo,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
