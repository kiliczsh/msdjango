# Final assignment review

Reviewed against the six-page supplied assignment on 8 November 2026, with the
user-approved additions of two execution models and four scheduling strategies.

## Requirement mapping

| Requirement | Implementation and evidence |
| --- | --- |
| Python backend with dashboard APIs | Django, Django REST Framework, server CRUD and run endpoints |
| Docker-only startup, including database/broker | Compose starts PostgreSQL, Redis, migrations/one-time seeding, Gunicorn and Celery; verified healthy |
| Heterogeneous CPU, memory and rate constraints | Exact per-server CPU shares, full-duration memory reservation, per-tick start budgets; hand-calculated and overload tests |
| Sequential compatibility with supplied validator | All four strategies validate with both the supplied validator and independent replay |
| Shared-CPU concurrent execution | All four strategies validate with corrected replay; original-validator incompatibility is explicit |
| Deterministic ties and output | Documented request/server/completion ordering, exact arithmetic, fixed JSON encoding; repeated bytes and reversed input-order tests |
| Queue/drop policy | Strict FIFO head blocking; infeasible-memory requests dropped at arrival with reasons; all eight combinations tested |
| No duplicate or simultaneous multi-server execution | Lifecycle and resource replay, duplicate-event rejection, PostgreSQL duplicate-delivery locking test |
| Server view/add/edit/delete | Dashboard and API; immutable run snapshots; startup retains intentional deletions |
| Trigger simulation and generate run.jsonl | Dashboard submits background jobs; successful validation unlocks the JSONL download; CLI also writes run.jsonl |
| Deterministic overwrite/versioning | CLI overwrites deterministically; saved runs version traces by UUID with IDs/timestamps outside trace bytes |
| Example data/output and alternative datasets | Supplied inputs preserved; eight generated examples; heterogeneous hand calculations and 96 seeded overload workloads |
| Architecture, scheduling, limits and trade-offs | README and design documentation, including the original/corrected validator distinction |
| Documented AI use, prompts and verification | AI usage log with actual user prompts and observed verification steps |
| Optional UI, multiple strategies and metrics | Request timeline, four strategies, cluster/per-server results and wait metrics |
| GitHub repository link for submission | Still a publishing step: this local repository has no Git remote configured |

## Findings fixed during review

1. The corrected replay grouped tick events before checking lifecycle order. It
   could accept a start before arrival at the same timestamp. An independent
   file-order lifecycle pass now rejects this for both models; the supplied trace
   remains accepted.
2. Previous tests demonstrated resource feasibility and determinism but had fewer
   independent scheduling expectations. A heterogeneous, hand-calculated matrix
   now asserts exact assignments and start/finish times for all eight pairs,
   supplemented by FIFO and rate/CPU expectations for every pair.
3. A valid import could merge with retained servers to exceed the cluster limit.
   The import now rejects that operation atomically. Pure-engine IDs also reject
   invalid Unicode before encoding or persistence.
4. The corrected validator CLI lacked summary output and could raise a traceback
   on invalid UTF-8 files. It now reports aggregate metrics and returns exit code 2
   with a useful invalid-result message.
5. Dashboard controls and results needed clearer context. The UI now explains
   each model and policy, supplies sample CSV data, shows progress/error states,
   brings results into view, separates exact timeline times, and confirms deletion.

No scheduling-engine algorithm change was required: the event-jump implementation
matched all added hand calculations. The engine remains independent of Django,
and the supplied validator and assignment artifacts remain unchanged.

## Final verification

- **120 tests passed against PostgreSQL**, with no warnings or skips.
- Ruff lint/format, ty, Pyright, JavaScript syntax, Django and migration checks passed.
- **16 real-worker runs**: every pair twice, independently replayed, matching trace bytes.
- **8 browser runs**: every pair completed and exposed its validated trace.
- Mobile layout, edit/cancel, delete confirmation/cancel and saved-run focus/navigation checked.
- All eight examples regenerated without changes; assignment artifacts unchanged.

Detailed commands and trace hashes are in [the validation record](validation.md).
GitHub publishing was not performed: no destination remote is configured locally.
