#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env.py —— 1 エピソードを回し、誤差を「分布で」返す。

集計値は嘘をつくので、平均だけでなく p50/p90/p99/max を必ず返す
（feedback-measure-distribution-not-aggregate）。

制御器は 3 種類:
  teacher : 遅延ゼロの理想制御（学習の教師であり、性能の下界＝目標）
  naive   : 最後に知った目標角をそのまま指令する（学習なしの基準線）
  policy  : 残差方策（P0〜P3）。naive の上に差分を足す
"""
import math

from joint import DT, Q0, Servo, Target, Context, teacher_command
from policy import Policy


def _quant(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[i]


def simulate(mode, target, ctx, horizon=6.0, policy=None,
             collect=False, warmup=0.5):
    """1 エピソード。collect=True なら (特徴, 教師指令-基底) の学習データも返す。

    warmup 区間は指標から除く（起動直後は文脈が無く、齢が異常に大きいため）。
    """
    ctx.reset()
    srv = Servo(Q0)
    integ = 0.0
    ddq_prev = 0.0
    errs = []
    jerks = []
    data = []
    n = int(horizon / DT)
    for k in range(n):
        t = k * DT
        q_ctx, dq_ctx, age, ahead = ctx.at(t)
        integ += (q_ctx - srv.q) * DT * 0.5
        if integ > 2.0:
            integ = 2.0
        elif integ < -2.0:
            integ = -2.0

        if mode == 'teacher':
            u = teacher_command(target, t)
        elif mode == 'naive':
            u = q_ctx
        else:
            x = policy.features(srv.q, srv.dq, q_ctx, dq_ctx, integ, age, ahead)
            u = policy.command(q_ctx, x)

        if collect:
            # 特権教師のラベル: いま本当の目標を知っている制御器の指令
            x = (policy.features(srv.q, srv.dq, q_ctx, dq_ctx, integ, age, ahead)
                 if policy is not None else None)
            data.append((x, teacher_command(target, t) - q_ctx))

        srv.step(u)
        if t >= warmup:
            errs.append(abs(srv.q - target.q(t)))
            jerks.append(abs(srv.ddq - ddq_prev) / DT)
        ddq_prev = srv.ddq

    rms = math.sqrt(sum(e * e for e in errs) / len(errs)) if errs else 0.0
    out = {'rms': rms,
           'p50': _quant(errs, 0.50),
           'p90': _quant(errs, 0.90),
           'p99': _quant(errs, 0.99),
           'max': max(errs) if errs else 0.0,
           'jerk': (sum(jerks) / len(jerks)) if jerks else 0.0}
    return (out, data) if collect else out


def make_episodes(delay, n_ep=3, t_ctx=0.100, jitter=0.0, p_drop=0.0,
                  seed_base=1000, horizon=6.0, ahead_mode='nominal'):
    """決定論的なタスク集合。乱数で有利不利が出ないよう条件間で共有する
    （rl/dofbot_rl.py と同じ方針）。

    seed_base=1000 を評価用、2000 を学習用に使い、**学習と評価の軌道を分ける**。
    同じ軌道で学習して同じ軌道で測ると、齢の効果ではなく過学習を測ることになる。
    """
    eps = []
    for i in range(n_ep):
        tg = Target(seed=seed_base + i)
        cx = Context(tg, delay, t_ctx=t_ctx, jitter=jitter, p_drop=p_drop,
                     seed=seed_base + i, horizon=horizon + 0.5,
                     ahead_mode=ahead_mode)
        eps.append((tg, cx))
    return eps


def evaluate(mode, episodes, policy=None, horizon=6.0):
    """複数エピソードをまとめた指標。誤差は全エピソードを結合して分位点を採る。"""
    acc = {'rms': 0.0, 'p50': 0.0, 'p90': 0.0, 'p99': 0.0, 'max': 0.0, 'jerk': 0.0}
    for tg, cx in episodes:
        m = simulate(mode, tg, cx, horizon=horizon, policy=policy)
        for k in acc:
            acc[k] = max(acc[k], m[k]) if k == 'max' else acc[k] + m[k]
    n = len(episodes)
    for k in acc:
        if k != 'max':
            acc[k] /= n
    return acc
