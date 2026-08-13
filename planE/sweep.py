#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep.py —— 条件を掃引し、6 条件を同じ軌道で比べる。

  teacher : 遅延ゼロの理想制御（下界）
  naive   : 最後に知った目標をそのまま指令（学習なしの基準線）
  P0 / P1 : 模倣学習（齢なし／齢あり）
  P2 / P3 : 強化学習 CEM（齢なし／齢あり）

掃引できる軸は 3 つ。**変化させた軸が横軸**になる。
  DELAYS  : 輸送遅延 ms（既定 0,50,100,200,400,800）
  JITTERS : 文脈生成のジッタ ±ms（既定 0）
  PDROPS  : 文脈の脱落率（メールボックス溢れ。既定 0）

**しきい値は先に宣言する**（後から都合よく選ばない）:
  TOL   = 2.0 deg —— 制御として許容する追従誤差。可動範囲 50 deg p-p の 4 %
  d*_IL = P1 の rms が TOL を超える最小の点
  d*_RL = P3 の rms 中央値が P1 の rms 中央値を下回る最小の点

例:
  DELAYS=0,50,100,200,400,800 SEEDS=5 python3 sweep.py
  DELAYS=100 JITTERS=0,25,50,100,200 SEEDS=5 OUT=sweep_jitter python3 sweep.py
"""
import csv
import os
import pathlib
import statistics
import time

from env import evaluate, make_episodes
from train import train_cem, train_imitation

AHEAD = os.environ.get("AHEAD", "nominal")   # â の作り方: nominal（OS が出せる）/ oracle

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "results"

TOL = 2.0
EVAL_H = 4.0
TRAIN_H = 4.0
CEM_H = 2.5

BC = dict(epochs=40, stride=2, dagger=2)
CEM = dict(pop=40, gens=30)


def run(points, seeds, name):
    OUT.mkdir(exist_ok=True)
    rows = []
    t0 = time.time()
    for (d, j, pd) in points:
        base = dict(delay_ms=d, jitter_ms=j, p_drop=pd)
        kw = dict(n_ep=3, horizon=EVAL_H, jitter=j / 1000.0, p_drop=pd,
                  ahead_mode=AHEAD)
        ev = make_episodes(d / 1000.0, seed_base=1000, **kw)
        tr = make_episodes(d / 1000.0, seed_base=2000, **kw)
        for cond in ('teacher', 'naive'):
            m = evaluate(cond, ev, horizon=EVAL_H)
            rows.append(dict(cond=cond, seed=-1, **base, **m))
            print("d=%4d j=%4d p=%.2f %-7s rms=%7.3f p99=%7.3f max=%7.3f" %
                  (d, j, pd, cond, m['rms'], m['p99'], m['max']), flush=True)
        for seed in range(seeds):
            for cond, use_age, kind in (('P0', False, 'bc'), ('P1', True, 'bc'),
                                        ('P2', False, 'cem'), ('P3', True, 'cem')):
                if kind == 'bc':
                    p = train_imitation(use_age, tr, seed=seed, horizon=TRAIN_H, **BC)
                else:
                    p = train_cem(use_age, tr, seed=seed, horizon=CEM_H, **CEM)
                m = evaluate('policy', ev, policy=p, horizon=EVAL_H)
                rows.append(dict(cond=cond, seed=seed, **base, **m))
                print("d=%4d j=%4d p=%.2f %-7s rms=%7.3f p99=%7.3f max=%7.3f "
                      "seed=%d (%.0fs)" % (d, j, pd, cond, m['rms'], m['p99'],
                                           m['max'], seed, time.time() - t0),
                      flush=True)
    with open(OUT / (name + ".csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


def summarize(rows, points, xkey, name):
    xs = [p[{'delay_ms': 0, 'jitter_ms': 1, 'p_drop': 2}[xkey]] for p in points]
    unit = {'delay_ms': ' ms', 'jitter_ms': ' ms', 'p_drop': ''}[xkey]

    def med(x, c, key='rms'):
        v = [r[key] for r in rows if r[xkey] == x and r['cond'] == c]
        return statistics.median(v) if v else float('nan')

    def wins(x, a, b):
        pa = {r['seed']: r['rms'] for r in rows if r[xkey] == x and r['cond'] == a}
        pb = {r['seed']: r['rms'] for r in rows if r[xkey] == x and r['cond'] == b}
        ks = sorted(set(pa) & set(pb))
        return sum(1 for k in ks if pb[k] < pa[k]), len(ks)

    L = []
    L.append("横軸 = %s\n" % xkey)
    L.append("| %s | teacher | naive | P0 模倣・齢なし | P1 模倣・齢あり | "
             "P2 RL・齢なし | P3 RL・齢あり |" % xkey)
    L.append("|---:|---:|---:|---:|---:|---:|---:|")
    for x in xs:
        L.append("| %g%s | %.3f | %.3f | %.3f | %.3f | %.3f | %.3f |" %
                 (x, unit, med(x, 'teacher'), med(x, 'naive'), med(x, 'P0'),
                  med(x, 'P1'), med(x, 'P2'), med(x, 'P3')))
    d_il = next((x for x in xs if med(x, 'P1') > TOL), None)
    d_rl = next((x for x in xs if med(x, 'P3') < med(x, 'P1')), None)
    L.append("")
    L.append("d*_IL（P1 の rms が %.1f deg を超える最小の点）= %s" %
             (TOL, ("%g%s" % (d_il, unit)) if d_il is not None else "掃引範囲では未到達"))
    L.append("d*_RL（P3 が P1 を下回る最小の点）= %s" %
             (("%g%s" % (d_rl, unit)) if d_rl is not None else "掃引範囲では未到達"))
    L.append("")
    L.append("齢の効果。比が 1 未満なら齢ありが良い。**勝った種の数を併記する** "
             "（中央値だけでは、ばらつきに埋もれた差を見分けられない）。")
    L.append("")
    L.append("| %s | P1/P0（模倣） | 勝ち | P3/P2（強化学習） | 勝ち |" % xkey)
    L.append("|---:|---:|:--:|---:|:--:|")
    for x in xs:
        a, b = med(x, 'P0'), med(x, 'P1')
        c, e = med(x, 'P2'), med(x, 'P3')
        w1 = wins(x, 'P0', 'P1')
        w2 = wins(x, 'P2', 'P3')
        L.append("| %g%s | %.3f | %d/%d | %.3f | %d/%d |" %
                 (x, unit, b / a if a else 0, w1[0], w1[1],
                  e / c if c else 0, w2[0], w2[1]))
    txt = "\n".join(L)
    (OUT / (name + "_summary.md")).write_text(txt + "\n", encoding="utf-8")
    return txt


if __name__ == "__main__":
    def lst(k, dflt):
        return [float(x) for x in os.environ.get(k, dflt).split(",")]

    delays = lst("DELAYS", "0,50,100,200,400,800")
    jitters = lst("JITTERS", "0")
    pdrops = lst("PDROPS", "0")
    seeds = int(os.environ.get("SEEDS", "5"))
    name = os.environ.get("OUT", "sweep")
    points = [(d, j, p) for d in delays for j in jitters for p in pdrops]
    xkey = ('jitter_ms' if len(jitters) > 1 else
            'p_drop' if len(pdrops) > 1 else 'delay_ms')
    rows = run(points, seeds, name)
    print()
    print(summarize(rows, points, xkey, name))
