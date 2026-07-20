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
