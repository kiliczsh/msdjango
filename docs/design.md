# Design and correctness contract

## Architecture

```text
Browser (Django templates + plain JS)
    → Django REST Framework → PostgreSQL: servers, run snapshots, status and results
    → Redis → Celery worker → pure Python simulator → independent replay validator
                                               → original validator for sequential mode
                                               → validated trace and metrics in PostgreSQL
```

The engine imports no Django, Celery, database, or wall-clock facilities. Immutable
dataclasses describe inputs. The execution model determines server eligibility and
CPU sharing; scheduling strategies select among eligible servers. Four explicit
branches keep the implementation small. Adding a strategy requires updating its
selection rule, the strategy choices, UI description, and parameterized tests.

PostgreSQL is the source of truth for run results. JSONL is stored as text rather
than in shared filesystem storage. This keeps web and worker deployment simple
and makes a successful run and its output commit atomically.

A small bootstrap marker records initial server seeding separately from the server
table. After initialization, deleting all servers remains an intentional empty
configuration across restarts; startup never silently restores deleted servers.

## Tick semantics

An event at tick `t` describes the state at the start of `t`, after CPU work in
`[t-1, t)` has finished. At each scheduling boundary:

1. Finish due requests and release their reserved memory. Order by server ID,
   then request ID.
2. Record all requests arriving at `t`, ordered by request ID.
3. Drop impossible requests in that same order, with
   `reason=memory_exceeds_all_servers`. Other arrivals join the FIFO queue.
4. Reset each server's start counter. Schedule from the head of the queue until
   the head cannot be placed. Each start consumes one unit of that server's
   `rate_limit_per_sec` budget for this tick.
5. Divide each server's CPU equally among its active requests and perform the
   tick's work. Completion events appear at the next tick boundary.

Sequential mode limits the active set to one request. Its runtime is exactly
`ceil(work_units / cpu_units_per_tick)`. Concurrent mode uses
`Fraction(cpu_units_per_tick, active_request_count)` per tick. Exact rational
arithmetic avoids floating-point completion drift. CPU left over by an early
completion within a tick is not redistributed until the next tick.

Memory is reserved at start and held until finish. It is the **sum** of active
request memory that must fit. The CPU budget limits total allocation; it does not
limit the number of starts. Rate limits count starts, not arrivals or completions.

The engine jumps across intervals in which active sets and shares cannot change.
It stops at the next arrival, completion, or relevant start-rate reset. This is
equivalent to ticking one second at a time. A queued request blocked on memory or
server occupancy does not force empty tick-by-tick scheduling checks.

## Deterministic scheduling

Input list order is irrelevant: servers sort lexicographically by ID, and requests
sort by `(t, request_id)`. All strategies share the same strict FIFO queue.
Temporarily blocked requests are never bypassed. Impossible requests are rejected
at arrival rather than occupying the queue indefinitely.

- First fit: lowest eligible server ID.
- Round robin: maintain a cursor into the sorted server list. Search cyclically
  from that cursor. After a successful start, advance to the selected server's
  successor. Skipped servers do not advance the cursor; each run resets it to 0.
- Least connections: smallest active request count, then lowest server ID.
- Fastest server: greatest CPU capacity, then lowest server ID.

Eligibility always checks memory, start budget, and the selected execution model.
Multiple strategies can make identical decisions, especially when sequential
mode leaves all eligible servers idle. These are valid outcomes.

Event keys are emitted in a fixed order, encoded as compact ASCII JSON with LF
line endings and a final newline. No run IDs, timestamps, database IDs, random
values, or worker details enter the trace. Same inputs and configuration therefore
produce identical bytes across input permutations and supported platforms.

## Validation and the supplied-validator discrepancy

The provided validator enforces one active request per server, with exclusive CPU
and fixed ceil runtimes. Section 4 of the PDF permits shared-CPU concurrency. We
support both models explicitly, without altering the supplied artifact.

Every run passes the corrected independent replay validator. Sequential runs also
pass the original validator in an isolated subprocess. Concurrent runs mark
original validation as `not_applicable`, because shared CPU is outside its model.

The corrected validator consumes the trace rather than regenerating engine
output. It checks ordered nonnegative timestamps, known IDs, exact arrivals,
legal lifecycle transitions, expected completions under the active CPU shares,
aggregate memory reservations, per-tick starts, execution-model concurrency, and a
terminal outcome for every input request. It rejects early, late, duplicated,
missing, and wrong-server finishes. The engine and validator share input types,
but do not share scheduling or resource-update helpers.

Replay proves trace/resource correctness. It is not an optimizer or a proof that
the selected strategy was used. Separate hand-calculated strategy tests and FIFO
tests establish scheduling decisions. Determinism tests compare trace bytes and
reverse input lists; seeded workload tests exercise every combination.

## Background execution and failure handling

Run creation snapshots servers with one database SELECT and stores parsed requests
before publishing a task. Workers never read the mutable server table. A later
edit or deletion cannot change a queued or completed run.

Redis uses append-only persistence. Celery acknowledges after execution and
requests redelivery after worker loss. A PostgreSQL row lock serializes duplicate
deliveries for the same run. A task rechecks terminal status after obtaining the
lock, so repeated delivery cannot overwrite a successful trace. Simulation,
validation, metrics, and the final success state commit in one transaction. A
process crash rolls that transaction back; redelivery can safely recompute from
the saved snapshots.

Status changes to `running` before that transaction, so the dashboard can display
it. A normal simulation/validation exception records a failed state and useful
error; no trace is downloadable. A publish failure returns HTTP 503 and records a
failed run. There is a small commit-to-publish crash window, as no transactional
outbox is implemented. `resume_runs` explicitly re-enqueues unfinished runs after
an interruption. This also provides recovery after a broker restart. Failed jobs
remain available for diagnosis; submitting a new run is an explicit new attempt.

Workers have two execution processes, a 110-second soft limit, and a 120-second
hard limit. Work is simulated as quickly as possible; it never sleeps for a tick.
The independent original-validator subprocess has a 30-second timeout.

## Input contract and bounds

The supplied schemas are retained:

- `servers.json`: `tick_seconds=1`, and server objects containing `id`,
  `cpu_units_per_tick`, `mem_mb`, `rate_limit_per_sec`.
- `requests.csv`: exactly `t,request_id,work_units,mem_mb`, in any column order.
- `run.jsonl`: supplied lifecycle event names and fields. The optional drop event
  additionally carries a reason.

IDs are unique, nonempty, at most 80 characters, without edge whitespace or ASCII
control characters, and must encode as valid UTF-8. Server IDs cannot contain `/`
or equal `.` or `..`, so every
server can be addressed through the API. IDs are compared as case-sensitive
strings. Request IDs do not affect resource requirements; they break arrival ties.

CPU, memory, work, and start rates are positive integers. Arrival ticks are
nonnegative integers. Zero work is rejected to avoid ambiguous same-tick starts
and finishes. JSON booleans and fractional capacities are rejected. CSV numeric
columns use integer parsing. UTF-8 CSV with a BOM is supported. Duplicate IDs,
missing/extra columns, malformed quoting, and invalid UTF-8 are rejected.

Bounds: 100 servers, 2,000 requests, a 1,000,000-byte CSV, arrival/work values at
most 1,000,000, capacities at most 1,000,000,000, and completion by tick 1,000,000.
Exceeding the runtime bound fails a run explicitly; it never yields a partial
successful trace. The worker time limits bound pathological computation separately.

## Metrics and UI

Queue wait is `start - arrival`. Percentiles use the nearest-rank definition and
exclude dropped requests. Empty wait populations yield null values. Throughput
uses the elapsed interval from the earliest arrival to the last event, with a
minimum denominator of one tick. Server CPU utilization is completed useful work
divided by server CPU capacity times that interval; unused partial-tick work is
not counted as useful CPU. The timeline displays queue and execution intervals
on a common scale with exact tick labels.

The UI is intentionally server-rendered with small DOM-based JavaScript. User
supplied identifiers are rendered as text, not HTML. It supports pagination,
worker-state polling, visible errors, responsive tables, and keyboard-accessible
forms. Polling stops at a terminal state.

## Deliberate trade-offs

Strict FIFO can leave capacity idle behind a large request. First fit can favor
low-ID servers; fastest server can favor one powerful server; least connections
does not account for request size. These policies are intentionally easy to
explain and compare. No claim of optimal latency or fairness is made.

There is no autoscaling, authentication, streaming trace store, transactional
outbox, or external result backend. The application targets a local assignment
demonstration. PostgreSQL history, a Redis broker, and one Celery worker service
provide the requested background execution without additional services.
