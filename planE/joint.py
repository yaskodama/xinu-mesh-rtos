#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""joint.py —— 1 関節の位置サーボと、齢つきで届く上位目標。

案E（docs/ml_rt_proposals.pdf 第8節）の実験環境。第1層（関節、1 kHz）だけを模す。

  ・サーボ  : DOFBOT 級のシリアルバスサーボ。位置指令 u を受け、内部で PD、
              角速度は VMAX で飽和、可動域は 0..180 deg。
  ・上位目標: 5〜10 Hz でしか届かない「意味トークン」を、滑らかな目標角として模す。
              実物の VLA は要らない（案D の発想 —— 遅延の研究に遅延を生む実物は不要）。
  ・齢      : 方策が持っている文脈が何秒古いか。輸送遅延 d ＋ 配布周期の位相で決まる。
  ・â       : 次の文脈が届くまでの残り時間。tickless ワンショットタイマが持っている値で、
              OS だけが答えられる。案E に固有の入力。

注意: VMAX=180 deg/s はカタログ値ではなく推定（rl/dofbot_rl.py と同じ仮定）。
結論がこれに依存する場合は感度解析を回すこと。
"""
import math

DT      = 0.001      # 制御周期 1 ms = 1 kHz（rpi5 実測でジッタ 3 µs の層）
VMAX    = 180.0      # deg/s（推定値。データシート値ではない）
Q_MIN   = 0.0
Q_MAX   = 180.0
KP      = 900.0      # サーボ内部 PD（1/s^2）。ω=30 rad/s ≈ 4.8 Hz
KD      = 60.0       # ζ = KD/(2√KP) = 1.0（臨界制動）
T_LEAD  = 2.0 / 30.0 # ランプ追従の定常遅れ 2ζ/ω。教師の先行補償に使う

Q0      = 90.0       # 中立角
AMP     = 25.0       # 目標の振幅 deg


# ── 上位から降ってくる目標軌道 ────────────────────────────────────────────
class Target:
    """滑らかな目標角。サーボ帯域(4.8 Hz)より十分低い成分だけで作るので、
    遅延ゼロの教師なら誤差ほぼ 0 で追える = 教師が「正解」として機能する。"""

    def __init__(self, seed=0):
        import random
        r = random.Random(seed)
        # 3 成分。周波数は 0.15〜0.8 Hz。
        self.c = [(AMP * (0.55 - 0.15 * i) * r.uniform(0.7, 1.3),
                   2 * math.pi * r.uniform(0.15 + 0.2 * i, 0.35 + 0.2 * i),
                   r.uniform(0, 2 * math.pi)) for i in range(3)]

    def q(self, t):
        v = Q0
        for a, w, p in self.c:
            v += a * math.sin(w * t + p)
        return min(Q_MAX, max(Q_MIN, v))

    def dq(self, t):
        v = 0.0
        for a, w, p in self.c:
            v += a * w * math.cos(w * t + p)
        return v


# ── 齢つきの文脈配布 ──────────────────────────────────────────────────────
class Context:
    """上位の目標が、周期 T_ctx で生成され、輸送遅延 d を経て届く経路。

    ・生成時刻 t_k = k*T_ctx（＋ジッタ）。到達時刻 = t_k + d。
    ・時刻 t で方策が持っている最新の文脈は、到達済みのもののうち最後の 1 つ。
    ・齢 a = t - t_k（生成からの経過。輸送遅延と待ち時間の合計）。
    ・â  = 次の文脈が届くまでの残り時間（OS が知りうる上界）。
    ・drop: メールボックス溢れ（cc.c:532）を模す。落ちると齢が伸び、â は外れる。
    """

    def __init__(self, target, d, t_ctx=0.100, jitter=0.0, p_drop=0.0, seed=0,
                 horizon=8.0, ahead_mode='nominal'):
        import random
        r = random.Random(seed + 977)
        self.target = target
        self.d = d
        self.t_ctx = t_ctx
        # â の作り方。'nominal' = tickless タイマが持つ**名目周期**から計算する
        # （OS が実際に答えられる値。ジッタや脱落があれば外れる）。
        # 'oracle'  = 次に本当に届く時刻（実装の上限。OS には出せない）。
        self.ahead_mode = ahead_mode
        self.events = []          # (到達時刻, 生成時刻, 目標角, 目標角速度)
        k, t_gen = 0, 0.0
        while t_gen <= horizon + t_ctx:
            t_gen = k * t_ctx + (r.uniform(-jitter, jitter) if jitter else 0.0)
            if t_gen < 0:
                t_gen = 0.0
            if p_drop <= 0.0 or r.random() >= p_drop:
                self.events.append((t_gen + d, t_gen,
                                    target.q(t_gen), target.dq(t_gen)))
            k += 1
        self.events.sort()
        # 到着順に見て、生成時刻が過去へ戻るもの（追い越されて着いた古い文脈）は捨てる。
        # 案A の「文脈クラスは最新優先で上書き」に対応する。ジッタ 0 では何も起きない。
        keep, newest = [], -1.0
        for e in self.events:
            if e[1] > newest:
                newest = e[1]
                keep.append(e)
        self.events = keep
        self._i = 0

    def reset(self):
        self._i = 0

    def at(self, t):
        """時刻 t における (q_ctx, dq_ctx, age, ahead)。単調に呼ぶ前提で O(1)。"""
        ev = self.events
        i = self._i
        if ev[i][0] > t:      # 時刻が巻き戻った（走査は前向きなので張り直す）
            i = 0
        while i + 1 < len(ev) and ev[i + 1][0] <= t:
            i += 1
        self._i = i
        t_arr, t_gen, q_c, dq_c = ev[i]
        if self.ahead_mode == 'nominal':
            # 名目周期の次の到達予定時刻まで。脱落・ジッタがあれば当然外れる。
            T = self.t_ctx
            k = math.floor((t - self.d) / T) + 1
            nxt = (k * T + self.d) - t
            if nxt <= 0.0:
                nxt = T
        else:
            nxt = (ev[i + 1][0] - t) if i + 1 < len(ev) else 1.0
        if t < t_arr:                      # まだ最初の文脈が届いていない
            age = t + self.d               # 起動直後。齢は「持っていない」ぶん大きい
            return Q0, 0.0, age, max(0.0, nxt)
        age = t - t_gen
        return q_c, dq_c, age, max(0.0, nxt)


# ── サーボ ────────────────────────────────────────────────────────────────
class Servo:
    def __init__(self, q0=Q0):
        self.q = q0
        self.dq = 0.0
        self.u_prev = q0
        self.ddq = 0.0

    def step(self, u):
        u = min(Q_MAX, max(Q_MIN, u))
        ddq = KP * (u - self.q) - KD * self.dq
        self.ddq = ddq
        self.dq += ddq * DT
        if self.dq > VMAX:
            self.dq = VMAX
        elif self.dq < -VMAX:
            self.dq = -VMAX
        self.q += self.dq * DT
        if self.q < Q_MIN:
            self.q, self.dq = Q_MIN, 0.0
        elif self.q > Q_MAX:
            self.q, self.dq = Q_MAX, 0.0
        self.u_prev = u
        return self.q


def teacher_command(target, t):
    """遅延ゼロの理想制御。いま本当の目標がどこにあるかを知っている。
    臨界制動 2 次系のランプ追従遅れを先行補償で打ち消す。"""
    return target.q(t) + T_LEAD * target.dq(t)
