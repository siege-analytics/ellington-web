# ellington-web

Ellington web application — Django on the GeoDjango Simple Template ([siege-analytics/geodjango_simple_template](https://github.com/siege-analytics/geodjango_simple_template)). Consumes the [`siege-analytics/ellington-systems`](https://github.com/siege-analytics/ellington-systems) engine. Part of [ellington-systems#12](https://github.com/siege-analytics/ellington-systems/issues/12).

Production deploys to the cyberpower microk8s cluster at [https://ellington.siegeanalytics.com](https://ellington.siegeanalytics.com). Manifests live in [siege-analytics/ellington-web-manifests](https://github.com/siege-analytics/ellington-web-manifests).

## Layout

```
app/
  ellington_web/             # Django project root
    ellington_web/           # project module (settings, asgi, urls, celery)
    locations/               # GST sample app — placeholder until sub-2d
    manage.py
docker/                      # Dockerfile, entrypoint, nginx config
conf/                        # gunicorn / django / postgres / build config
compose.yaml                 # local dev (NOT production — that's k8s)
Makefile                     # `make build`, `make up`, `make migrate`, etc.
```

## Local development

```bash
make build       # build container images
make up          # start the stack (Django + PostGIS + nginx)
make migrate     # run Django migrations
make shell       # shell into the webserver container
```

Once up: `http://localhost:8000/` (Django), `http://localhost:8001/` (nginx).

## Management commands

Operator-facing `manage.py` commands. Every sync command supports `--dry-run` so a release can be previewed before any DB writes.

### Readiness

- **`preflight_check`** — exits non-zero if any migrations are pending. Wire as a Kubernetes readiness probe so stale-schema pods deregister rather than serving 500s. Add `--verbose` to name pending migrations on failure. (#213)

### Catalog syncs

- **`sync_engine_rules`** — pulls a pinned plugin Release bundle and upserts the EngineRule catalog. Mutually-exclusive source flags:
  - `--release-tag <tag>` — pin a specific release
  - `--latest-release` — auto-resolve highest-semver `engine-rules-v*` tag from GitHub (removes need for init-container tag lookup) (#157)
  - `--bundle-path <path>` — read a local tarball (offline / CI)

  Plus: `--dry-run` (load + validate + plan add/update/deactivate counts; skip DB writes, #218); `--force` (override the >50% mass-deactivation guard).

- **`sync_voicings`** — pulls plugin `voicings.json`. Flags: `--source-url`, `--local-path`, `--plugin-sha`, `--built-at`, `--dry-run` (#220).

- **`sync_plugin_catalogs`** — pulls plugin `styles.json` / `idioms.json` / `masters.json`. Flags: `--plugin-data-dir`, `--skip-masters`, `--dry-run` (#222).

All three sync commands emit a `==== DRY RUN — no DB writes ====` banner when `--dry-run` is set so logs don't lie about what happened.

## Status

- **sub-1 (k8s substrate):** done — site serves at `ellington.siegeanalytics.com` behind LetsEncrypt + Authentik
- **sub-2 (GST instantiation):** in progress
- **sub-3** Master Timeline + iReal Pro ingestion, **sub-4** audio pipeline, **sub-5** LLM coach: upcoming

## License

Apache 2.0. See [LICENSE](LICENSE).
