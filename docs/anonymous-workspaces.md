# Temporary anonymous workspaces

This describes the application's runtime contract. The current private
[Hugging Face deployment](hugging-face.md) uses anonymous workspaces inside the
provider's access-controlled Space; visitors do not create ZoneMiner accounts.
The default `ZONE_ANALYTICS_MODE=local` retains the existing persistent local
workspace. It is intended for a trusted local installation. The explicit
`anonymous` mode isolates visitors and expires their data.

## Isolation and lifecycle

The API issues an opaque, random 256-bit bearer cookie. It is HttpOnly,
SameSite=Strict and Secure by default. Anonymous mode needs HTTPS; the
`ZONE_ANALYTICS_COOKIE_SECURE=0` exception is only for HTTP localhost testing.
The browser bootstraps one session before making concurrent API requests.

Behind a reverse proxy, set `ZONE_ANALYTICS_PUBLIC_ORIGIN` to the exact external
app origin, such as `https://alexandramilanova-zoneminer.hf.space`. Mutating browser
requests must match this origin even if the internal request URL differs. Other
origins, including other Spaces and localhost, remain rejected when configured;
forwarded headers do not add trusted origins. Without this setting, direct
same-origin access and the local Vite development origins retain their defaults.

Every visitor has a separate directory, DuckDB database, uploaded log/model,
replay cache, prediction artifacts and analysis results. Input hashes are only
deduplicated within that workspace. A dataset or analysis URL is not a sharing
mechanism. Jobs and SSE progress also require the same workspace cookie.
Bundled synthetic datasets are registered in each workspace. The developer's
local database is never copied into an anonymous workspace.

Sessions expire **24 hours after creation**, independent of activity. No account
is created and there is no recovery after the cookie is lost. The UI displays
the expiry and offers deletion. Access stops at expiry/deletion. The server
checks expiry every 60 seconds and deletes the whole workspace; in-flight
requests finish or hit their bound before files are removed. Active child
computations check expiry/deletion and are killed. Queued work checks expiry
before starting. Session metadata survives restart so expiry still runs after
restart. Interrupted analysis rows are marked as errors at startup.

Deletion is ordinary filesystem deletion, not a promise of secure media erasure.
Host snapshots, provider logs and backups have separate retention policies.
Workspace expiry governs application-managed files; it does not control those
provider policies. Review them before uploading sensitive data or enabling
public access. Users must download results they want to retain.

## Resource boundaries

There is no default fixed file-size, event-count, case-count, model-node,
per-workspace data-size, dataset-count or computation-time cap. A large CSV is
not rejected merely because its encoding is bigger than another representation.
The local application also has no fixed file/count caps by default. Input format,
model semantics and timestamp validation remain required; no records are silently
truncated. This does not mean every log will fit in RAM or finish in a practical
time. Anonymous work still ends when its session expires or is deleted.

The hosted service shares finite compute resources and queues intensive work.
For full performance on large logs or repeated experiments, use the local
installation on a machine with sufficient CPU, RAM and disk. Local mode retains
data across runs and avoids the hosted service's session expiry and shared
compute queue; it still has the physical limits of the local machine.

These defaults are configurable with the `ZONE_ANALYTICS_` prefix. For optional
policy caps, zero means disabled; a positive number opts into a deployment policy:

| Suffix | Default | Meaning |
| --- | ---: | --- |
| SESSION_TTL_SECONDS | 86400 | Fixed workspace lifetime |
| MAX_SESSIONS | 100 | Simultaneous retained workspaces |
| UPLOAD_MB | 0 (no fixed cap) | Optional maximum event-log MiB |
| MODEL_MB | 0 (no fixed cap) | Optional maximum PNML MiB |
| REQUEST_MB | 0 (no fixed cap) | Optional entire multipart request MiB |
| JSON_REQUEST_MB | 1 | JSON control-request MiB; does not limit uploaded files |
| WORKSPACE_MB | 0 (no fixed cap) | Optional per-workspace storage quota |
| TOTAL_STORAGE_MB | 0 (no fixed cap) | Optional total stored-data quota |
| DISK_RESERVE_MB | 512 | Stop accepting/writing data when actual free disk falls below this reserve |
| MAX_DATASETS | 0 (no fixed cap) | Optional datasets per workspace |
| MAX_EVENTS | 0 (no fixed cap) | Optional events per uploaded log |
| MAX_CASES | 0 (no fixed cap) | Optional cases per uploaded log |
| MAX_MODEL_NODES | 0 (no fixed cap) | Optional places plus transitions per net |
| MAX_REQUESTS | 16 | Concurrent anonymous API requests, including SSE |
| SESSION_REQUESTS | 8 | Concurrent requests per session |
| MAX_PROCESSES | 1 | Concurrent isolated computations |
| COMPUTE_QUEUE_WAIT_SECONDS | 0 (no policy timeout) | Admitted requests wait for a compute slot, up to session expiry; an optional positive value sets a shorter wait |
| WORKER_MEMORY_MB | automatic | Share 75% of detected container/host RAM across compute slots; positive values override, explicit 0 disables |
| NATIVE_THREADS | 1 | Rayon threads per isolated native computation |
| REQUEST_TIMEOUT_SECONDS | 0 (no fixed cap) | Optional isolated request computation timeout |
| ANALYSIS_TIMEOUT_SECONDS | 0 (no fixed cap) | Optional background computation timeout |
| MAX_PENDING_JOBS | 16 | Running plus queued jobs |
| SESSION_JOBS | 2 | Running plus queued jobs per workspace |
| MAX_JOBS | 1 | Background compute slots |
| JOB_EVENTS | 200 | Progress events retained per job, plus terminal event |
| JOB_HISTORY | 200 | Completed jobs retained globally |
| JOB_TTL_SECONDS | 3600 | Completed job retention time |

MB means 1024² bytes. Files stream to disk; limits count actual bytes, including
requests without Content-Length. XML document type/entity declarations are
rejected. Parsing, model discovery, helper rendering, statistical views and
prediction in anonymous mode execute in fresh child processes. Busy capacity
returns 429; expired sessions return 410; oversized inputs return 413; timeouts
return 504. Worker exceptions do not disclose source values or internal paths.

Actual free disk is checked during request/upload streaming and while workers
run. Optional storage quotas, if configured, are checked at admission and
artifact writes. Temporary files and concurrent writes can temporarily exceed
an optional quota or cross the free-space reserve between checks; these are not
filesystem reservation guarantees. A hosting plan still needs filesystem/container
limits and disk monitoring.

The automatic worker allocation budget uses the smaller of host physical RAM
and detected Linux cgroup memory limits, reserves 25% for the API/OS/libraries,
and divides the remainder across configured compute slots. It scales with the
hosting hardware rather than imposing a fixed 2 GiB ceiling. If detection is
unavailable there is no derived per-child limit; an explicit override remains
available. Native/file-backed mappings and memory competition mean this is not
a guarantee against an OS/container OOM kill.

Anonymous mode currently supports **one API process on Linux**. A lock rejects
a second API process using the same directory. A small bounded background queue
and process limits are appropriate for a modest demo service; this is not a
distributed job system. A process restart interrupts jobs. Optional compute timeouts
and the capacity-based allocation budget are application safeguards; deployment must also enforce a
container memory/CPU limit and choose ingress rate limits. No public-load or
penetration-test claim is made by the regression suite.

## Verification

`tests/test_anonymous_sessions.py` exercises real independent cookies, private
uploads/results/jobs, actual child computations, deletion, expiry, restoration of
expiry metadata, XML rejection, body limits without Content-Length, queue
saturation and process timeouts. The separate
`frontend/anonymous.playwright.config.ts` suite exercises browser upload,
analysis, isolation and deletion against an anonymous-mode localhost API.

The existing full browser suite targets local mode; its fixtures intentionally
reuse analyses between independent test contexts. Both suites cover Chromium,
Firefox and WebKit. WebKit automation is not a claim of testing branded Safari.

Deterministic change-point and dependency views are cached within their private workspace (at most 64 entries / 32 MiB). Cache keys include parameters, the feature-frame version and application source fingerprint. Session expiry/deletion removes these results too. Queued work checks session expiry before starting.
