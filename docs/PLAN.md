# Ellington — Product Plan

A living roadmap for the Ellington web application. Updated at every
major decision; revise rather than ignore. Last revision: 2026-06-15
after Phases 1, 1b, 2, 3a shipped via epic #60.

## Cross-repo references

| Repo | Purpose |
|---|---|
| [`siege-analytics/ellington-web`](https://github.com/siege-analytics/ellington-web) | This repo — Django web app (GeoDjango Simple Template instantiation) |
| [`siege-analytics/ellington-systems`](https://github.com/siege-analytics/ellington-systems) | Python port of the master-voicing-style dispatcher (spike; closed epic [#1](https://github.com/siege-analytics/ellington-systems/issues/1)) |
| [`siege-analytics/ellington-web-manifests`](https://github.com/siege-analytics/ellington-web-manifests) | k8s manifests, Tekton CI, ArgoCD application |
| [`siege-analytics/musescore4-chord-library-plugin`](https://github.com/siege-analytics/musescore4-chord-library-plugin) | Origin codebase — Stage B distillation pipeline produces `usage_notes[]` consumed by Ellington |
| [`dheerajchand/omr-leadsheet`](/Users/dheerajchand/Documents/Professional/Siege_Analytics/Code/omr-leadsheet) | OMR pipeline — scanned PDF → `.mscz` lead sheet. To be integrated as a fourth Ellington ingest format (Phase 4-PDF). |

## Product framing

Ellington is a guitar practice + feedback platform. The core loop:

1. User has a lead sheet (chord progression).
2. User exports backing audio from that source (iRealPro audio export,
   BiaB render, MuseScore render).
3. User records themselves playing over the backing in Logic (or any
   DAW).
4. User uploads to Ellington.
5. Ellington's audio pipeline detects what the player actually played,
   time-aligns to the lead sheet measures, hands off to the comparator.
6. The comparator produces a `CritiqueDraft` — both a quantitative
   score and structured commentary fragments.
7. The LLM coach (eventually) renders prose feedback.

Two orthogonal axes the comparator works on:
- **master × style × idiom** (chart context) — sourced from the
  musescore4-chord-library-plugin's Stage B distillation pipeline
- **detected playing vs chart ground truth** (alignment) — sourced
  from sub-4 audio pipeline

The plugin's Stage B is a separately-tracked workstream that I
coordinate with the plugin agent on but don't drive.

## Architecture

```
                          https://ellington.siegeanalytics.com
                                       │
                                  traefik (k8s)
                                       │
                  ┌────────────────────┴────────────────────┐
                  │                                         │
              Authentik                                 WhiteNoise +
            forwardauth                                 Daphne (ASGI)
           (currently OFF —                             on port 8080
           ticket #14 disabled                                │
            it for dev access)                                │
                                                       Django (apps/core,
                                                       apps/charts,
                                                       apps/practice,
                                                       apps/styles)
                                                              │
                                                       PostGIS db
                                                       ellington_web on
                                                       default/db-postgis-master
```

Companion services on cyberpower microk8s (planned):

```
GPU node ─┬─ audio pipeline worker (Phase 3b: madmom / CREPE / librosa)
          ├─ omr pipeline worker (Phase 4-PDF: omr-leadsheet Celery task)
          └─ llm coach worker (Phase 5: prose render via Anthropic API or local)
```

## Epic map

The single epic is **siege-analytics/ellington-web#60** — practice-feedback loop.
Phases 1-3a shipped 2026-06-12 to 2026-06-14.

```
EPIC #60 — Practice-feedback loop
│
├─ Phase 1 ─── iRealPro chart ingest                            DONE 2026-06-12
│              (#61 / PR #62 — merged 0dd73a9)                   ✓ 1400 songs verified
│              `manage.py import_irealpro <playlist.html_or_uri>`
│
├─ Phase 1b ── DetectedVoicing.measure_index +                  DONE 2026-06-14
│              apps/charts/timeline.py math helpers              ✓ 2ae0012
│              (#63 / PR #64 — merged 2ae0012)
│
├─ Phase 2 ─── Practice-flow UI                                 DONE 2026-06-14
│              (#65 / PR #66 — merged 8e56186)                   ✓ login/list/create/detail/delete
│              session list/create/detail/delete + content-
│              addressed file storage + tempo persistence
│
├─ Phase 3a ── Audio pipeline scaffolding                       DONE 2026-06-14
│              (#67 / PR #69 — merged 27658c4)                   ✓ Celery task + placeholder analyzer
│              Celery task + chart-mirroring placeholder
│              Recording.analysis_status lifecycle field
│
├─ Phase 3b ── Real chord detection                             NOT STARTED
│              Algorithm choice TBD: madmom DeepChromaProcessor
│              vs CREPE-based crema vs librosa+chordino vs
│              Essentia. Multi-week. Needs design ticket.
│
├─ Phase 4-MS ─ MuseScore .mscz ingest                          PLANNED
│              `manage.py import_musescore <song.mscz>`
│              → MusicXML extract → ChordEvent rows
│              + audio/MIDI export via MuseScore 4 CLI
│
├─ Phase 4-PDF ─ Scanned-PDF ingest via omr-leadsheet           NEW — see workstream B below
│              Upload `.pdf` → Celery task on cyberpower fires
│              omr-leadsheet pipeline → `.mscz` → ingest via
│              Phase 4-MS importer
│
├─ Phase 4-BiaB ─ Band-in-a-Box import                          PLANNED
│              Accept pre-rendered `.mid` + `.wav` exports.
│              No native `.SGU/.MGU` parsing (no open-source
│              parser exists).
│
├─ Phase 5 ─── Sub-5 LLM coach prose                            CONTRACT-ONLY
│              (#57 — design note + reader signature stubbed,
│               no implementation)
│
├─ Phase 5-quant ─ Quantitative review model                    NEW — see workstream C below
│              Decompose comparator output into per-axis
│              scores (chord-symbol divergence, voicing-tag
│              affinity distance, tempo accuracy, etc.).
│              Aggregable into a single score, comparable
│              across sessions / styles / users.
│
└─ Phase 6 ─── Audio corpus model                               DEFERRED
               `LabeledSample` with provenance + visibility enums.
               Training data for sub-4, reference clips for sub-5.
               (#59 fork-vs-extension decision deferred until
                Coltrane Patterns + Bergonzi v1 reach s2-s4 plugin-side)
```

## Active workstreams

Three workstreams move in parallel. Each has its own ticket(s); each
is independently driveable. The product plan calls out which depends
on what.

### Workstream A — Phase 3b real chord detection

**State**: design conversation open; Dheeraj's go signal needed before
ticket files.

**Open questions** (will land in the design ticket as proposals):

- Algorithm: madmom `DeepChromaProcessor` (most-trodden in MIR) vs
  CREPE-based crema (research-y but high accuracy) vs librosa+chordino
  (lighter dep footprint) vs Essentia (C++; complex install)
- Worker placement: Celery task on cyberpower GPU node OR Daphne
  inline (no — multi-second work)
- Source separation for mixed user uploads: Demucs is the standard;
  required for shipping per Dheeraj 2026-06-12 ("users don't generally
  separate stems")

**Dependencies**: needs Phase 3a (#67/#69) merged — DONE.

### Workstream B — Phase 4 multi-format ingest

**State**: ticket TBD, scope confirmed:

- **Phase 4-MS** (MuseScore `.mscz` ingest): standalone — extract
  MusicXML from the `.mscz` ZIP, walk via music21 or manual XML
  parsing, emit Songbook → Song → ChordEvent rows. ~1 week.

- **Phase 4-PDF** (scanned-PDF ingest via omr-leadsheet): user uploads
  `.pdf` → Ellington fires a Celery task that:
  1. Runs the omr-leadsheet pipeline on cyberpower (Audiveris + VLM
     chord recognition + Tesseract lyric OCR + music21 reduction)
  2. Receives the resulting `.mscz`
  3. Hands it to Phase 4-MS importer to land ChordEvent rows
  4. Surfaces the per-measure flagged review artifacts in the practice
     session detail view so the user can correct OCR mistakes before
     practice
  ~2-3 weeks. Depends on omr-leadsheet being installable on cyberpower
  (Audiveris + qwen2.5vl via ollama already running there for plugin
  pipeline; same deps).

- **Phase 4-BiaB** (Band-in-a-Box import): accept user-uploaded
  pre-rendered `.mid` + `.wav` exports. No native `.SGU/.MGU` parsing.
  ~1 week.

**Dependencies**: Phase 1 (#61/#62) merged — DONE; Phase 1b
(#63/#64) merged — DONE.

### Workstream C — Quantitative review model

**State**: ticket TBD. New direction per Dheeraj 2026-06-15.

**Scope**: take the existing `CritiqueDraft` from
`apps/styles/comparator.py` (currently outputs
`style_match_score: float 0.0-1.0` + a list of free-form commentary
items) and decompose into:

- Per-axis scores: chord-symbol divergence rate per measure,
  voicing-tag affinity distance, tempo-accuracy, timing precision,
  proscriptive-rule violations, prescriptive-rule alignment
- A principled aggregation that produces a single 0-100 score
- A per-session record so users can see progression over time
- Comparison surfaces — between users (eventually), between styles
  (always: "you played 73% bossa, 21% bebop, 6% gypsy"), between
  sessions (improvement-over-time chart)

**Dependencies**: independent of Phase 3b — the quantitative model
works on whatever `DetectedVoicing[]` it gets. Phase 3a's
chart-mirroring placeholder is sufficient to develop the scoring math
against; the score becomes meaningful when Phase 3b's real detector
lands.

## Coordination — out-of-band workstreams

These run independently; I sync with them but don't drive:

- **Plugin agent's Stage B distillation pipeline** — produces the
  `usage_notes[]` content Ellington's `Master` model carries. 18
  masters / 2,073 notes / 200 proscriptive synced as of 2026-06-12
  pre-deploy. Plugin agent is currently working
  [plugin#505](https://github.com/siege-analytics/musescore4-chord-library-plugin/issues/505)
  (soft-hyphen relaxation in s2 validator) to unblock 7 OCR-recovered
  books at s1=accepted.

- **omr-leadsheet** — the OMR pipeline this product plan integrates
  via Phase 4-PDF. Currently on ticket
  [omr#106](https://github.com/dheerajchand/omr-leadsheet/issues/106)
  (VLM verification stage). Active development.

- **Authentik gate enablement** — single-env-var flip
  (`AUTHENTIK_HEADER_TRUST=1`) + manifests-side ingress annotation.
  Deferred until practice-flow has non-Dheeraj users.

## Deferred / parking-lot

| Item | Why deferred | Revisit when |
|---|---|---|
| Automated plugin catalog sync (#58) | Manual `kubectl cp` + sync works for our cadence | Multiple agents need it OR plugin merge frequency >2/day sustained |
| s5_lines fork-vs-extension (#59) | Need 2 corpora to decide | Coltrane Patterns + Bergonzi v1 both at s2-s4 plugin-side |
| Audio corpus `LabeledSample` model | Sub-4 doesn't need training data yet | Phase 3b ships with measurable confidence |
| Reinhardt / Howard Roberts onboarding | Reinhardt didn't write a method book; plugin#502 tracks gypsy-axis alternates | Dheeraj picks Horowitz / Rosenberg / Wrembel substitute |

## Decision log

Material architectural calls, with date + brief why. Append, don't
edit.

| Date | Decision | Why |
|---|---|---|
| 2026-06-10 | Three orthogonal axes: master × style × idiom | Single-axis model couldn't express "bossa chord vocabulary in gypsy backing while playing bebop voicings" |
| 2026-06-11 | Polarity field on usage_notes (prescriptive/proscriptive) | Greene's corpus is heavily restriction-based; inferring polarity from narrative wording is fragile |
| 2026-06-11 | Cross_ref between sibling notes | dom7#9 exception to dom7alt tonic-placement-restriction needs explicit link, not LLM inference |
| 2026-06-12 | iRealPro first, then MuseScore + BiaB | iRealPro format is well-documented + Dheeraj has a 1400-song corpus ready |
| 2026-06-12 | C (mixed-stem source separation) is the product target; A (separate stems) is the dev stepping stone | Users don't generally export separate stems from Logic |
| 2026-06-12 | Django + htmx frontend (not SPA) | Matches GST stack; fast to ship; rich enough for v0 audio UX |
| 2026-06-14 | omr-leadsheet integration as Phase 4-PDF (option B) | Highest product value — user uploads scanned songbook page → real lead sheet they can practice against |
| 2026-06-14 | Quantitative review model as Phase 5-quant, independent of Phase 5 LLM coach | Quantitative scoring doesn't need prose; both axes can develop in parallel |

## How to use this document

- When kicking off a new ticket, point its body at the relevant
  workstream section here for context.
- When changing direction, update the decision log.
- When a phase ships, update the epic map (status + commit) and the
  "Last revision" line at the top.
- When deferring something, add it to the parking-lot table with the
  trigger condition for revisit.
- Don't let this document drift — read it at the start of each
  multi-day session.
