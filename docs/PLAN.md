# Ellington — Plan Outline

A living roadmap for the Ellington web application, the spike engine it consumes, and the cluster substrate it runs on. Re-read at every major decision; revise rather than ignore.

Cross-repo references:

| Repo | Purpose |
|---|---|
| [`siege-analytics/ellington-systems`](https://github.com/siege-analytics/ellington-systems) | Python port of the master-voicing-style engine + dispatcher (spike). Closed epic [#1](https://github.com/siege-analytics/ellington-systems/issues/1). Successor web epic [#12](https://github.com/siege-analytics/ellington-systems/issues/12). |
| [`siege-analytics/ellington-web`](https://github.com/siege-analytics/ellington-web) | This repo. Django web app — GeoDjango Simple Template instantiation. |
| [`siege-analytics/ellington-web-manifests`](https://github.com/siege-analytics/ellington-web-manifests) | k8s manifests, Tekton CI, ArgoCD application. |
| [`siege-analytics/musescore4-chord-library-plugin`](https://github.com/siege-analytics/musescore4-chord-library-plugin) | Origin codebase. Ships `scripts/engine_dump.js` as the oracle shim for Ellington's Goal A diff harness. |

## Architecture

```
                          https://ellington.siegeanalytics.com
                                       │
                                  traefik (k8s)
                                       │
                  ┌────────────────────┴────────────────────┐
                  │                                         │
              Authentik                                 (eventually)
            forwardauth                                  WhiteNoise +
           (currently OFF —                             Daphne (ASGI)
           ticket #14 disabled                          on port 8080
            it for dev access)                                │
                                                              │
                                                       Django (apps/core,
                                                       apps/practice,
                                                       apps/timeline,
                                                       apps/audio,
                                                       apps/coach)
                                                              │
                                                       PostGIS db
                                                       ellington_web on
                                                       default/db-postgis-master
```

Companion services (cyberpower microk8s, planned):

```
GPU node ─┬─ audio pipeline worker (sub-4: aubio/CREPE/librosa)
          └─ llm coach worker (sub-5: llama.cpp / vLLM, model TBD)
```

## Epic map

```
EPIC #12 — Ellington as web product (siege-analytics/ellington-systems)
│
├─ sub-1 ───── k8s deployment substrate                        DONE
│              (ellington-web-manifests#1)                     ✓ live
│
├─ sub-2 ───── Django web application
│   ├─ 2a ─── GST instantiation (ellington-web#6/#7)           DONE
│   ├─ 2b ─── Authentik header-trust middleware                DONE
│   │         (ellington-web#9/#10) + 6/6 tests pass
│   ├─ 2c ─── PostGIS DB wiring                                DONE
│   │         (ellington-web-manifests#2/#3)
│   ├─ 2d ─── apps/core growth                                 PARTIAL
│   │         (ensure_superuser command landed via #15/#16;
│   │          base models / profile / audit log deferred
│   │          until sub-3 or sub-4 forces the shape)
│   └─ 2e ─── production build — docker-bake + Daphne + COPY   DONE
│             (ellington-web#12/#13) → image swap #9/#10
│
├─ sub-3 ───── Master Timeline + iReal Pro ingestion           NOT STARTED
│              data shape:
│                  songbook → song → measure → chord_event
│                  voicings_referenced ← from sub-2b's spike port
│
├─ sub-4 ───── Audio pipeline                                  NOT STARTED
│              chord detection → alignment to master timeline
│              → per-measure feedback artifact
│
└─ sub-5 ───── LLM coach                                       NOT STARTED
               reads:
                  per-measure feedback (sub-4)
                  master timeline (sub-3)
                  voicing-style preferences (sub-2 / spike)
               writes:
                  human-language practice guidance
```

Cross-cutting & follow-ups:

| Ticket | Track |
|---|---|
| [ellington-web-manifests#6](https://github.com/siege-analytics/ellington-web-manifests/issues/6) | HMAC validation sweep on every `*-webhook` (org-wide gap; not Ellington-specific but blocks production exposure) |
| [ellington-web-manifests#18](https://github.com/siege-analytics/ellington-web-manifests/issues/18) | Graduate operator-applied Secrets to sealed-secrets OR Vault-injected (Vault already running cluster-side) |
| [ellington-web-manifests#14](https://github.com/siege-analytics/ellington-web-manifests/issues/14) (closed) | Authentik gate currently OFF on the IngressRoute — restore when ready for public auth, see ticket for the one-line revert |
| [geodjango_simple_template#30](https://github.com/siege-analytics/geodjango_simple_template/issues/30) | GST upstream — `staticfiles/` tracked in git + macOS Finder " 2" duplicate dirs |
| [geodjango_simple_template#31](https://github.com/siege-analytics/geodjango_simple_template/issues/31) | GST upstream — `settings/__init__.py` import order bug; `logging.py` reads `settings.LOGS_DIRECTORY` before `path_settings` has it |

## Substrate facts to remember

(See workspace memory entry `reference_cyberpower_cluster_conventions.md` for the full version.)

- **DNS:** `*.webhook.elect.info` is a wildcard A record → cluster. No DNS work for new webhooks.
- **PostGIS:** single multi-tenant instance `default/db-postgis-master`, pod container is `postgis` (not `db-postgis-master`). Each app gets its own DB + role.
- **Authentik:** single outpost `preview-elect-info-outpost` serves every Proxy Provider. New ProxyProvider → bind to that outpost. Don't spin up a new outpost.
- **Tekton bake:** the cluster's `sites-build-bake` Task is reusable across repos — its script just runs `docker buildx bake --file docker-bake.hcl --push`. The hardcoded `results` outputs at the end are electinfo-sites-specific names but go to nowhere if the Pipeline doesn't consume them.
- **Container registry:** in-cluster pull endpoint is **`localhost:32000`**, not `cyberpower:32000`. The registry NodePort is exposed on every node; each kubelet pulls from its own localhost.
- **HMAC gap:** every `*-webhook` EventListener in the cluster accepts unsigned POSTs. Tighten before exposing production endpoints to untrusted networks — see `ellington-web-manifests#6`.
- **Memory headroom:** cyberpower sits at ~169% memory limits / ~166% CPU limits (overcommit). One transient pressure event flapped the stateful tier 2026-06-08T19:30 CDT (magnum reboot cascade). Self-heals quickly; worth knowing.

## Operational patterns

### Secret-handling

Established by [ellington-web#15](https://github.com/siege-analytics/ellington-web/issues/15) + [ellington-web-manifests#17](https://github.com/siege-analytics/ellington-web-manifests/issues/17):

1. Idempotent Django management command (`apps/core/management/commands/<verb>.py`)
2. k8s Job manifest in `ellington-web-manifests/base/job-<verb>.yaml`, `envFrom` mounts both configmap and the operator-applied Secret
3. Secret shape documented as `base/<verb>.yaml.example` (placeholder values; never live)
4. README §N in `ellington-web-manifests` has the bootstrap recipe

Concrete example tonight: `ensure_superuser` provisioned the `dheeraj` Django superuser with passwords sourced from `Secret/ellington-web-admin`. Re-running the Job is safe (idempotency tests assert it doesn't reset passwords).

Graduation to sealed-secrets or Vault is tracked at `ellington-web-manifests#18`.

### Git workflow

Both `ellington-web` and `ellington-web-manifests`:

- `develop` is the default branch (origin of all work)
- `main` is downstream of `develop` (production), protected (PR-only, no force push, no deletion)
- Feature branches: `feat/<ticket>-<slug>` off `develop`, PR → `develop`, then a separate "promote develop → main" PR for the production cut
- One ticket per PR; ticket reference in every commit
- 0 required approvals (solo dev), but PR gate is enforced

## Decisions log

Decisions made tonight (2026-06-08 evening into 2026-06-09 early morning) that affect future work:

| Decision | Rationale |
|---|---|
| Daphne (ASGI), not gunicorn (WSGI) | Substrate placeholder Deployment was set to 8080 anticipating Daphne; ASGI keeps the door open for WebSockets in sub-4/5 |
| WhiteNoise for static, no nginx sidecar | One fewer container; collected statics get hashed filenames + 1y caching; fine until traffic justifies a CDN |
| Vue frontend deferred | Was part of GST; UI direction (Vue vs HTMX vs server-rendered) is a sub-3-or-later decision |
| `apps/core` grows by need, not speculation | Tonight: just auth (sub-2b) + `ensure_superuser` (sub-2d). Profile / audit / mixins land when sub-3 or sub-4 forces the shape |
| `localhost:32000` for cluster image pulls | NOT `cyberpower:32000` — sub-1's placeholder comment was wrong; verified against airflow/* + electinfo/* deployments |
| operator-applied Secrets, not sealed-secrets yet | Lower setup cost; graduate when there are >5 secret sources or rotation cadence justifies the tooling |

## Open questions

- **UI direction.** Vue + REST? HTMX + server-rendered? Plain Django templates? Sub-3's "play a Real Book chart" view will force this. Tentatively HTMX-first; revisit when designing sub-3's first page.
- **Audio pipeline placement.** Worker pod on the GPU node (cyberpower? magnum?) consuming a queue, OR an inline Django view? Inline only works for <30s clips; the practice loop assumes longer.
- **iReal Pro ingestion source.** End-user upload via Django form? Or admin-ingestion of a curated set? Probably both, but admin-first is faster to ship.
- **LLM coach hosting.** Local vLLM on the GPU node, or remote API? Local is cheaper and private; API is faster to prototype.
- **Auth re-enable.** Authentik gate currently OFF (ticket #14). Re-enable before any non-Dheeraj user account exists — the bypass + a real account would let anyone log in as that user.

## Pointers

- This document. Refresh it as the plan changes — don't let it drift.
- `ellington-web-manifests/README.md` — operator bootstrap recipes (DNS, Authentik config, ArgoCD, GitHub webhook, PostGIS DB, Django superuser).
- Workspace memory `reference_cyberpower_cluster_conventions.md` — the cluster facts captured tonight.
- Sub-2b's `apps/core/auth/middleware.py` + `backends.py` — the header-trust pattern for any future Authentik-fronted Django service in this cluster.
