# docker/

Container build inputs for the ellington-web substrate. Two images
ship from this directory:

| Image | Dockerfile | Purpose | Size class |
|---|---|---|---|
| `ellington-web` | `Dockerfile` | Django web (gunicorn / daphne) | ~1.2 GB |
| `ellington-web-worker` | `Dockerfile.worker` | Celery worker for OMR / audio queues | ~5 GB |

The worker image inherits FROM the web image so Django + Python + GDAL
stay in lockstep. Both targets ship from `docker-bake.hcl`; the
cluster's `sites-build-bake` Tekton Task invokes `docker buildx bake`
with no explicit target, picking up the `default` group's two entries.

## When to bump pinned versions

### Audiveris

`Dockerfile.worker` pins `AUDIVERIS_VERSION` (the OMR engine
omr-leadsheet shells out to). Bump when a newer Ubuntu-24.04 .deb is
tagged at <https://github.com/Audiveris/audiveris/releases>. Smoke-test
the new build against `apps/charts/tests_omr.py` before merging — the
binary path (`/usr/bin/Audiveris`) is set as
`ELLINGTON_OMR_AUDIVERIS_BIN` in the Dockerfile; if a release moves it,
update the `ENV` block.

### MuseScore Studio

`Dockerfile.worker` pins `MUSESCORE_VERSION` and `MUSESCORE_BUILD`
(both come from the AppImage filename). Bump when a newer release ships
at <https://github.com/musescore/MuseScore/releases>. The filename
pattern is
`MuseScore-Studio-${VERSION}.${BUILD}-x86_64.AppImage` — read the
exact `BUILD` suffix from the release asset list, not the version
string alone.

## What the .mss file represents

`docker/styles/Siege_Jazz_Style.mss` is Dheeraj's MuseScore Studio 4
style file, baked into the worker so `omr-leadsheet` produces
consistently-rendered .mscz outputs. It's XML style data (stroke
widths, fonts, layout) — no copyrightable content, safe in the public
repo. The source-of-truth lives at
`~/Documents/MuseScore4/Styles/Dheeraj-Jazz.mss` on Dheeraj's box;
re-export and copy when the style evolves.

## Rebuilding the worker locally

```bash
# Builds both images. The worker target named-contexts the web target
# so they're produced in one pass without needing a registry push
# between them.
docker buildx bake --file docker-bake.hcl --load

# Just the worker, using a pre-built web image:
docker buildx bake --file docker-bake.hcl ellington-web-worker --load
```

The worker image is ~5 GB unpacked; expect ~10-15 minute first build
on a clean machine (Audiveris + MuseScore AppImage downloads dominate).
Subsequent builds reuse layers.

## Out-of-scope splits

Phase 3b audio chord-detection worker (#86) gets its own thin image
when `madmom` lands — different deps from omr-leadsheet and the
audio-analysis queue cadence is fast enough to deserve isolation. For
now both queues run on `ellington-web-worker`.
