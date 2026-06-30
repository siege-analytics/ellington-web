"""Forms for the practice-flow UI.

``PracticeSessionForm`` handles the create-session flow: pick a song,
pick a target style preset, set tempo, upload a recording. The form
returns a saved ``PracticeSession`` + ``Recording`` pair; storage of
the uploaded file is delegated to :mod:`apps.practice.storage`.
"""

from __future__ import annotations

from django import forms

from apps.audio.models import SoundBank
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
    # #244 — pick a sound bank from those discovered by
    # ``scan_sound_banks`` (#233). When set, the view dispatches
    # ``render_backing`` after persist so a canonical backing WAV is
    # available for time-alignment + per-slice analysis. Optional —
    # legacy sessions without a bank still work; they just won't have
    # a canonical backing.
    bank = forms.ModelChoiceField(
        queryset=SoundBank.objects.filter(is_active=True),
        required=False,
        label="Sound bank (for backing render)",
        help_text="Pick a discovered SoundBank to render a canonical "
        "backing track that the audio analysis aligns against. Leave "
        "blank to skip rendering.",
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

        # #244 — when a bank is picked, dispatch a Celery task to render
        # the canonical backing. The resulting BackingTrack row attaches
        # to the session later (via #235 task internals) so the audio
        # pipeline has something to align against. Dispatched .delay()
        # so form save stays fast; pulled out of save() into a tiny
        # helper so tests can patch the dispatch without mocking the
        # whole task chain.
        if cd.get("bank") is not None:
            self._dispatch_backing_render(
                session=session,
                song=cd["song"],
                bank=cd["bank"],
                tempo_bpm=cd["tempo_bpm"],
            )
        return session

    def _dispatch_backing_render(
        self, *, session: PracticeSession, song, bank, tempo_bpm: int,
    ) -> None:
        """Fire-and-forget Celery dispatch for the backing render.

        Pulled out so tests can patch this method without exercising the
        Celery wire. The task itself (#235) is idempotent on
        ``(song, bank, tempo, key)``; safe if the user submits the form
        twice with the same inputs.
        """
        from apps.audio.tasks import render_backing
        render_backing.delay(
            song_id=song.pk,
            bank_id=bank.pk,
            tempo_bpm=tempo_bpm,
            key=song.key or None,
        )


__all__ = ["PracticeSessionForm"]


# ---------------------------------------------------------------------------
# Recording sharing form (epic #96 sub-ticket b / #108)
# ---------------------------------------------------------------------------


class ShareRecordingForm(forms.Form):
    """Recording-sharing form. Two paths:

    - ``recipient`` (existing user, looked up by email or username) →
      RecordingShare with recipient set, no Invite
    - ``recipient_email`` (outsider) → Invite + RecordingShare with
      recipient=null, invite=<the invite>

    Exactly one path must be filled.
    """

    recipient_lookup = forms.CharField(
        required=False,
        max_length=255,
        label="Share with existing user (email or username)",
        help_text="If they already have an Ellington account, type their"
        " email or username here.",
    )
    recipient_email = forms.EmailField(
        required=False,
        label="Or invite by email",
        help_text="Type their email to send a fresh invitation.",
    )
    recipient_name = forms.CharField(
        required=False,
        max_length=128,
        label="Their name (optional)",
        help_text="Shown in the invitation email if you're inviting"
        " someone new.",
    )
    share_note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        max_length=2000,
        label="Note to recipient (optional)",
    )

    def __init__(self, *args, sharer=None, recording=None, **kwargs):
        # Stash for clean() / save() — set by the view.
        super().__init__(*args, **kwargs)
        self.sharer = sharer
        self.recording = recording

    def clean(self):
        from django.contrib.auth import get_user_model

        cd = super().clean()
        lookup = (cd.get("recipient_lookup") or "").strip()
        email = (cd.get("recipient_email") or "").strip()

        if lookup and email:
            raise forms.ValidationError(
                "pick existing user OR invite by email — not both"
            )
        if not lookup and not email:
            raise forms.ValidationError(
                "pick existing user OR enter an invite email"
            )

        if lookup:
            User = get_user_model()
            recipient = (
                User.objects.filter(email__iexact=lookup).first()
                or User.objects.filter(username__iexact=lookup).first()
            )
            if recipient is None:
                raise forms.ValidationError(
                    f"no existing user matches {lookup!r} —"
                    " try inviting by email instead"
                )
            if self.sharer and recipient.pk == self.sharer.pk:
                raise forms.ValidationError(
                    "you can't share a recording with yourself"
                )
            cd["_resolved_recipient"] = recipient

        return cd

    def save(self):
        """Create the RecordingShare (and maybe Invite). Returns
        ``(share, invite_or_none)``. Caller is responsible for sending
        the appropriate email.
        """
        import secrets
        from datetime import timedelta

        from django.utils import timezone

        from .models import Invite, RecordingShare

        if not self.is_valid():
            raise ValueError("save() called on invalid form")
        if not self.sharer or not self.recording:
            raise ValueError("ShareRecordingForm needs sharer + recording")

        cd = self.cleaned_data
        share_note = (cd.get("share_note") or "").strip()
        recipient = cd.get("_resolved_recipient")

        if recipient is not None:
            share = RecordingShare.objects.create(
                recording=self.recording,
                sharer=self.sharer,
                recipient=recipient,
                share_note=share_note,
            )
            return share, None

        # Invite path
        email = cd["recipient_email"].strip()
        token = secrets.token_urlsafe(32)
        invite = Invite.objects.create(
            token=token,
            inviter=self.sharer,
            email=email,
            name_hint=(cd.get("recipient_name") or "").strip(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        share = RecordingShare.objects.create(
            recording=self.recording,
            sharer=self.sharer,
            invite=invite,
            share_note=share_note,
        )
        return share, invite


__all__ = list(__all__) + ["ShareRecordingForm"]
