"""Permission helpers for the charts app (epic #96 sub-ticket c / #137).

Centralizes "can user X view/share Songbook Y?" so views + templates
don't re-implement the visibility + share + studio-member join.
"""

from __future__ import annotations

from .models import Songbook, SongbookShare, SongbookVisibility


def can_access_songbook(user, songbook: Songbook) -> bool:
    """True if ``user`` may read the Songbook.

    Access paths:
    - Songbook is public (open to any authenticated user)
    - User is the owner
    - User is a recipient of any SongbookShare for this Songbook
    - Visibility is studio AND user is a member of the linked Studio
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if songbook.visibility == SongbookVisibility.PUBLIC:
        return True

    if songbook.owner_id and songbook.owner_id == user.pk:
        return True

    if SongbookShare.objects.filter(
        songbook=songbook, recipient=user,
    ).exists():
        return True

    if (
        songbook.visibility == SongbookVisibility.STUDIO
        and songbook.studio_id is not None
    ):
        # Lazy import — keeps apps.charts decoupled from apps.practice
        # at module load.
        from apps.practice.models import StudioMember, StudioRole

        return StudioMember.objects.filter(
            studio_id=songbook.studio_id,
            user=user,
        ).exclude(role=StudioRole.BANNED).exists()

    return False


def is_songbook_owner(user, songbook: Songbook) -> bool:
    """True if ``user`` owns the Songbook."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return songbook.owner_id == user.pk


__all__ = ["can_access_songbook", "is_songbook_owner"]
