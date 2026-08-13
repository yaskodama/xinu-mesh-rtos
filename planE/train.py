#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train.py —— 4 条件の学習。

  P0 : 模倣学習・齢なし     P1 : 模倣学習・齢あり
  P2 : 強化学習・齢なし     P3 : 強化学習・齢あり

模倣は特権教師つき（案D と同じ枠組み）。教師は遅延ゼロで本当の目標を知り、
生徒は遅れた文脈と齢しか見ない。分布ずれを避けるため DAgger を 1 巡入れる
（生徒が訪れる状態で教師に label させる）。

強化学習は CEM（rl/dofbot_rl.py と同じ方式。純 Python で回る規模に収めるため）。
報酬は追従誤差の rms と p99、それにジャーク。**「待つ」ことを罰しない** ――
大遅延では減速・保守的な動きが最適解でありうるので、進捗そのものは報酬にしない。
"""
import math
import random

from env import evaluate, simulate
from policy import Adam, Policy, U_RES, n_params

W_P99 = 0.5      # 分布の裾を目的関数に入れる
W_JERK = 2.0e-6  # ジャークの重み（deg/s^3 の桁を吸収する）


def fitness(metrics):
    return -(metrics['rms'] + W_P99 * metrics['p99'] + W_JERK * metrics['jerk'])


# ── 模倣学習 ──────────────────────────────────────────────────────────────
def collect(episodes, policy, mode, horizon, stride):
    data = []
    for tg, cx in episodes:
        _, d = simulate(mode, tg, cx, horizon=horizon, policy=policy, collect=True)
        data.extend(d[::stride])
    return data


def fit(policy, data, epochs, lr, seed):
    p = policy.get_flat()
    opt = Adam(len(p), lr=lr)
    r = random.Random(seed)
    n_in = len(data[0][0])
    n_h = len(policy.b1)
    idx = list(range(len(data)))
    for _ in range(epochs):
        r.shuffle(idx)
        g = [0.0] * len(p)
        cnt = 0
        for t in idx:
            x, tgt = data[t]
            tgt = max(-U_RES, min(U_RES, tgt))
            out, h, y = policy.forward(x)
            # dL/dz2
            dz2 = 2.0 * (out - tgt) * U_RES * (1.0 - y * y)
            base = n_in * n_h + n_h          # W2 の開始位置
            for j in range(n_h):
                g[base + j] += dz2 * h[j]
            g[base + n_h] += dz2
            for j in range(n_h):
                dh = dz2 * policy.W2[0][j] * (1.0 - h[j] * h[j])
                off = j * n_in
                for i in range(n_in):
                    g[off + i] += dh * x[i]
                g[n_in * n_h + j] += dh
            cnt += 1
            if cnt >= 64:                     # ミニバッチ
                inv = 1.0 / cnt
                for i in range(len(g)):
                    g[i] *= inv
                p = opt.step(p, g)
                policy.set_flat(p)
                g = [0.0] * len(p)
                cnt = 0
        if cnt:
            inv = 1.0 / cnt
            for i in range(len(g)):
                g[i] *= inv
            p = opt.step(p, g)
            policy.set_flat(p)
    return policy


def train_imitation(use_age, tr_eps, seed, epochs=12, lr=0.02, stride=4,
                    horizon=3.0, dagger=1):
    pol = Policy(use_age, seed=seed)
    data = collect(tr_eps, pol, 'naive', horizon, stride)
    pol = fit(pol, data, epochs, lr, seed)
    for _ in range(dagger):
        data += collect(tr_eps, pol, 'policy', horizon, stride)
        pol = fit(pol, data, max(4, epochs // 2), lr * 0.5, seed + 1)
    return pol


# ── 強化学習（CEM） ───────────────────────────────────────────────────────
def train_cem(use_age, tr_eps, seed, pop=20, gens=12, elite=0.25,
              sigma0=0.35, horizon=2.0, init=None):
    n = n_params()
    r = random.Random(seed + 31)
    mu = list(init) if init is not None else Policy(use_age, seed=seed).get_flat()
    sig = [sigma0] * n
    n_el = max(2, int(pop * elite))
    pol = Policy(use_age, seed=seed)
    best, best_f = list(mu), -1e18
    for _ in range(gens):
        cand = []
        for _k in range(pop):
            p = [mu[i] + sig[i] * r.gauss(0, 1) for i in range(n)]
            pol.set_flat(p)
            f = fitness(evaluate('policy', tr_eps, policy=pol, horizon=horizon))
            cand.append((f, p))
        cand.sort(key=lambda z: -z[0])
        if cand[0][0] > best_f:
            best_f, best = cand[0][0], list(cand[0][1])
        el = [c[1] for c in cand[:n_el]]
        for i in range(n):
            m = sum(e[i] for e in el) / n_el
            v = sum((e[i] - m) ** 2 for e in el) / n_el
            mu[i] = m
            sig[i] = max(0.02, math.sqrt(v))
    pol.set_flat(best)
    return pol
