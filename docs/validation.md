# Validation record

Observed on 8 November 2026. The final application was built and started with
Docker Compose using PostgreSQL 17, Redis 7, Django, Gunicorn, and Celery workers.

## Final quality results

```sh
docker compose build web test
docker compose up -d --wait --wait-timeout 120
docker compose --profile test run --rm test
```

| Check | Observed result |
| --- | --- |
| Runtime and development image builds | Passed |
| Database migration and application startup | Passed; web/database/Redis healthy |
| Ruff lint | All checks passed |
| Ruff formatting | 38 Python files already formatted |
| ty | All checks passed |
| Pyright | 0 errors, 0 warnings |
| Django system checks | No issues |
| Migration drift | No changes detected |
| PostgreSQL pytest suite | **70 passed**, no warnings or skips |
| Local `.venv` quality suite | **69 passed, 1 expected skip** |
| JavaScript syntax (`node --check`) | Passed |

The local skip is the PostgreSQL-specific duplicate-delivery row-lock test.
SQLite does not implement that locking guarantee; the Docker suite executes and
passes it against PostgreSQL.

## Complete model/strategy matrix

```sh
docker compose --profile test run --rm smoke
```

This command exercised the real HTTP, PostgreSQL, Redis, Celery, and trace download
path. It submitted **16 successful runs**, two per combination, replay-validated
every downloaded trace, and asserted identical trace bytes between repetitions.
It also created, edited, listed, and deleted its own temporary server fixture.

| Model | Strategy | Engine/API tests | Corrected replay | Original validator | Real worker / repeat bytes |
| --- | --- | --- | --- | --- | --- |
| Sequential | First fit | Passed | Passed | Passed | Passed |
| Sequential | Round robin | Passed | Passed | Passed | Passed |
| Sequential | Least connections | Passed | Passed | Passed | Passed |
| Sequential | Fastest server | Passed | Passed | Passed | Passed |
| Concurrent | First fit | Passed | Passed | Not applicable | Passed |
| Concurrent | Round robin | Passed | Passed | Not applicable | Passed |
| Concurrent | Least connections | Passed | Passed | Not applicable | Passed |
| Concurrent | Fastest server | Passed | Passed | Not applicable | Passed |

Concurrent results are not presented as passing the original validator. A separate
hand-calculated test explicitly confirms that the original rejects a genuinely
overlapping concurrent trace.

## Additional exercised behavior

- Twelve seeded overload workloads for each of the eight combinations: 96
  workloads, with 20 requests each, including memory-infeasible drops.
- Hand-calculated shared-CPU finishes, fractional CPU shares, aggregate memory,
  full-duration memory reservations, and same-boundary memory release.
- Start-rate replenishment before the next completion; strict FIFO blocking;
  deterministic strategy choices; reversed input order; all-dropped workloads.
- Missing, duplicate, early, late, unordered, negative-tick, unknown-ID and
  incorrectly typed trace events; resource-limit violations.
- Malformed CSV headers/rows, invalid UTF-8, duplicate request IDs, oversized files,
  invalid capacities and unknown configuration choices.
- API server CRUD, CSRF enforcement, immutable run snapshots after server deletion,
  failed broker publication, failed simulation, interrupted-run recovery, and
  duplicate worker delivery under real PostgreSQL row locks.
- One-time startup seeding: intentional deletion of all servers survives subsequent
  startup seeding attempts.
- A request finishing exactly at the 1,000,000-tick limit and explicit failure when
  queued work would extend beyond that limit.

## Example reproducibility

```sh
uv run python -m scripts.generate_examples
git diff --exit-code -- examples run.jsonl
```

The generator validated all eight examples. The diff was empty. The real-worker
traces matched the same SHA-256 digests recorded by the local generator:

| Example configuration | SHA-256 |
| --- | --- |
| All four sequential strategies, provided dataset | `225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845` |
| Concurrent first fit / fastest server | `f63abcc30825b29abdd437f551123eae86416fe21c4e68a9f5694494e4e521e8` |
| Concurrent round robin / least connections | `72d177a66c0314ef6bfe2e30fc37a6916b860aaf40ce2d7f6bf100af38a886c1` |

Identical traces across different strategies are expected for this small input.
Separate strategy tests use inputs that distinguish their choices.

The root `run.jsonl` was also checked through both validator CLIs in the runtime
container. Both passed; the original reported four completed requests, no drops,
and average queue wait of 0.25 ticks.

## Browser verification

The running application was opened in the in-app browser. The following were
observed through the rendered UI:

- Server configuration rendered correctly; edit and cancel controls worked.
- Execution-model and strategy controls changed selection and descriptions.
- The provided CSV was selected through the browser file chooser.
- A concurrent/round-robin run was submitted and reached `succeeded` through the
  actual worker.
- Replay validation status, per-server metrics, and exact request timeline values
  rendered correctly; a trace download link was available.
- The browser console contained no warnings or errors during that flow.

## Development issues resolved

The first non-root Docker quality run exposed an unwritable Ruff cache; the cache
now lives in `/tmp/ruff-cache`. The first PostgreSQL concurrency-test run exposed
unclosed test-thread connections during database teardown; those connections are
now explicitly closed. Both fixes were rerun successfully. A transient registry
metadata timeout was resolved by using verified immutable Python and uv image
digests. These were development failures, not waived final checks.
