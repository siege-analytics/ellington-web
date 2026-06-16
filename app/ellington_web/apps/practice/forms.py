"""Forms for the practice-flow UI.

``PracticeSessionForm`` handles the create-session flow: pick a song,
pick a target style preset, set tempo, upload a recording. The form
returns a saved ``PracticeSession`` + ``Recording`` pair; storage of
the uploaded file is delegated to :mod:`apps.practice.storage`.
"""

from __future__ import annotations

from django import forms

from apps.charts.models import Song
from apps.styles.models import StylePreset

from .models import PracticeSession, Recording
from .storage import ALLOWED_AUDIO_EXTENSIONS, store_upload


# Hard cap on upload size to protect Daphne from absurd uploads. A
# 10-minute uncompressed 48kHz stereo WAV is ~110MB; cap at 500MB to
# leave headroom for long sessions + future longer formats.
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


class PracticeSessionForm(forms.Form):
    """Create form for a new ``PracticeSession`` + ``Recording``.

    Not a ModelForm because the form spans two models (PracticeSession
    AND its first Recording), and the file goes through a custom
    storage helper rather than a Django FileField. The view calls
    ``form.save(user=request.user)`` to commit.
    """

    song = forms.ModelChoiceField(
        queryset=Song.objects.all(),
        required=True,
        label="Song",
        help_text="Pick a song from your imported songbooks.",
    )
    target_preset = forms.ModelChoiceField(
        queryset=StylePreset.objects.all(),
        required=True,
        label="Target style",
        help_text=(
            "The style you're aiming for — the comparator scores how "
            "close your playing comes to this preset."
        ),
    )
    tempo_bpm = forms.IntegerField(
        required=True,
        min_value=20,
        max_value=400,
        label="Tempo (BPM)",
        help_text="If left at the song default, the comparator's timeline "
        "math uses this value to align your recording to the chart.",
    )
    recording = forms.FileField(
        required=True,
        label="Recording (.wav / .mp3 / .m4a / .flac / .aiff / .ogg)",
        help_text="Upload your Logic export (mixed bounce or isolated track). "
        "Max 500 MB.",
    )
    notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        label="Notes (optional)",
        max_length=2000,
    )

    def __init__(self, *args, **kwargs):
        # Optional ``initial_song_id`` lets the view pre-select a song
        # when the user arrived from a song-detail page. Pop before
        # super().__init__ so Django's form machinery doesn't complain.
        initial_song_id = kwargs.pop("initial_song_id", None)
        super().__init__(*args, **kwargs)
        if initial_song_id is not None:
            self.fields["song"].initial = initial_song_id
            song = Song.objects.filter(pk=initial_song_id).first()
            if song and song.default_tempo_bpm:
                self.fields["tempo_bpm"].initial = song.default_tempo_bpm

    def clean_recording(self):
        uploaded = self.cleaned_data["recording"]
        if uploaded.size > _MAX_UPLOAD_BYTES:
            raise forms.ValidationError(
                f"file too large ({uploaded.size} bytes); max is "
                f"{_MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
            )
        # Extension check — content-type sniffing is unreliable across
        # browsers (audio/wave, audio/x-wav, audio/vnd.wave, audio/wav
        # are all real headers we'd see).
        name = (uploaded.name or "").lower()
        if "." not in name:
            raise forms.ValidationError(
                "file has no extension — please ensure the file is named "
                "with a .wav / .mp3 / .m4a / .flac / .aiff / .ogg suffix"
            )
        ext = "." + name.rsplit(".", 1)[1]
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise forms.ValidationError(
                f"unsupported audio format {ext!r}; allowed: "
                + ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
            )
        return uploaded

    def save(self, user) -> PracticeSession:
        """Persist the PracticeSession + Recording, returning the session.

        The recording file is written to storage via
        :func:`apps.practice.storage.store_upload`; the resulting
        ``file_ref`` is stored on the Recording row.
        """
        if not self.is_valid():
            raise ValueError("save() called on invalid form; check is_valid first")

        cd = self.cleaned_data
        session = PracticeSession.objects.create(
            user=user,
            song=cd["song"],
            target_preset=cd["target_preset"],
            tempo_bpm=cd["tempo_bpm"],
            notes=cd.get("notes", ""),
        )

        stored = store_upload(cd["recording"], cd["recording"].name)
        Recording.objects.create(
            session=session,
            file_ref=stored.file_ref,
            notes=(
                f"sha256={stored.sha256}; original={cd['recording'].name!r}"
            ),
        )
        return session


__all__ = ["PracticeSessionForm"]
