#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_planE.py —— 実験系そのものの検証。結論より先にここを通すこと。

測っているものが「齢の効果」でなくなる壊れ方が 3 つある。
  ① 容量が揃っていない → 測っているのは容量差
  ② 齢マスクが効いていない → 齢なし条件が齢を見てしまう
  ③ 学習と評価が同じ軌道 → 測っているのは過学習
この 3 つを機械的に検査する。

  python3 test_planE.py
"""
import math

from env import evaluate, make_episodes
from joint import Context, Target
from policy import Policy, n_params

ok = 0
fail = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print("  OK   %s %s" % (name, detail))
    else:
        fail.append(name)
        print("  FAIL %s %s" % (name, detail))


print("① 容量の一致")
ps = [Policy(a, seed=s) for a, s in ((False, 0), (True, 0), (False, 1), (True, 1))]
ns = [len(p.get_flat()) for p in ps]
check("4 条件のパラメータ数が同一", len(set(ns)) == 1 and ns[0] == n_params(),
      "= %d" % ns[0])

print("② 齢マスク")
p_off, p_on = Policy(False, seed=3), Policy(True, seed=3)
base = dict(q=95.0, dq=12.0, q_ctx=100.0, dq_ctx=30.0, integ=0.1)
x1 = p_off.features(age=0.01, ahead=0.09, **base)
x2 = p_off.features(age=0.40, ahead=0.01, **base)
check("齢なしは齢を変えても入力が不変", x1 == x2)
y1 = p_on.forward(p_on.features(age=0.01, ahead=0.09, **base))[0]
y2 = p_on.forward(p_on.features(age=0.40, ahead=0.01, **base))[0]
check("齢ありは齢を変えると出力が変わる", abs(y1 - y2) > 1e-9,
      "Δ=%.4f deg" % (y2 - y1))
check("齢の端子だけが違い、他は同一",
      all(a == b for k, (a, b) in enumerate(zip(x1, p_on.features(age=0.01, ahead=0.09, **base)))
          if k not in (6, 7)))

print("②' アブレーションの 4 マスク")
masks = [(False, False), (True, False), (False, True), (True, True)]
ms = [Policy(m, seed=5) for m in masks]
check("4 マスクのパラメータ数が同一", len({len(p.get_flat()) for p in ms}) == 1,
      "= %d" % len(ms[0].get_flat()))
fa = [p.features(age=0.33, ahead=0.07, **base) for p in ms]
check("a のみは a だけ通す", fa[1][6] != 0.0 and fa[1][7] == 0.0)
check("â のみは â だけ通す", fa[2][6] == 0.0 and fa[2][7] != 0.0)
check("両方は両方通す", fa[3][6] != 0.0 and fa[3][7] != 0.0)
check("なしは両方落とす", fa[0][6] == 0.0 and fa[0][7] == 0.0)

print("③ 学習軌道と評価軌道の分離")
t_ev, t_tr = Target(seed=1000), Target(seed=2000)
check("係数が異なる", t_ev.c != t_tr.c)
check("軌道が実際に違う",
      max(abs(t_ev.q(t * 0.05) - t_tr.q(t * 0.05)) for t in range(80)) > 1.0)

print("④ 教師が下界として機能する")
worst = 0.0
for d in (0.0, 0.1, 0.4, 0.8):
    m = evaluate('teacher', make_episodes(d, n_ep=2, horizon=3.0), horizon=3.0)
    worst = max(worst, m['rms'])
check("教師の rms は遅延に依らず < 0.2 deg", worst < 0.2, "最大 %.3f deg" % worst)

print("⑤ naive は遅延とともに悪化する")
rs = [evaluate('naive', make_episodes(d, n_ep=2, horizon=3.0), horizon=3.0)['rms']
      for d in (0.0, 0.1, 0.2, 0.4)]
check("単調増加", all(rs[i] < rs[i + 1] for i in range(len(rs) - 1)),
      " -> ".join("%.2f" % r for r in rs))

print("⑥ 齢の信号が本物か")
tg = Target(seed=7)
cx = Context(tg, 0.15, t_ctx=0.1, seed=7, horizon=4.0)
ages, aheads = [], []
for k in range(0, 3000):
    _, _, a, ah = cx.at(k * 0.001)
    if k * 0.001 > 0.5:
        ages.append(a)
        aheads.append(ah)
check("齢は変動する", max(ages) - min(ages) > 0.05,
      "%.3f..%.3f s" % (min(ages), max(ages)))
check("齢は輸送遅延以上", min(ages) >= 0.15 - 1e-9, "min=%.4f s" % min(ages))
check("â は正で周期以下", 0 < max(aheads) <= 0.1 + 1e-9, "max=%.4f s" % max(aheads))

print("⑦ 文脈の O(1) 走査が総当たりと一致する")
cx.reset()
bad = 0
for k in range(0, 2000):
    t = k * 0.002
    got = cx.at(t)
    ev = [e for e in cx.events if e[0] <= t]
    if ev:
        t_arr, t_gen, q_c, dq_c = ev[-1]
        want = (q_c, dq_c, t - t_gen)
        if abs(got[0] - want[0]) > 1e-9 or abs(got[2] - want[2]) > 1e-9:
            bad += 1
check("一致", bad == 0, "不一致 %d 件" % bad)

print()
if fail:
    print("FAILED: " + ", ".join(fail))
    raise SystemExit(1)
print("all %d checks passed" % ok)
