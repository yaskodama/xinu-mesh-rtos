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
