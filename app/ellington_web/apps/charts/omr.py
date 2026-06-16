"""Thin wrapper around the ``omr-leadsheet`` Python library.

Phase 4-PDF orchestrator surface (#81). Imports ``omr-leadsheet`` as a
library (Q1 decision: Python orchestration, not CLI shell-out). The
upstream API is one-PDF-equals-one-song; multi-song PDFs need
splitting which is filed as #84 (follow-up).

The wrapper does three things omr-leadsheet doesn't:

1. Builds an ``omr_leadsheet.config.Config`` from Django settings so
   the Celery worker doesn't have to know about ``omr-leadsheet``'s
   own env-var discovery rules.
2. Stages the uploaded PDF into a per-ChartImport workspace directory
   (omr-leadsheet writes its intermediate + output files under
   ``Config.book_dir`` keyed by ``pdf.stem``, so we control the stem
   here).
3. Translates omr-leadsheet's exception types into
   :class:`OmrLeadsheetError` subclasses with stable shapes the
   Celery task can decide on.

This module deliberately does NOT touch the ChartImport model — the
Celery task layer in ``apps.charts.tasks`` owns the lifecycle. Keep
this module pure so a future "split a multi-song PDF" path (#84) can
call ``run_one_pdf`` per sub-PDF without touching the Django ORM.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions — stable shapes the task layer matches on
# ---------------------------------------------------------------------------


class OmrLeadsheetError(RuntimeError):
    """Base class for OMR-pipeline failures.

    Subclasses convey *which stage* failed (OMR vs MuseScore export vs
    library missing). The task layer in ``apps.charts.tasks`` uses the
    subclass to decide whether to retry (transient) vs land as
    ``FAILED`` (permanent).
    """


class OmrLeadsheetNotInstalled(OmrLeadsheetError):
    """The ``omr-leadsheet`` Python package isn't importable.

    Distinct from the per-stage tool errors (Audiveris, MuseScore)
    because the fix is ``pip install omr-leadsheet`` not infra.
    Surfacing as its own class keeps the operator error message
    actionable.
    """


class OmrPipelineFailure(OmrLeadsheetError):
    """omr-leadsheet ran but its pipeline raised mid-process.

    Wraps RuntimeError / FileNotFoundError / etc. from
    ``omr_leadsheet.pipeline.process`` so the task layer doesn't have
    to catch a broad-and-changing set of upstream exceptions.
    """


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OmrOutcome:
    """Result of one ``run_one_pdf`` call.

    Always returned — never raised — when omr-leadsheet ran end-to-end.
    Upstream errors during the pipeline raise :class:`OmrLeadsheetError`
    subclasses instead so the task layer can branch on type.

    ``mscz_path`` is the absolute path to the produced ``.mscz``
    inside the per-ChartImport workspace. The task layer pipes this
    through :mod:`ingest.musescore` then can free the workspace if
    desired.

    ``review_md_path`` is the per-song suspicious-measure report
    omr-leadsheet writes alongside the .mscz. Optional — kept for
    operator surfaces (#82 detail view) and ignored by the task
    layer's success path.

    ``warnings`` are strings the task layer copies into
    ``ChartImport.error_log['page_warnings']``. omr-leadsheet's
    pipeline doesn't currently emit structured warnings; this is
    forward-compat for when it does.
    """

    mscz_path: Path
    review_md_path: Path | None = None
    warnings: tuple[str, ...] = ()


def run_one_pdf(
    pdf_path: Path,
    workspace_dir: Path,
    *,
    with_oemer: bool = False,
) -> OmrOutcome:
    """Run omr-leadsheet's ``process()`` over one PDF.

    ``pdf_path`` must already exist (the upload view stages it under
    ``MEDIA_ROOT/pdf_upload/<sha>.pdf`` and the task layer copies it
    into ``workspace_dir`` before calling here).

    ``workspace_dir`` is the per-ChartImport directory that becomes
    omr-leadsheet's ``Config.book_dir``. The caller owns its
    lifecycle (create on RUNNING, optionally clean up on
    COMPLETE/FAILED).

    ``with_oemer`` enables omr-leadsheet's second-engine OMR fallback;
    defaults off because oemer is a heavy optional dependency. The
    task layer can flip this from settings if/when we want it.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"pdf not found: {pdf_path}")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Stage the PDF into the workspace under a stable name —
    # omr-leadsheet keys its output dirs by ``pdf.stem`` so the
    # filename here becomes the resulting Song slug downstream.
    # Copy rather than symlink: Audiveris on some Linux distros
    # refuses to open symlinked input.
    staged_pdf = workspace_dir / pdf_path.name
    if staged_pdf.resolve() != pdf_path.resolve():
        shutil.copy2(pdf_path, staged_pdf)

    config = _build_config(workspace_dir)
    process = _resolve_process_function()

    try:
        mscz_path = process(config, staged_pdf, with_oemer=with_oemer)
    except FileNotFoundError as exc:
        # omr-leadsheet raises FileNotFoundError when the input PDF
        # vanishes mid-run (unlikely but possible) — preserve the
        # cause for the operator log.
        raise OmrPipelineFailure(
            f"omr-leadsheet could not find an input file: {exc}"
        ) from exc
    except RuntimeError as exc:
        # OMR-at-both-DPIs failure, MuseScore export failure, etc.
        # omr-leadsheet uses RuntimeError as the catch-all here.
        raise OmrPipelineFailure(str(exc)) from exc

    review_md = _find_review_md(mscz_path)
    return OmrOutcome(
        mscz_path=mscz_path,
        review_md_path=review_md,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_process_function():
    """Import omr-leadsheet's ``process`` lazily.

    Lazy import keeps the rest of ``apps.charts`` importable in
    environments without omr-leadsheet (CI on the django-check job
    skips the omr install; the model tests in #80 must still run).
    Surfaces a clean :class:`OmrLeadsheetNotInstalled` when the
    library is genuinely missing.
    """
    try:
        from omr_leadsheet.pipeline.process import process
    except ImportError as exc:
        raise OmrLeadsheetNotInstalled(
            "omr-leadsheet is not importable. Install with "
            "`pip install omr-leadsheet` (or from a local path during "
            "development). Phase 4-PDF cannot run without it."
        ) from exc
    return process


def _build_config(workspace_dir: Path):
    """Build an ``omr_leadsheet.config.Config`` from Django settings.

    Every required path / VLM toggle is sourced from Django settings
    rather than omr-leadsheet's own env-var discovery so the Celery
    worker's environment is the authoritative source. Settings hooks:

    - ``ELLINGTON_OMR_AUDIVERIS_BIN``  → Audiveris CLI path
    - ``ELLINGTON_OMR_MSCORE_BIN``     → MuseScore CLI path
    - ``ELLINGTON_OMR_STYLE_FILE``     → MuseScore .mss style file
    - ``ELLINGTON_OMR_VLM_ENABLED``    → enable chord-symbol VLM
    - ``ELLINGTON_OMR_VLM_BACKEND``    → "ollama" or "anthropic"
    - ``ELLINGTON_OMR_VLM_MODEL``      → e.g. "qwen2.5vl:7b"
    """
    from omr_leadsheet.config import Config

    audiveris = Path(
        getattr(
            settings,
            "ELLINGTON_OMR_AUDIVERIS_BIN",
            "/Applications/Audiveris.app/Contents/MacOS/Audiveris",
        )
    )
    mscore = Path(
        getattr(
            settings,
            "ELLINGTON_OMR_MSCORE_BIN",
            "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
        )
    )
    style = Path(
        getattr(
            settings,
            "ELLINGTON_OMR_STYLE_FILE",
            str(Path.home() / "Documents" / "MuseScore4" / "Styles" / "MyStyle.mss"),
        )
    )

    return Config(
        book_dir=workspace_dir,
        style_file=style,
        audiveris_bin=audiveris,
        mscore_bin=mscore,
        chord_vlm_enabled=bool(
            getattr(settings, "ELLINGTON_OMR_VLM_ENABLED", False)
        ),
        chord_vlm_backend=getattr(
            settings, "ELLINGTON_OMR_VLM_BACKEND", "ollama"
        ),
        chord_vlm_model=getattr(
            settings, "ELLINGTON_OMR_VLM_MODEL", "qwen2.5vl:7b"
        ),
    )


def _find_review_md(mscz_path: Path) -> Path | None:
    """Locate the per-song ``<song>.review.md`` next to the .mscz."""
    candidate = mscz_path.with_suffix(".review.md")
    return candidate if candidate.is_file() else None


__all__ = [
    "OmrLeadsheetError",
    "OmrLeadsheetNotInstalled",
    "OmrOutcome",
    "OmrPipelineFailure",
    "run_one_pdf",
]
