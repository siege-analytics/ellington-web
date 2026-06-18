"""Core views — invite acceptance + signup (epic #96 sub-ticket b / #108).

The invite acceptance flow lives in apps.core because it's about
identity / signup, not practice-flow. Recording-share materialization
on signup is a side-effect of redeeming the Invite — the view doesn't
need to know about Recording at all; the FK backfill does the work.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.http import HttpRequest, HttpResponse, HttpResponseGone
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods


User = get_user_model()


class InviteSignupForm(forms.Form):
    """Minimal signup form for the invite-acceptance flow.

    The Invite already supplies the email address (it's how the invite
    arrived), so we only ask for a username + password here.
    """

    username = forms.CharField(
        required=True,
        max_length=150,
        label="Pick a username",
        help_text="Letters, digits, and @/./+/-/_ — up to 150 characters.",
    )
    password1 = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        label="Password",
        min_length=8,
    )
    password2 = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        label="Confirm password",
        min_length=8,
    )

    def clean_username(self):
        username = (self.cleaned_data["username"] or "").strip()
        if not username:
            raise forms.ValidationError("username is required")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                f"username {username!r} is taken — try another"
            )
        return username

    def clean(self):
        cd = super().clean()
        if cd.get("password1") and cd.get("password2"):
            if cd["password1"] != cd["password2"]:
                raise forms.ValidationError("passwords don't match")
        return cd


@require_http_methods(["GET", "POST"])
def accept_invite(request: HttpRequest, token: str) -> HttpResponse:
    """Invite-acceptance + signup flow at /accounts/invite/<token>/."""
    from apps.practice.models import Invite, RecordingShare

    invite = Invite.objects.filter(token=token).first()
    if invite is None:
        return HttpResponseGone("This invite link is unrecognized.")
    if invite.is_expired():
        return HttpResponseGone(
            "This invite expired. Ask the sender to send a fresh one."
        )
    if invite.is_redeemed:
        return HttpResponseGone(
            "This invite has already been redeemed. Sign in instead."
        )

    pending_shares = list(
        RecordingShare.objects.filter(invite=invite)
        .select_related("sharer", "recording__session")
    )

    if request.method == "POST":
        form = InviteSignupForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            user = User.objects.create_user(
                username=cd["username"],
                email=invite.email,
                password=cd["password1"],
            )
            invite.accepted_at = timezone.now()
            invite.redeemed_by = user
            invite.save(update_fields=["accepted_at", "redeemed_by"])

            # Backfill recipient on all anchored RecordingShares
            shares_qs = RecordingShare.objects.filter(invite=invite)
            shares_qs.update(recipient=user, invite=None)

            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(
                request,
                f"Welcome, {user.username}! "
                f"{len(pending_shares)} recording(s) shared with you.",
            )
            return redirect("practice:shared_with_me")
    else:
        form = InviteSignupForm()

    return render(request, "core/accept_invite.html", {
        "form": form,
        "invite": invite,
        "pending_shares": pending_shares,
    })


# ---------------------------------------------------------------------------
# Self-service account deletion (epic #96 sub-ticket k / #112)
# ---------------------------------------------------------------------------


class SelfDeleteForm(forms.Form):
    """Confirm-by-typing-username form for self-service account deletion."""

    confirm_username = forms.CharField(
        required=True,
        max_length=150,
        label="Type your username to confirm",
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=2000,
        label="Reason (optional)",
        help_text="Helps us learn. Captured in the audit log, not"
        " forwarded to anyone.",
    )

    def __init__(self, *args, expected_username=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_username = expected_username

    def clean_confirm_username(self):
        value = (self.cleaned_data["confirm_username"] or "").strip()
        if self.expected_username and value != self.expected_username:
            raise forms.ValidationError(
                "username doesn't match — type it exactly as it"
                " appears in the form label"
            )
        return value


@require_http_methods(["GET", "POST"])
def self_delete_account(request: HttpRequest) -> HttpResponse:
    """Self-service account deletion at /accounts/delete/.

    Requires authentication. POST with matching confirm_username runs
    the full perform_account_deletion path; the request.user is both
    the target and the initiator.
    """
    from django.contrib.auth import logout
    from django.shortcuts import resolve_url

    from apps.core.deletion import perform_account_deletion

    if not request.user.is_authenticated:
        return redirect(f"{resolve_url('login')}?next={request.path}")

    if request.method == "POST":
        form = SelfDeleteForm(
            request.POST, expected_username=request.user.username,
        )
        if form.is_valid():
            try:
                perform_account_deletion(
                    request.user, initiated_by=request.user,
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                logout(request)
                return redirect("core:account_deleted")
    else:
        form = SelfDeleteForm(expected_username=request.user.username)

    return render(request, "core/account_delete.html", {
        "form": form,
        "user": request.user,
    })


def account_deleted(request: HttpRequest) -> HttpResponse:
    """Goodbye page at /accounts/deleted/."""
    return render(request, "core/account_deleted.html")


# ---------------------------------------------------------------------------
# Follow / feed / user profile (epic #96 sub-ticket h / #122)
# ---------------------------------------------------------------------------


@require_http_methods(["GET"])
def user_profile(request: HttpRequest, username: str) -> HttpResponse:
    """Public profile at /users/<username>/.

    Shows public Studios + follower/following counts + follow button
    state. Private content (private studios, sharing-only recordings)
    is gated and not surfaced.
    """
    from django.shortcuts import get_object_or_404

    from apps.practice.models import Studio, StudioVisibility

    from .models import Follow

    target = get_object_or_404(User, username=username, is_active=True)

    public_studios = list(
        Studio.objects.filter(
            owner=target, visibility=StudioVisibility.PUBLIC,
        )
    )

    follower_count = Follow.objects.filter(followed=target).count()
    following_count = Follow.objects.filter(follower=target).count()

    is_self = (
        request.user.is_authenticated and request.user.pk == target.pk
    )
    am_following = False
    if request.user.is_authenticated and not is_self:
        am_following = Follow.objects.filter(
            follower=request.user, followed=target,
        ).exists()

    return render(request, "core/user_profile.html", {
        "target": target,
        "public_studios": public_studios,
        "follower_count": follower_count,
        "following_count": following_count,
        "is_self": is_self,
        "am_following": am_following,
    })


@require_http_methods(["POST"])
def follow_user(request: HttpRequest, username: str) -> HttpResponse:
    """Follow a user. POST-only. Refuses self-follow."""
    from django.shortcuts import get_object_or_404

    from .models import Follow

    if not request.user.is_authenticated:
        from django.shortcuts import resolve_url
        return redirect(f"{resolve_url('login')}?next=/users/{username}/")

    target = get_object_or_404(User, username=username, is_active=True)
    if target.pk == request.user.pk:
        messages.error(request, "You can't follow yourself.")
        return redirect("core:user_profile", username=username)

    Follow.objects.get_or_create(follower=request.user, followed=target)
    messages.success(request, f"Following {target.username}.")
    return redirect("core:user_profile", username=username)


@require_http_methods(["POST"])
def unfollow_user(request: HttpRequest, username: str) -> HttpResponse:
    """Unfollow. POST-only. Idempotent."""
    from django.shortcuts import get_object_or_404

    from .models import Follow

    if not request.user.is_authenticated:
        return redirect("core:user_profile", username=username)

    target = get_object_or_404(User, username=username)
    Follow.objects.filter(follower=request.user, followed=target).delete()
    messages.info(request, f"Unfollowed {target.username}.")
    return redirect("core:user_profile", username=username)


@require_http_methods(["GET"])
def feed(request: HttpRequest) -> HttpResponse:
    """Followed-users activity feed at /feed/.

    v1 surface aggregates:
    - Public Studios created by followed users (recent first)
    - RuleComments by followed users (excluding deleted)

    Polled on page load. Real-time push is a v2 affordance.
    """
    if not request.user.is_authenticated:
        from django.shortcuts import resolve_url
        return redirect(f"{resolve_url('login')}?next=/feed/")

    from apps.practice.models import Studio, StudioVisibility
    from apps.rule_review.models import RuleComment

    from .models import Follow

    followed_ids = Follow.objects.filter(
        follower=request.user,
    ).values_list("followed_id", flat=True)

    recent_studios = (
        Studio.objects.filter(
            owner_id__in=followed_ids,
            visibility=StudioVisibility.PUBLIC,
        )
        .select_related("owner")
        .order_by("-created_at")[:20]
    )

    recent_comments = (
        RuleComment.objects.filter(
            author_id__in=followed_ids, deleted_at__isnull=True,
        )
        .select_related("author", "rule")
        .order_by("-created_at")[:20]
    )

    return render(request, "core/feed.html", {
        "recent_studios": recent_studios,
        "recent_comments": recent_comments,
    })
