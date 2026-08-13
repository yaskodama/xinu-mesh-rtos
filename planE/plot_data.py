#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plot_data.py —— results/sweep.csv を pgfplots 用の表に落とす。

レポートの図は「平均 1 本の折れ線」にしない。条件ごとに中央値と、
種のばらつき（最小・最大）を帯で描けるよう、分位点を列に出す。

  python3 plot_data.py            # → results/curves.dat, results/tails.dat
"""
import csv
import pathlib
import statistics

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "results"
CONDS = ('teacher', 'naive', 'P0', 'P1', 'P2', 'P3')


def load():
    with open(OUT / "sweep.csv") as f:
        rows = [{k: (float(v) if k != 'cond' else v) for k, v in r.items()}
                for r in csv.DictReader(f)]
    return rows


def main():
    rows = load()
    delays = sorted({int(r['delay_ms']) for r in rows})

    # ── 追従誤差 rms：中央値・最小・最大（種のばらつき） ───────────────────
    with open(OUT / "curves.dat", "w") as f:
        cols = ["delay"]
        for c in CONDS:
            cols += ["%s_med" % c, "%s_lo" % c, "%s_hi" % c]
        f.write(" ".join(cols) + "\n")
        for d in delays:
            vals = ["%d" % d]
            for c in CONDS:
                v = [r['rms'] for r in rows
                     if int(r['delay_ms']) == d and r['cond'] == c]
                if not v:
                    vals += ["nan"] * 3
                else:
                    vals += ["%.4f" % statistics.median(v),
                             "%.4f" % min(v), "%.4f" % max(v)]
            f.write(" ".join(vals) + "\n")

    # ── 分布の裾：p50/p90/p99/max（条件ごとに 1 ファイルぶんの列） ─────────
    with open(OUT / "tails.dat", "w") as f:
        f.write("delay cond p50 p90 p99 max\n")
        for d in delays:
            for c in CONDS:
                sel = [r for r in rows if int(r['delay_ms']) == d and r['cond'] == c]
                if not sel:
                    continue
                f.write("%d %s %.4f %.4f %.4f %.4f\n" % (
                    d, c,
                    statistics.median([r['p50'] for r in sel]),
                    statistics.median([r['p90'] for r in sel]),
                    statistics.median([r['p99'] for r in sel]),
                    max(r['max'] for r in sel)))
    print("wrote %s and %s" % (OUT / "curves.dat", OUT / "tails.dat"))


if __name__ == "__main__":
    main()
