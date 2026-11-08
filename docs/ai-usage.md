# AI usage and verification log

## Tools and scope

This project was implemented with OpenAI Codex in the repository workspace. The
assistant read the full assignment PDF, inspected the supplied data and validator,
proposed a questionnaire, and implemented the user-approved scope. AI assisted
with architecture, pure-Python scheduling, replay validation, Django/DRF code,
Celery integration, UI code, tests, Docker configuration, and documentation.

No generated output was treated as proof of correctness. The source validator was
run, independent replay was implemented, hand-calculated examples and deliberately
corrupted traces were tested, and code was checked with runtime tests plus Ruff,
ty, and Pyright. Tools reported failures during development and the implementation
was corrected before the final checks.

## Actual user prompts and decisions

The following excerpts are from the working conversation; they are not proposed
or reconstructed prompts.

1. "read and understand the assignment"
   - Read all six PDF pages and inspected all supplied files.
   - Identified that the detailed concurrency model differs from the original
     validator's exclusive-server assumptions.
2. "prepare a questionnaire to decide on everything ... this has to be simple
   and correct and validated"
   - Produced explicit scope and correctness decisions.
3. "has to be django btw"
   - Fixed Django as the backend framework.
4. "we need two execution models; the validator and corrected validator. we can
   say sequential and concurrent" and "we need to define multiple scheduling
   strategies at least 4"
   - Chose sequential/concurrent modes and first fit, round robin, least
     connections, and fastest server.
   - User selected Django templates, DRF, PostgreSQL, strict FIFO queues,
     impossible-memory drops, CSV uploads, background execution, timeline results,
     retained run history, and local Docker deployment.
5. "go ahead and implement it. keep it simple and make sure all 8 model/strategy
   combinations are tested and validated ... make sure to use conventional
   commits ... make sure to use .venv, ruff, ty and pyright setups and format lint
   to avoid runtime errors ... keep assignment requirements and make sure to
   satisfy it"
   - Created `.venv`, a locked Python environment, a shared quality command, and
     tests parameterized over the complete matrix.
6. "make sure for logical and traceable commits" and "commit and continue do not
   wait for everything to be completed to commit act like developer"
   - Committed completed slices as tooling/fixtures, engine/tests, API/worker,
     dashboard, containerization/examples, and subsequent fixes/documentation.
7. "do a final review against the assignment, especially correctness across all
   8 model/strategy combinations. fix any gaps, keep it simple, and commit fixes
   logically using conventional commits"
   - Re-read the assignment and reviewed the engine, replay, worker, input
     boundaries, tests, and delivery setup.
   - Added hand-calculated expectations and FIFO/rate regressions for every pair;
     fixed same-tick trace causality, input boundaries, and CLI reporting.
8. "meanwhile improve ui/ux for ease of understanding and use"
   - Added guided steps, model/strategy explanations, one-click sample requests,
     clearer run states and errors, explicit timeline times, and deletion confirmation.
   - Exercised all eight pairs through the actual dashboard and inspected mobile layout.

## Verification decisions prompted by review

- Preserved `task/validate_run.py` unchanged and invoke it on sequential output.
- Kept the corrected replay implementation independent of engine execution.
- Used exact rational CPU shares instead of floating-point remaining-work values.
- Added hand-calculated tests where a completion frees memory before new starts.
- Added a start-rate test where the next start must occur before the next finish.
- Tested FIFO blocking and impossible requests, instead of only the small fixture.
- Tested original-validator rejection of a genuinely concurrent trace.
- Tested duplicate delivery, snapshot isolation from later server deletion,
  unavailable brokers, failed simulation, and interrupted-job recovery.
- Corrected malformed-header handling after reviewing the parser's exception
  boundary, and rejected server IDs that cannot be addressed through URL routes.
- Used PostgreSQL and real Celery workers for Docker integration checks in addition
  to the fast SQLite-backed local test suite.

## Primary references consulted

- [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [Celery Django integration and committed task dispatch](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html)
- [DRF serializers](https://www.django-rest-framework.org/api-guide/serializers/)

The final [validation record](validation.md) lists observed commands and results.
