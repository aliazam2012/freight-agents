"""freight-forecast: run the backtest and write its report, or print a stored forecast."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from freight_agents.volume_forecast.report import write
from freight_agents.volume_forecast.runs import FORECAST_DAYS, RunStore, build_run

DEFAULT_RUNS = Path("var/forecast/runs")
DEFAULT_REPORTS = Path("apps/volume-forecast/reports")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="freight-forecast")
    commands = parser.add_subparsers(dest="command", required=True)

    backtest = commands.add_parser("backtest", help="backtest every model and write the report")
    backtest.add_argument("--seed", type=int, default=7)
    backtest.add_argument("--origins", type=int, default=8)
    backtest.add_argument("--day", default=date.today().isoformat(), help="report date")
    backtest.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)

    forecast = commands.add_parser("forecast", help="print a lane's forecast from a stored run")
    forecast.add_argument("--lane", required=True)
    forecast.add_argument("--days", type=int, default=14)
    forecast.add_argument("--model", help="defaults to the run's best model")
    forecast.add_argument("--run", default="latest", help="run id, or latest")

    for sub in (backtest, forecast):
        sub.add_argument("--runs", type=Path, default=DEFAULT_RUNS, help="run store directory")

    args = parser.parse_args(argv)
    store = RunStore(args.runs)

    if args.command == "backtest":
        if args.origins < 2:
            parser.error("--origins needs at least 2: one half calibrates, the other is checked")
        run = build_run(seed=args.seed, count=args.origins, day=args.day)
        store.save(run)
        path = write(run, args.reports)
        print(f"run {run['run_id']}  best model {run['best_model']}")
        for row in sorted(run["backtest"]["overall"], key=lambda r: r["wape"]):
            print(f"  {row['model']:<18} WAPE {row['wape']:.1%}  MASE {row['mase']:.2f}")
        print(f"report: {path}")
        return 0

    try:
        run = store.load(args.run)
    except (FileNotFoundError, ValueError):
        print(f"no run {args.run!r} in {args.runs}; run `freight-forecast backtest` first")
        return 2
    if not 1 <= args.days <= FORECAST_DAYS:
        print(f"--days must be between 1 and {FORECAST_DAYS}", file=sys.stderr)
        return 2
    model = args.model or run["best_model"]
    rows = [r for r in run["forecast"] if r["lane"] == args.lane and r["model"] == model]
    if not rows:
        lanes = sorted({r["lane"] for r in run["forecast"]})
        print(f"no forecast for lane {args.lane!r}; lanes: {', '.join(lanes)}", file=sys.stderr)
        return 2
    print(f"{args.lane}, {model}, run {run['run_id']} (data through {run['data']['end']})")
    print(f"{'date':<11} {'forecast':>8}  {'80% range':>13}  {'95% range':>13}")
    for r in sorted(rows, key=lambda r: r["date"])[: args.days]:
        note = "  holiday" if r["holiday"] else ""
        print(
            f"{r['date']:<11} {r['forecast']:>8.0f}  {r['lo_80']:>6.0f}-{r['hi_80']:<6.0f}"
            f"  {r['lo_95']:>6.0f}-{r['hi_95']:<6.0f}{note}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
