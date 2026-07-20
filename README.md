# xinu-mesh-rtos — turning the Xinu mesh into an AIPL-driven real-time OS

A plan and working track for evolving the bare-metal Embedded-Xinu mesh
([`xinu-rpi3`](https://github.com/yaskodama/xinu-rpi3) /
[`xinu-rpi4`](https://github.com/yaskodama/xinu-rpi4) /
[`xinu-rpi5`](https://github.com/yaskodama/xinu-rpi5)) into a **real-time
operating system for physical AI** — arm-type robots controlled by AIPL (a
custom actor language), with a target of **12 Xinu nodes**, one per joint /
subsystem.

The full write-up (background, gap analysis, roadmap, risks) is in
**[`docs/rtos_plan.pdf`](docs/rtos_plan.pdf)** (`docs/rtos_plan.tex`), and a
**code-level assessment** of where the real kernels fall short — with file:line
evidence across all three ports — is in
**[`docs/os_assessment.pdf`](docs/os_assessment.pdf)** (`docs/os_assessment.tex`).

## Where we are

The mesh already works as a **distributed parallel computer**:

- 4-core worker-pool SMP on all three boards (dining ×3.99–4.00, verified).
- A self-forming Wi-Fi ad-hoc mesh (periodic-HELLO neighbour discovery).
- 12-core distributed N-Queens across the three boards.

That is a *throughput* machine. An RTOS is a *timing* machine — a different and
stricter contract. This project closes that gap.

## Why it is not an RTOS yet

| # | Gap | Fix |
|---|-----|-----|
| ① | cooperative scheduling | fixed-priority preemptive (Rate-Monotonic / EDF) + priority inheritance |
| ② | unstable timer tick (`clktime=0` seen) | robust periodic tick + **measured** interrupt latency/jitter; tickless one-shot for tight deadlines |
| ③ | GC pauses (AIPL) | no-alloc RT path / incremental-region GC; separate RT vs best-effort heaps |
| ④ | demand paging → unbounded faults | pin RT-task memory |
| ⑤ | unbounded spins/timeouts (e.g. `SMP_WAIT_LIMIT`) | bounded, event-driven waits |
| ⑥ | best-effort drivers | WCET-bounded RT drivers (PWM/step-gen, encoder capture, CAN) |
| ⑦ | symmetric SMP vs non-reentrant runtime | **AMP partitioning** — fixed roles (control / sensor / planner core), maps onto "12 Xinu" |
| ⑧ | no safety fallback | watchdog + deadline-miss → safe torque/brake; fault containment |
| ⑨ | no isolation | Capability + **MMU-region** isolation of actors (MMU already on) |
| ⑩ | AIPL is untimed | express period/deadline/WCET as **types/effects**; static schedulability (this is the differentiator) |
| ⑪–⑭ | non-deterministic interconnect, distributed scheduler, collectives, task granularity | deterministic fieldbus (CAN/EtherCAT/TSN) + PTP time sync; P2P work-stealing; MPI-style collectives |

## Roadmap (see the PDF for acceptance criteria)

- **P1 — preemptive fixed-priority scheduler + timer/IRQ hardening**, with a
  **µs jitter-measurement harness**. *Highest ROI; everything else builds on it.*
  Acceptance: 1 kHz periodic task release jitter under budget (e.g. <100 µs),
  interrupt latency measured and reported.
- **P2 — remove non-determinism**: no-alloc RT path + GC separation, page
  pinning, no unbounded waits.
- **P3 — AMP partitioning** (isolate a control core) + **safety** (watchdog,
  safe-state, Capability+MMU isolation).
- **P4 — deterministic inter-node comms + time sync, distributed scheduler /
  collectives, and AIPL timing/effect types**, scaled to 12 nodes.

## Status

- [x] Plan document (`docs/rtos_plan.pdf`).
- [x] **Code-level OS assessment** (`docs/os_assessment.pdf`) — the 6 mechanisms
  audited against the real kernels. Headline findings:
  - **rpi3 is the only port with a real-time-shaped scheduler** (preemptive,
    priority, + EDF/MLFQ/aging/RCU hooks); it is the natural RT base.
  - **rpi5 has no preemption** (`proc.h:12`), its ready list is FIFO with the
    `prio` field never read, and it runs the **entire network stack inside the
    100 Hz timer ISR** (unbounded ISR).
  - **rpi4/rpi5 semaphores are non-blocking stubs** (`xinu_compat.c:88`) — no
    real synchronization; the actor mailbox **drops on overflow** (`cc.c:532`).
  - **No priority inheritance anywhere**; unbounded priority inversion is
    structurally possible.
  - **rpi5 demand-pages** (`mmu.c:267`) and uses first-fit `getmem` — both inject
    unbounded latency; no RT-memory pinning API.
  - The **AIPL GC is a stop-the-world actor sweep** driven from the timer path
    (`main.c:99`, ~8 s), and the value heap is a 32 KiB bump arena.
- [~] **P1** — *in progress.*
  - [x] µs **jitter-measurement harness** on rpi3 (`/rtos-jitter`) + **baseline
    captured** (`docs/p1_jitter_baseline.md`): a 1 kHz periodic task holds its
    period with **<60 µs jitter and zero deadline misses even under a full-core
    low-priority hog** — rpi3's preemptive fixed-priority scheduler is genuinely
    real-time-shaped. Residual loaded-vs-idle gap ~100 µs is the dispatch latency
    to drive down.
  - [x] **Cooperative-gap measured on rpi4** (`docs/p1_jitter_baseline.md`):
    under a CPU hog, jitter grows with the hog's non-yielding run (unbounded);
    a **1 kHz loop misses 82% of deadlines** (164/200) and rpi4's round-robin
    preemption does **not** help — vs rpi3's 57 µs / 0 misses. ~45× worse.
    (rpi5 skipped: its HTTP handler runs in the timer ISR, so proc-switching from
    it is unsafe — itself a finding.)
  - [x] **Ported preemptive fixed-priority scheduling to rpi4** — priority
    `ready_pop`, `proc_sleep_us` + timer-driven wakeup, tick 100→1000 Hz, RT
    procs isolated from the cooperative AIPL actor pump. Real-HW result: a
    high-priority 10 ms task holds its period at **~1 ms jitter with 0 deadline
    misses under a full-core CPU hog** (was 10 ms / 60-of-60 cooperatively),
    matching rpi3. Root cause of the first miss (new procs dispatched IRQ-masked
    so the timer couldn't preempt them) found via `[diag]` counters and fixed.
  - [ ] Generalise the entry IRQ-enable (a `proc_create` trampoline); tickless
    one-shot for true 1 kHz; port to rpi5 (handler runs in the timer ISR).
- [ ] P2–P4.

## Related

- `xinu-rpi3/4/5` — the boards (SMP, mesh, benchmark routes).
- `xinu-mesh-ga` — the sibling project: hardware-in-the-loop evolutionary design
  search on the same mesh.
