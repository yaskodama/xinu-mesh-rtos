# xinu-mesh-rtos — turning the Xinu mesh into an AIPL-driven real-time OS

A plan and working track for evolving the bare-metal Embedded-Xinu mesh
([`xinu-rpi3`](https://github.com/yaskodama/xinu-rpi3) /
[`xinu-rpi4`](https://github.com/yaskodama/xinu-rpi4) /
[`xinu-rpi5`](https://github.com/yaskodama/xinu-rpi5)) into a **real-time
operating system for physical AI** — arm-type robots controlled by AIPL (a
custom actor language), with a target of **12 Xinu nodes**, one per joint /
subsystem.

The full write-up (background, gap analysis, roadmap, risks) is in
**[`docs/rtos_plan.pdf`](docs/rtos_plan.pdf)** (`docs/rtos_plan.tex`).

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
- [ ] **P1** — jitter-measurement harness on a board (in progress); baseline
  numbers next.
- [ ] P2–P4.

## Related

- `xinu-rpi3/4/5` — the boards (SMP, mesh, benchmark routes).
- `xinu-mesh-ga` — the sibling project: hardware-in-the-loop evolutionary design
  search on the same mesh.
