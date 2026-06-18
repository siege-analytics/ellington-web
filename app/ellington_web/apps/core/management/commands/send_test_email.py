"""Send a one-line test email — used to verify SMTP plumbing.

Designed to be run from a pod shell on the cluster after the
``ellington-email`` Secret + ``ellington-config`` ConfigMap are wired
into the Deployment:

    kubectl exec -it deploy/ellington-web -- \
        python ellington_web/manage.py send_test_email steve@blackmon.org

Emits the configured FROM_EMAIL + REPLY_TO_EMAIL so misconfigured
sender envelopes are obvious from the recipient side.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a one-line test email to verify SMTP plumbing."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient",
            help="Email address to send the test to.",
        )

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        if "@" not in recipient:
            raise CommandError(f"not a plausible email address: {recipient!r}")

        reply_to = getattr(settings, "REPLY_TO_EMAIL", None)
        from_email = settings.DEFAULT_FROM_EMAIL

        msg = EmailMessage(
            subject="Ellington email plumbing OK",
            body=(
                "If you can read this, Django's SMTP backend is wired"
                f" correctly.\n\nFrom: {from_email}\n"
                f"Reply-To: {reply_to}\n"
                f"Host: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}\n"
            ),
            from_email=from_email,
            to=[recipient],
            reply_to=[reply_to] if reply_to else None,
        )
        sent = msg.send(fail_silently=False)
        if sent != 1:
            raise CommandError(
                f"EmailMessage.send() returned {sent}; expected 1."
            )
        self.stdout.write(self.style.SUCCESS(
            f"sent test email to {recipient} via {settings.EMAIL_HOST}"
        ))
