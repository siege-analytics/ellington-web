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
