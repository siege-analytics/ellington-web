"""Permission helpers for the practice app.

Centralizes the "can user X view/comment-on Recording Y?" check so
views and templates don't repeat the join across Recording owner +
RecordingShare recipient + signed-in user. Used by the comments view
(#110) and will be the seam when sub-tickets b/c/d/e accumulate more
sharing modes.
"""

from __future__ import annotations

from .models import Recording, RecordingShare


def can_access_recording(user, recording: Recording) -> bool:
    """True if ``user`` may view + comment on the Recording.

    Access paths:
    - User owns the Recording (via PracticeSession.user)
    - User is the recipient of any RecordingShare for this Recording
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if recording.session.user_id == user.pk:
        return True
    return RecordingShare.objects.filter(
        recording=recording, recipient=user,
    ).exists()


def is_recording_owner(user, recording: Recording) -> bool:
    """True if ``user`` owns the Recording via its PracticeSession."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return recording.session.user_id == user.pk


__all__ = ["can_access_recording", "is_recording_owner"]
