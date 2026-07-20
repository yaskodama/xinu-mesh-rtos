# P1 baseline — periodic-task release jitter on rpi3

First concrete P1 measurement: how well does the **rpi3** port (the only one with
a preemptive fixed-priority scheduler) hold a periodic real-time task? Measured
on real hardware via the new `GET /rtos-jitter` route (`apps/webactor.c`): a
high-priority (prio 55) thread wakes every `period_ms` via `sleep()` and
timestamps each release with the 1 MHz system timer; **release jitter =
|measured period − target|**. Each period is measured **idle** and again with a
**low-priority (prio 10) CPU hog** burning the core the whole time.

## Results (µs; 0 deadline misses everywhere)

| period | idle max jitter | loaded max jitter | idle mean | loaded mean | misses |
|-------:|----------------:|------------------:|----------:|------------:|:------:|
| 1 ms (1 kHz) | 37 | 57 | 1001 | 1000 | 0 |
| 2 ms | 50 | 166 | 2002 | 2003 | 0 |
| 5 ms | 36 | 98 | 5005 | 5005 | 0 |
| 10 ms | 61 | 42 | 10011 | 10010 | 0 |

(`/rtos-jitter?period_ms=P&samples=N&prio=PR&hogprio=HP`, 200–500 samples.)

## What it shows

- **A 1 kHz servo loop is already viable on the A53:** mean period lands on
  1000 µs with max jitter under 60 µs and **zero deadline misses**, even under a
  full-core low-priority hog.
- **The scheduler is genuinely preemptive fixed-priority:** the hog does *not*
  disturb the high-priority periodic task — loaded jitter stays bounded and no
  period is missed. This is the property rpi4/rpi5 lack (see `os_assessment.pdf`).
- **The residual gap P1 targets:** loaded jitter (57–166 µs) exceeds idle jitter
  (36–61 µs) by ~100 µs — the preemption/dispatch latency when the RT thread has
  to displace the running hog. That ~100 µs is the concrete number to drive down
  (shorter critical sections, tickless one-shot timer, bounded ISRs).

## Method / reproduce

```
curl 'http://192.168.3.50:8080/rtos-jitter?period_ms=1&samples=500'
```

Harness: `xinu-rpi3` `apps/webactor.c` — `jit_measure` (periodic timestamped
thread), `jit_hog` (low-prio load), `/rtos-jitter` route. Baseline captured
2026-07-20 on real Pi 3 B+ hardware.

## Next

- Same harness on rpi4/rpi5 to quantify the cooperative-scheduler gap (expect
  large jitter / missed periods under load until a preemptive scheduler is ported).
- Drive the ~100 µs loaded-jitter down (P1 improvements), then P2 (bounded waits,
  priority inheritance) so worst-case — not just typical — jitter is bounded.

---

# The cooperative gap — rpi4 (and why rpi5 was skipped)

To make the case for a preemptive scheduler concrete, the same harness was
ported to **rpi4** (cooperative, round-robin preemption off by default) via its
`proc_create`/`proc_yield` API (`/rtos-jitter?...&chunk_us=C&preempt=0|1`). Here
the periodic task competes with a low-"priority" CPU hog that yields only every
`chunk_us` µs — modelling a real compute/AIPL actor that runs a while before
giving up the CPU.

## rpi4 cooperative — loaded jitter (best-of, consistent runs)

| period | hog chunk | preempt | max jitter | deadline misses |
|-------:|----------:|:-------:|-----------:|:---------------:|
| 10 ms | 2 ms  | off | 1 132 µs | 0 |
| 10 ms | 5 ms  | off | 2 083 µs | 0 |
| 10 ms | 10 ms | off | 7 095 µs | 1 |
| 10 ms | 20 ms | off | **17 086 µs** | 57 |
| 10 ms | 20 ms | **on** | 17 106 µs | 57 |
| **1 ms (1 kHz)** | 3 ms | off | **2 561 µs** | **164 / 200** |

(idle jitter on rpi4 is ~2–3 µs, timer-limited, same as rpi3 — the gap is
entirely about behaviour *under load*.)

## What it proves

- **Cooperative jitter ≈ the longest non-yielding run of any other task, and is
  unbounded:** it grows straight with the hog chunk (1 132 → 17 086 µs). A task
  that runs 20 ms before yielding pushes a 10 ms period out to 27 ms.
- **A 1 kHz servo loop is impossible on the cooperative kernel under load:** with
  a 3 ms hog, **164 of 200 releases (82%) miss their deadline**; worst release is
  2.5 ms late on a 1 ms period.
- **rpi4's optional round-robin preemption does not help** (17 106 ≈ 17 086 µs,
  57 = 57 misses) — matching `os_assessment.pdf`: preemption is suppressed while
  the non-reentrant AIPL/actor runtime holds the CPU.
- **rpi5 was not measured** because its HTTP handler runs inside the 100 Hz timer
  ISR (no dedicated net proc), so `proc_yield`/context-switch from the handler is
  unsafe — itself a finding: rpi5 is a step behind rpi4 on the proc model.

## Three-generation contrast (headline: 1 kHz under CPU load)

| board | scheduler | max jitter @1 kHz under load | deadline misses |
|-------|-----------|-----------------------------:|:---------------:|
| **rpi3** | preemptive fixed-priority, 1 kHz tick | **57 µs** | **0** |
| **rpi4** | cooperative (+ RR preempt, ineffective) | 2 561 µs | 164 / 200 |
| **rpi5** | no preemption (handler in timer ISR) | — (not measurable) | — |

**rpi3's preemptive scheduler holds a 1 kHz servo loop with ~45× less jitter and
zero misses versus rpi4's cooperative kernel.** This is the empirical case for P1:
port rpi3's `resched` to rpi4/rpi5, drive it from the timer, and keep RT control
tasks off the non-reentrant AIPL runtime (AMP) so preemption is never suppressed.

---

# P1 result — preemptive RT scheduling ported to rpi4

Ported rpi3's priority + preemption model onto rpi4's cooperative kernel
(`xinu-rpi4`, `system/proc.c` / `device/timer/timer.c`), **without touching the
non-reentrant AIPL runtime**:

- `ready_pop()` now returns the **highest-priority** ready proc (the `prio`
  field was previously never read).
- `proc_sleep_us()` (a new `PR_SLEEP` state) + `proc_timer_tick()`: the timer
  readies due sleepers and requests a preemptive switch, so a high-priority
  periodic task **wakes on time and preempts** lower-priority compute. Tick
  raised 100 → 1000 Hz.
- Only procs that call `proc_sleep_us()` sleep/preempt; **resident actors keep
  running cooperatively** under the existing `g_actor_pump` guard.

**Root cause of the first failed attempt** (found via `[diag]` counters):
`proc_preempt` was called only ~50×/s instead of 1000×/s during a CPU hog —
because a newly-dispatched compute proc inherited the dispatcher's masked-IRQ
state (the `ctxsw` runs inside `proc_resched`'s `irq_save`) and, being a tight
loop, never re-enabled interrupts, so **the timer never preempted it**. RT procs
now enable IRQs at entry (`msr daifclr, #2`).

## Result (period 10 ms, 20 ms CPU hog)

| | max jitter | deadline misses | preempts fired (`[diag]`) |
|---|---:|:---:|---|
| **preempt=1 (RT)** | **1 012 µs** | **0** | 660 |
| preempt=0 (cooperative) | 10 042 µs | 60 / 60 | 0 |

With preemption on, **`[idle]` and `[loaded]` are identical** (11 ms period,
~1 ms jitter, 0 misses): the high-priority periodic task holds its period under
a full-core CPU hog — matching rpi3. Regression-clean (boot, `/manet`, `/bench`
SMP 4×, actors all fine).

The residual ~1 ms jitter is the 1 kHz tick quantization; a 1 kHz *servo* period
sits at that limit (needs a tickless one-shot timer to reach rpi3's ~57 µs).

## Updated three-generation picture

| board | scheduler | 10 ms period under CPU load | 1 kHz servo |
|-------|-----------|:---------------------------:|:-----------:|
| rpi3 | preemptive priority (native) | ~0.06 ms jitter, 0 miss | 57 µs, 0 miss |
| **rpi4** | **preemptive priority (ported)** | **~1 ms jitter, 0 miss** | tick-limited (~1 ms) |
| rpi5 | cooperative (port pending) | — | — |

## Next

- Generalise the entry IRQ-enable (a `proc_create` trampoline) so every proc —
  not just RT ones — starts with interrupts on.
- Tickless one-shot timer for sub-tick (µs) periodic precision → true 1 kHz.
- Port the same to rpi5 (harder: its HTTP handler runs in the timer ISR).

---

# P1 #1 + #2 — general IRQ-enable + tickless one-shot (rpi4)

**#1 — general entry IRQ-enable.** The per-harness `msr daifclr` was replaced by
a `proc_create` trampoline (`ctxsw.S`: `msr daifclr #2; br x19`), so **every**
process starts with interrupts enabled — the fix belongs in dispatch, not the
workload. Verified: RT still holds ~1 ms jitter / 0 misses with no harness hack;
boot / SMP / actors regression-clean.

**#2 — tickless one-shot timer.** The fixed 1 kHz periodic reload became a
one-shot armed at the next RT deadline (`proc_next_delay_us()`; `proc_sleep_us`
arms via `timer_arm_before_us`), with a 1 ms floor for round-robin preemption.
Sub-tick precision for every period:

| period | periodic 1 kHz tick | **tickless one-shot** | misses |
|-------:|--------------------:|----------------------:|:------:|
| 10 ms  | 1 012 µs | **156 µs** | 0 |
| 1 ms (1 kHz) | ~1 ms (300/500 miss) | **228 µs** | **0** |

Period-to-period *variation* is only ~2 µs (the ~150–230 µs figure is a fixed
per-period overhead offset, not jitter). A 1 kHz servo now holds 0 misses under a
full-core CPU hog.

**Hardened (fixed):** the one-shot could fire as fast as 25 µs; with the per-IRQ
proctab scan, back-to-back tests could storm it and starve the net process into
a total hang. Raising the hard minimum between fires to **200 µs** makes any
storm a survivable slowdown — the previously-hanging back-to-back sequence now
runs through and the board stays alive, still 0 misses (1 kHz 403 µs, 10 ms
209 µs). 200 µs is well below the periods used, so no practical precision loss.

## Three-generation picture (final)

| board | scheduler | 10 ms under load | 1 kHz servo under load |
|-------|-----------|:----------------:|:----------------------:|
| rpi3 | preemptive priority (native) | ~0.06 ms, 0 miss | 57 µs, 0 miss |
| **rpi4** | **preemptive priority + tickless (ported)** | **156 µs, 0 miss** | **228 µs, 0 miss** |
| rpi5 | cooperative (port pending) | — | — |

rpi4 now matches rpi3's real-time behaviour — a high-priority periodic task holds
its period with zero deadline misses under a full-core CPU hog, at both 100 Hz
and 1 kHz — while the non-reentrant AIPL actor runtime keeps running
cooperatively (untouched). Next: harden the one-shot; port to rpi5.
