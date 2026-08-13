#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ablate.py —— 齢 $a$ と「次が届くまでの残り時間」$\\hat a$ を分離して測る。

実験1・実験2 は両方を同時に与えていたので、**案E に固有の入力である $\\hat a$ が
単独でどれだけ効くか**が言えなかった。ここを埋める。

  A0 : どちらも無し（= 実験1・2 の P0）
  A1 : $a$ のみ（案D が渡すぶん）
  A2 : $\\hat a$ のみ（案E に固有。OS の tickless タイマだけが答えられる値）
  A3 : 両方（= 実験1・2 の P1）

容量は 4 条件とも同一（端子は常に 8 本、切るのは値だけ）。学習は模倣のみ
（実験1・2 で強化学習 CEM には齢の効果が出ないことが分かっているため、
ここに CEM を足しても $\\hat a$ の情報価値は測れない）。

**予測（結果を見る前に書く）**
  ① ジッタ軸では A1 が主役。A2 単独の効果は A1 より小さい。
  ② 脱落（p_drop）が増えると **A2 の効果が落ちる**。次の到着時刻の予告が外れるため。
     A1 は落ちない（齢は実測値なので脱落しても正しい）。
  ③ A3 は A1 と A2 の和より小さい（情報が重複しているため）。

  JITTERS=0,50,100,200 SEEDS=5 python3 ablate.py
  PDROPS=0,0.1,0.3 JITTERS=100 SEEDS=5 OUT=ablate_drop python3 ablate.py
"""
import csv
import os
import pathlib
import statistics
import time

from env import evaluate, make_episodes
from sweep import BC, EVAL_H, TRAIN_H
from train import train_imitation

AHEAD = os.environ.get("AHEAD", "nominal")   # â の作り方: nominal（OS が出せる）/ oracle

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "results"

CONDS = (('A0', (False, False)), ('A1', (True, False)),
         ('A2', (False, True)), ('A3', (True, True)))
LABEL = {'A0': 'なし', 'A1': 'a のみ', 'A2': 'â のみ', 'A3': '両方'}


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
        m = evaluate('naive', ev, horizon=EVAL_H)
        rows.append(dict(cond='naive', seed=-1, **base, **m))
        print("d=%4d j=%4d p=%.2f naive rms=%7.3f" % (d, j, pd, m['rms']), flush=True)
        for seed in range(seeds):
            for cond, mask in CONDS:
                p = train_imitation(mask, tr, seed=seed, horizon=TRAIN_H, **BC)
                m = evaluate('policy', ev, policy=p, horizon=EVAL_H)
                rows.append(dict(cond=cond, seed=seed, **base, **m))
                print("d=%4d j=%4d p=%.2f %-3s(%-5s) rms=%7.3f p99=%7.3f seed=%d (%.0fs)"
                      % (d, j, pd, cond, LABEL[cond], m['rms'], m['p99'], seed,
                         time.time() - t0), flush=True)
    with open(OUT / (name + ".csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


def summarize(rows, points, xkey, name):
    xs = [p[{'delay_ms': 0, 'jitter_ms': 1, 'p_drop': 2}[xkey]] for p in points]
    unit = {'delay_ms': ' ms', 'jitter_ms': ' ms', 'p_drop': ''}[xkey]

    def per(x, c):
        return {r['seed']: r['rms'] for r in rows if r[xkey] == x and r['cond'] == c}

    def med(x, c):
        v = list(per(x, c).values())
        return statistics.median(v) if v else float('nan')

    L = ["横軸 = %s\n" % xkey]
    L.append("| %s | naive | A0 なし | A1 a のみ | A2 â のみ | A3 両方 |" % xkey)
    L.append("|---:|---:|---:|---:|---:|---:|")
    for x in xs:
        L.append("| %g%s | %.3f | %.3f | %.3f | %.3f | %.3f |" %
                 (x, unit, med(x, 'naive'), med(x, 'A0'), med(x, 'A1'),
                  med(x, 'A2'), med(x, 'A3')))
    L.append("")
    L.append("A0 を基準にした改善率（負が良い）と、A0 に勝った種の数:")
    L.append("")
    L.append("| %s | A1 a のみ | 勝ち | A2 â のみ | 勝ち | A3 両方 | 勝ち |" % xkey)
    L.append("|---:|---:|:--:|---:|:--:|---:|:--:|")
    for x in xs:
        cells = []
        b = per(x, 'A0')
        for c in ('A1', 'A2', 'A3'):
            a = per(x, c)
            ks = sorted(set(a) & set(b))
            w = sum(1 for k in ks if a[k] < b[k])
            cells.append("%+.1f %%| %d/%d " % (100 * (med(x, c) / med(x, 'A0') - 1), w, len(ks)))
        L.append("| %g%s | %s|" % (x, unit, "|".join(cells)))
    txt = "\n".join(L)
    (OUT / (name + "_summary.md")).write_text(txt + "\n", encoding="utf-8")
    return txt


if __name__ == "__main__":
    def lst(k, dflt):
        return [float(v) for v in os.environ.get(k, dflt).split(",")]

    delays = lst("DELAYS", "100")
    jitters = lst("JITTERS", "0,50,100,200")
    pdrops = lst("PDROPS", "0")
    seeds = int(os.environ.get("SEEDS", "5"))
    name = os.environ.get("OUT", "ablate")
    points = [(d, j, p) for d in delays for j in jitters for p in pdrops]
    xkey = ('p_drop' if len(pdrops) > 1 else
            'jitter_ms' if len(jitters) > 1 else 'delay_ms')
    rows = run(points, seeds, name)
    print()
    print(summarize(rows, points, xkey, name))
