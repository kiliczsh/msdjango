# Medsien load balancer simulation

A deterministic Python simulator with a Django / Django REST Framework dashboard,
PostgreSQL run history, and Celery workers backed by Redis. It implements two
execution models and four scheduling strategies. Every successful run is replay
validated before its trace can be downloaded.

## Run with Docker only

Prerequisites: Docker with Docker Compose v2. No Python, Node, or database setup is
required on your machine.

```sh
docker compose up --build -d --wait
```

Open <http://localhost:8000>. Initial startup migrates PostgreSQL and seeds the
provided servers once for a fresh database. Add/edit/delete servers in the
dashboard, select a model and strategy, and upload `task/requests.csv`. The results
include validation status, metrics, input snapshots, a request timeline, and a
`run.jsonl` download. Changes to servers affect future runs only.

The optional `.env.example` lists configuration overrides. Port 8000 is bound to
localhost; this assignment demonstration has no user accounts or authentication.
Writes require a CSRF token. Database and Redis ports are not published.

```sh
docker compose logs -f web worker
docker compose down
```

Named volumes retain server configuration and run history across container
restarts. `docker compose down -v` intentionally deletes that data. Startup never
overwrites existing server edits or recreates deliberately deleted servers.

## Verify everything with Docker

```sh
docker compose --profile test run --rm --build test
docker compose --profile test run --rm smoke
```

The first command runs Ruff lint and formatting checks, ty, Pyright, Django system
and migration checks, and the pytest suite against **PostgreSQL**. It includes all
eight model/strategy combinations at both engine and API levels. The second
command tests the actual HTTP → PostgreSQL → Redis → Celery → downloaded trace
path, twice for every combination, checks trace replay and byte equality, and
exercises server CRUD. Start the application first as shown above.

The test image supplies Node for Pyright. The runtime image contains only runtime
Python dependencies. Both run as a non-root user.

## Models and scheduling

| Model | CPU and concurrency | Validators |
| --- | --- | --- |
| `sequential` | One request per server; full CPU each tick | Original and corrected |
| `concurrent` | Equal CPU shares across active requests each tick | Corrected |

| Strategy | Eligible server selection |
| --- | --- |
| `first_fit` | First server by ascending ID |
| `round_robin` | Next eligible server in a stable cyclic order |
| `least_connections` | Fewest active requests; ties by ID |
| `fastest_server` | Highest CPU capacity; ties by ID |

All strategies use a strict FIFO request queue, ordered by `(arrival tick, request
ID)`. A temporarily blocked head request prevents later requests from starting.
A request that exceeds **every** server's memory is dropped at arrival with a
reason. Requests are never preempted, migrated, or dropped after starting.

The detailed assignment permits equal-share concurrency, but the supplied
`task/validate_run.py` rejects any overlap and assumes exclusive CPU runtimes.
That file is preserved unchanged. Sequential runs satisfy it. The corrected
`validate_run.py` independently replays shared CPU, aggregate reserved memory,
start-rate budgets, exact finish times, and complete request lifecycles. Concurrent
runs do not claim compatibility with the original validator.

See [design documentation](docs/design.md) for tick semantics, assumptions, failure
handling, and trade-offs, and [AI usage](docs/ai-usage.md) for prompts and
verification. The [validation record](docs/validation.md) records completed checks.

## CLI and example traces

`run.jsonl` is a generated sequential/first-fit example. `examples/` contains one
trace and a validation/metrics report for each of the eight combinations, using
the provided input files. Different configurations can legitimately produce
identical traces on this small dataset.

Run the engine without the dashboard, using only Docker:

```sh
docker compose exec web python -m simulation --servers task/servers.json --requests task/requests.csv --mode concurrent --strategy round_robin --output /tmp/run.jsonl
docker compose exec web python validate_run.py --servers task/servers.json --requests task/requests.csv --run /tmp/run.jsonl --mode concurrent
docker compose cp web:/tmp/run.jsonl ./run.jsonl
```

Check the tracked sequential example with the original validator:

```sh
docker compose exec web python task/validate_run.py --servers task/servers.json --requests task/requests.csv --run run.jsonl
```

The CLI deterministically overwrites the requested file. Dashboard runs version
their traces under distinct run IDs; timestamps and UUIDs never enter trace bytes.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET, POST | `/api/servers/` | List/create servers |
| GET, PUT, PATCH, DELETE | `/api/servers/{id}/` | Retrieve/update/delete a server |
| GET | `/api/runs/` | Paginated run history, newest first |
| POST | `/api/runs/` | Multipart `mode`, `strategy`, `requests_file`; returns 202 |
| GET | `/api/runs/{uuid}/` | Status, immutable snapshots, results and validation |
| GET | `/api/runs/{uuid}/trace/` | Validated JSONL attachment; 409 until successful |
| GET | `/api/health/` | Application/database readiness |

POST/PATCH/PUT/DELETE requests require the CSRF cookie and `X-CSRFToken` header.
The dashboard supplies both. Server numeric fields are JSON integers, not strings,
booleans, or fractional numbers. Server IDs are stable; edit capacity fields or
delete/recreate a server to change its ID.

Import/update servers or recover interrupted jobs:

```sh
docker compose exec web python manage.py load_servers task/servers.json
docker compose exec web python manage.py resume_runs
```

The import updates matching IDs and retains unlisted servers. `resume_runs`
re-enqueues queued/running jobs; terminal jobs are never rerun or overwritten.

## Optional local development

The supported demonstration and full integration checks use Docker. For fast
editor feedback, uv creates the requested `.venv` from the committed lockfile:

```sh
uv sync --locked
uv run python scripts/check.py
uv run python -m scripts.generate_examples
```

On Windows, activate `.venv\Scripts\Activate.ps1`; on Unix, use
`source .venv/bin/activate`. Local tests use isolated in-memory SQLite; Docker tests
use PostgreSQL. Ruff, ty, and Pyright are configured in `pyproject.toml` and run
against application, engine, scripts, and tests. The unmodified supplied validator
and generated migrations are excluded from style/type checking.

## Repository map

```text
simulation/       Immutable inputs, scheduling engine, independent replay, metrics, CLI
balancer/         Django models, DRF API, Celery task, templates and static assets
config/           Django, Celery and isolated local-test settings
tests/            Combination matrix, overload, hand calculations, mutations and API tests
scripts/          Quality runner, example generator and real-worker integration smoke
task/             Unmodified assignment and supplied fixtures/validator
examples/         Generated traces and validation reports for all eight combinations
docs/             Design, AI usage and validation record
```
