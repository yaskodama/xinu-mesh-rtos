#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""policy.py —— 関節方策（小さな MLP）と、齢入力の有無を厳密に容量一致で切り替える仕組み。

案E の対照設計（P0/P1/P2/P3）で最も間違えやすいのは容量を揃えないことである
（docs/ml_rt_proposals.pdf 8.3節）。ここでは
  ・齢なし条件でも齢の入力端子は持たせ、常にゼロを流す
  ・したがって 4 条件のパラメータ数は完全に同一
とする。test_planE.py がこれを検査する。

規模: 入力 8 → 隠れ 12(tanh) → 出力 1 = 121 パラメータ。
1 kHz で回すことと、将来ノード上で固定小数点にすることを見込んだ大きさ。
"""
import math

N_IN, N_H, N_OUT = 8, 12, 1
U_RES = 40.0          # 残差指令の飽和幅 deg（基底制御を大きく壊さないための安全設計）
A_SCALE = 0.30        # 齢・残り時間の正規化スケール s
IDX_AGE = (6, 7)      # 齢 a と â の入力位置


def n_params():
    return N_IN * N_H + N_H + N_H * N_OUT + N_OUT


class Policy:
    """残差方策。基底は「最後に知った目標角」（＝素朴な制御）で、方策はその差分を出す。"""

    def __init__(self, use_age, seed=0, params=None):
        # use_age は bool（両方の齢入力をまとめて切る）か、
        # (a を使うか, â を使うか) の 2 要素。容量は常に同一で、切るのは値だけ。
        if isinstance(use_age, (tuple, list)):
            self.use_a, self.use_ahead = bool(use_age[0]), bool(use_age[1])
        else:
            self.use_a = self.use_ahead = bool(use_age)
        self.use_age = (self.use_a, self.use_ahead)
        if params is not None:
            self.set_flat(params)
        else:
            import random
            r = random.Random(seed)
            s1 = math.sqrt(1.0 / N_IN)
            s2 = math.sqrt(1.0 / N_H)
            self.W1 = [[r.uniform(-s1, s1) for _ in range(N_IN)] for _ in range(N_H)]
            self.b1 = [0.0] * N_H
            self.W2 = [[r.uniform(-s2, s2) for _ in range(N_H)] for _ in range(N_OUT)]
            self.b2 = [0.0] * N_OUT

    # ── 入力の組み立て ───────────────────────────────────────────────────
    def features(self, q, dq, q_ctx, dq_ctx, integ, age, ahead):
        x = [(q - 90.0) / 45.0,
             dq / 180.0,
             (q_ctx - q) / 45.0,
             max(-1.0, min(1.0, integ)),
             (q_ctx - 90.0) / 45.0,
             dq_ctx / 180.0,
             age / A_SCALE,
             ahead / A_SCALE]
        # 端子は残したままゼロを流す（容量を揃えるため。値を落とすだけ）
        if not self.use_a:
            x[IDX_AGE[0]] = 0.0
        if not self.use_ahead:
            x[IDX_AGE[1]] = 0.0
        return x

    # ── 前向き ───────────────────────────────────────────────────────────
    def forward(self, x):
        W1, b1, W2, b2 = self.W1, self.b1, self.W2, self.b2
        h = [0.0] * N_H
        for j in range(N_H):
            w = W1[j]
            s = b1[j]
            for i in range(N_IN):
                s += w[i] * x[i]
            h[j] = math.tanh(s)
        s = b2[0]
        w = W2[0]
        for j in range(N_H):
            s += w[j] * h[j]
        y = math.tanh(s)
        return y * U_RES, h, y

    def command(self, q_ctx, x):
        out, _, _ = self.forward(x)
        return q_ctx + out

    # ── 平坦化（CEM 用） ─────────────────────────────────────────────────
    def get_flat(self):
        p = []
        for row in self.W1:
            p.extend(row)
        p.extend(self.b1)
        for row in self.W2:
            p.extend(row)
        p.extend(self.b2)
        return p

    def set_flat(self, p):
        k = 0
        self.W1 = []
        for _ in range(N_H):
            self.W1.append(list(p[k:k + N_IN])); k += N_IN
        self.b1 = list(p[k:k + N_H]); k += N_H
        self.W2 = []
        for _ in range(N_OUT):
            self.W2.append(list(p[k:k + N_H])); k += N_H
        self.b2 = list(p[k:k + N_OUT]); k += N_OUT
        assert k == n_params(), (k, n_params())


class Adam:
    """純 Python の Adam。模倣学習（回帰）用。"""

    def __init__(self, n, lr=0.02, b1=0.9, b2=0.999, eps=1e-8):
        self.lr, self.b1, self.b2, self.eps = lr, b1, b2, eps
        self.m = [0.0] * n
        self.v = [0.0] * n
        self.t = 0

    def step(self, p, g):
        self.t += 1
        b1, b2, lr, eps = self.b1, self.b2, self.lr, self.eps
        c1 = 1.0 - b1 ** self.t
        c2 = 1.0 - b2 ** self.t
        m, v = self.m, self.v
        for i in range(len(p)):
            gi = g[i]
            m[i] = b1 * m[i] + (1 - b1) * gi
            v[i] = b2 * v[i] + (1 - b2) * gi * gi
            p[i] -= lr * (m[i] / c1) / (math.sqrt(v[i] / c2) + eps)
        return p
