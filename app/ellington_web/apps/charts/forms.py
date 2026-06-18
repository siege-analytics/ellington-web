"""Forms for the charts UI — PDF upload (Phase 4-PDF / #82).

The form spans a ``ChartImport`` create + a Songbook pick/create + a
content-addressed write. Not a ModelForm because the SHA-256 idempotency
flow is more elaborate than a single ``form.save()`` can express
cleanly.
"""

from __future__ import annotations

from django import forms

from .models import ChartImport, Songbook
from .storage import ALLOWED_PDF_EXTENSIONS, store_pdf_upload
from .tasks import dispatch_pdf_chart


# 100 MB cap. A typical Real Book scan is ~20-50 MB; 100 MB leaves
# headroom for higher-resolution scans without inviting absurd uploads.
_MAX_PDF_BYTES = 100 * 1024 * 1024


class PDFUploadForm(forms.Form):
    """Create form for a new ``ChartImport``.

    Two paths for Songbook:
    - ``songbook`` set → use that existing Songbook
    - ``new_songbook_name`` set → create one, then use it

    Exactly one must be filled; the form rejects both blank or both
    filled.
    """

    pdf = forms.FileField(
        required=True,
        label="PDF (.pdf)",
        help_text="Lead-sheet PDF — a single page or a multi-page book scan. Max 100 MB.",
    )
    songbook = forms.ModelChoiceField(
        queryset=Songbook.objects.all(),
        required=False,
        label="Existing songbook",
        help_text="Pick one of your existing songbooks.",
    )
    new_songbook_name = forms.CharField(
        required=False,
        max_length=255,
        label="Or create a new songbook",
        help_text="Leave blank if picking an existing one above.",
    )

    def clean_pdf(self):
        uploaded = self.cleaned_data["pdf"]
        if uploaded.size > _MAX_PDF_BYTES:
            raise forms.ValidationError(
                f"file too large ({uploaded.size} bytes); max is "
                f"{_MAX_PDF_BYTES // (1024 * 1024)} MB"
            )
        name = (uploaded.name or "").lower()
        if "." not in name:
            raise forms.ValidationError(
                "file has no extension — please ensure the file is named with a .pdf suffix"
            )
        ext = "." + name.rsplit(".", 1)[1]
        if ext not in ALLOWED_PDF_EXTENSIONS:
            raise forms.ValidationError(
                f"unsupported format {ext!r}; allowed: .pdf"
            )
        return uploaded

    def clean(self):
        cd = super().clean()
        sb = cd.get("songbook")
        new_name = (cd.get("new_songbook_name") or "").strip()
        if sb and new_name:
            raise forms.ValidationError(
                "pick an existing songbook OR enter a new name — not both"
            )
        if not sb and not new_name:
            raise forms.ValidationError(
                "pick an existing songbook OR enter a new name"
            )
        return cd

    def save(self, user) -> tuple[ChartImport, bool]:
        """Persist the ChartImport + dispatch the orchestrator.

        Returns ``(chart_import, dispatched)``. ``dispatched=False`` is
        the idempotent re-upload path — same user re-uploads the same
        PDF SHA, we hand back their existing ChartImport without
        re-dispatching.
        """
        if not self.is_valid():
            raise ValueError("save() called on invalid form")

        cd = self.cleaned_data
        stored = store_pdf_upload(cd["pdf"], cd["pdf"].name)

        # Idempotency check — same user + same SHA → reuse
        existing = ChartImport.objects.filter(
            user=user, file_ref=stored.file_ref,
        ).first()
        if existing is not None:
            return existing, False

        # Resolve songbook (pick-or-create)
        songbook = cd.get("songbook")
        if songbook is None:
            songbook = Songbook.objects.create(
                title=cd["new_songbook_name"].strip(),
            )

        chart_import = ChartImport.objects.create(
            user=user,
            file_ref=stored.file_ref,
            source_songbook=songbook,
        )
        dispatch_pdf_chart(chart_import)
        return chart_import, True


__all__ = ["PDFUploadForm"]
