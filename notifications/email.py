"""
Email notification support for the Meta Ads Management System.

Sends reports, alerts, webinar reminders, welcome emails, and offer emails
via the Resend API. All methods degrade gracefully when the RESEND_API_KEY
is missing or invalid.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import resend

from config.settings import EMAIL_FROM, EMAIL_TO, RESEND_API_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity configuration
# ---------------------------------------------------------------------------

_SEVERITY_COLORS: Dict[str, str] = {
    "critical": "#E74C3C",
    "warning": "#F39C12",
    "info": "#3498DB",
    "positive": "#2ECC71",
}

_SEVERITY_LABELS: Dict[str, str] = {
    "critical": "CRITICAL",
    "warning": "WARNING",
    "info": "INFO",
    "positive": "GOOD NEWS",
}


# ---------------------------------------------------------------------------
# HTML template helpers
# ---------------------------------------------------------------------------


def _base_template(title: str, body_html: str, preheader: str = "") -> str:
    """Wrap *body_html* in the YourBrand dark-themed email template.

    Args:
        title: Displayed as the main heading inside the email.
        body_html: Pre-rendered inner HTML content.
        preheader: Hidden preheader text shown in inbox previews.

    Returns:
        Complete HTML document string ready to send.
    """
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape_html(title)}</title>
<!--[if mso]>
<style>table,td {{font-family:Arial,sans-serif;}}</style>
<![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#0F1117;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">

<!-- Preheader (hidden inbox preview text) -->
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">
  {_escape_html(preheader)}
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0F1117;">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background-color:#1A1D27;border-radius:12px;overflow:hidden;border:1px solid #2A2D3A;">

        <!-- Header bar -->
        <tr>
          <td style="background:linear-gradient(135deg,#6C5CE7,#A855F7);padding:28px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td>
                  <span style="font-size:22px;font-weight:700;color:#FFFFFF;letter-spacing:-0.3px;">
                    YourBrand
                  </span>
                  <span style="font-size:22px;font-weight:300;color:rgba(255,255,255,0.85);letter-spacing:-0.3px;">
                    .ai
                  </span>
                </td>
              </tr>
              <tr>
                <td style="padding-top:12px;">
                  <span style="font-size:17px;font-weight:600;color:#FFFFFF;">
                    {_escape_html(title)}
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;color:#E2E8F0;font-size:15px;line-height:1.7;">
            {body_html}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:20px 32px;border-top:1px solid #2A2D3A;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="color:#64748B;font-size:12px;line-height:1.5;">
                  Sent by <strong style="color:#A855F7;">YourBrand.ai</strong>
                  Meta Ads Management System<br>
                  {datetime.now().strftime("%B %d, %Y at %H:%M")}
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for embedding user-supplied text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# EmailNotifier
# ---------------------------------------------------------------------------


class EmailNotifier:
    """Send email notifications via the Resend API.

    All public methods log a warning and return ``False`` when the
    ``RESEND_API_KEY`` is not configured, so callers never need to
    guard against missing settings.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
    ) -> None:
        """Initialise the Resend email notifier.

        Args:
            api_key: Resend API key. Falls back to ``settings.RESEND_API_KEY``.
            from_addr: Sender address. Falls back to ``settings.EMAIL_FROM``.
            to_addr: Default recipient address. Falls back to ``settings.EMAIL_TO``.
        """
        self._api_key: str = api_key or RESEND_API_KEY
        self._from_addr: str = from_addr or EMAIL_FROM
        self._to_addr: str = to_addr or EMAIL_TO

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_configured(self) -> bool:
        """Return ``True`` when enough config is present to attempt sending."""
        missing: list[str] = []
        if not self._api_key:
            missing.append("RESEND_API_KEY")
        if not self._from_addr:
            missing.append("EMAIL_FROM")

        if missing:
            logger.warning(
                "Resend email not configured (missing: %s). "
                "Set these in your .env file to enable email notifications.",
                ", ".join(missing),
            )
            return False
        return True

    def _resolve_to(self, to: Optional[str] = None) -> list[str]:
        """Resolve the recipient list.

        Args:
            to: Override recipient(s), comma-separated. Falls back to the
                default ``to_addr`` set at init time.

        Returns:
            A list of stripped email addresses.
        """
        raw = to or self._to_addr
        return [addr.strip() for addr in raw.split(",") if addr.strip()]

    # ------------------------------------------------------------------
    # Core send method
    # ------------------------------------------------------------------

    def send_email(
        self,
        subject: str,
        body: str,
        html: bool = False,
        to: Optional[str] = None,
    ) -> bool:
        """Send an email via the Resend API.

        Args:
            subject: Email subject line.
            body: Email body content (plain text or HTML).
            html: If ``True``, *body* is treated as HTML; otherwise plain text.
            to: Optional override recipient(s), comma-separated.

        Returns:
            ``True`` if the email was accepted by Resend.
        """
        if not self._is_configured():
            return False

        recipients = self._resolve_to(to)
        if not recipients:
            logger.warning("No recipients specified. Email not sent.")
            return False

        resend.api_key = self._api_key

        params: Dict[str, Any] = {
            "from": self._from_addr,
            "to": recipients,
            "subject": subject,
        }

        if html:
            params["html"] = body
        else:
            params["text"] = body

        try:
            result = resend.Emails.send(params)
            email_id = result.get("id", "unknown") if isinstance(result, dict) else getattr(result, "id", "unknown")
            logger.info("Email sent via Resend (id=%s): %s", email_id, subject)
            return True
        except resend.exceptions.ResendError as exc:
            logger.error("Resend API error sending '%s': %s", subject, exc)
            return False
        except Exception as exc:
            logger.error("Unexpected error sending email '%s': %s", subject, exc)
            return False

    # ------------------------------------------------------------------
    # Report emails
    # ------------------------------------------------------------------

    def send_report(
        self,
        report_text: str,
        report_type: str = "daily",
    ) -> bool:
        """Send a formatted report email with an HTML template.

        Args:
            report_text: The full report body (plain text, rendered in a
                         monospace ``<pre>`` block).
            report_type: Report label used in the subject line
                         (e.g. ``"daily"``, ``"weekly"``, ``"creative"``).

        Returns:
            ``True`` if the email was sent successfully.
        """
        title = f"Meta Ads {report_type.title()} Report"

        inner = (
            f'<pre style="background-color:#0F1117;border:1px solid #2A2D3A;'
            f"border-radius:8px;padding:20px;font-family:'Fira Code',Consolas,"
            f'monospace;font-size:13px;line-height:1.6;color:#E2E8F0;'
            f'overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">'
            f"{_escape_html(report_text)}"
            f"</pre>"
        )

        html_body = _base_template(
            title=title,
            body_html=inner,
            preheader=f"Your {report_type} Meta Ads report is ready.",
        )
        return self.send_email(title, html_body, html=True)

    # ------------------------------------------------------------------
    # Alert emails
    # ------------------------------------------------------------------

    def send_alert(
        self,
        alert_type: str,
        message: str,
        severity: str = "warning",
    ) -> bool:
        """Send an alert email with a severity-colored header.

        Args:
            alert_type: Short alert label (e.g. ``"creative_fatigue"``).
            message: Full alert description.
            severity: One of ``"critical"``, ``"warning"``, ``"info"``,
                      ``"positive"``.

        Returns:
            ``True`` if the email was sent successfully.
        """
        color = _SEVERITY_COLORS.get(severity, "#F39C12")
        label = _SEVERITY_LABELS.get(severity, "ALERT")
        subject = f"[{label}] Meta Ads: {alert_type}"

        severity_bar = (
            f'<div style="background-color:{color};border-radius:8px;'
            f'padding:14px 20px;margin-bottom:24px;">'
            f'<span style="color:#FFFFFF;font-weight:700;font-size:14px;'
            f'text-transform:uppercase;letter-spacing:0.5px;">'
            f"{_escape_html(label)}</span>"
            f"</div>"
        )

        details = (
            f"{severity_bar}"
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="margin-bottom:20px;">'
            f"<tr>"
            f'<td style="color:#94A3B8;padding:4px 16px 4px 0;font-size:13px;">'
            f"Alert Type</td>"
            f'<td style="color:#E2E8F0;font-weight:600;font-size:13px;">'
            f"{_escape_html(alert_type)}</td>"
            f"</tr>"
            f"<tr>"
            f'<td style="color:#94A3B8;padding:4px 16px 4px 0;font-size:13px;">'
            f"Severity</td>"
            f'<td style="color:{color};font-weight:600;font-size:13px;">'
            f"{severity.upper()}</td>"
            f"</tr>"
            f"</table>"
            f'<div style="background-color:#0F1117;border-radius:8px;'
            f'border:1px solid #2A2D3A;padding:20px;color:#E2E8F0;'
            f'font-size:14px;line-height:1.7;white-space:pre-wrap;">'
            f"{_escape_html(message)}"
            f"</div>"
        )

        html_body = _base_template(
            title=f"Alert: {alert_type}",
            body_html=details,
            preheader=f"{label} - {alert_type}: {message[:80]}",
        )
        return self.send_email(subject, html_body, html=True)

    # ------------------------------------------------------------------
    # Webinar reminder
    # ------------------------------------------------------------------

    def send_webinar_reminder(
        self,
        to: str,
        webinar_date: str,
        webinar_title: str,
    ) -> bool:
        """Send a webinar reminder email.

        Args:
            to: Recipient email address.
            webinar_date: Human-readable date/time string for the webinar.
            webinar_title: Title of the webinar.

        Returns:
            ``True`` if the email was sent successfully.
        """
        subject = f"Reminder: {webinar_title}"

        inner = (
            f'<div style="text-align:center;padding:16px 0 24px;">'
            f'<div style="display:inline-block;background-color:#6C5CE7;'
            f"border-radius:50%;width:64px;height:64px;line-height:64px;"
            f'text-align:center;font-size:28px;margin-bottom:16px;">'
            f"&#128197;</div>"
            f"</div>"
            f'<h2 style="color:#FFFFFF;font-size:20px;margin:0 0 8px;'
            f'text-align:center;">'
            f"{_escape_html(webinar_title)}</h2>"
            f'<p style="text-align:center;color:#A855F7;font-weight:600;'
            f'font-size:16px;margin:0 0 24px;">'
            f"{_escape_html(webinar_date)}</p>"
            f'<div style="background-color:#0F1117;border:1px solid #2A2D3A;'
            f'border-radius:8px;padding:20px;color:#E2E8F0;font-size:14px;'
            f'line-height:1.7;">'
            f"<p style=\"margin:0 0 12px;\">Hey there,</p>"
            f"<p style=\"margin:0 0 12px;\">Just a friendly reminder that "
            f"<strong>{_escape_html(webinar_title)}</strong> is coming up on "
            f"<strong>{_escape_html(webinar_date)}</strong>.</p>"
            f"<p style=\"margin:0;\">Make sure to mark your calendar and "
            f"show up ready to learn. We have some great insights to share!</p>"
            f"</div>"
            f'<div style="text-align:center;padding-top:28px;">'
            f'<a href="#" style="display:inline-block;background:linear-gradient'
            f"(135deg,#6C5CE7,#A855F7);color:#FFFFFF;text-decoration:none;"
            f"font-weight:600;font-size:15px;padding:14px 36px;"
            f'border-radius:8px;">Join the Webinar</a>'
            f"</div>"
        )

        html_body = _base_template(
            title="Webinar Reminder",
            body_html=inner,
            preheader=f"Your webinar '{webinar_title}' is on {webinar_date}",
        )
        return self.send_email(subject, html_body, html=True, to=to)

    # ------------------------------------------------------------------
    # Welcome email
    # ------------------------------------------------------------------

    def send_welcome_email(
        self,
        to: str,
        name: str,
    ) -> bool:
        """Send a welcome email to a new signup.

        Args:
            to: Recipient email address.
            name: First name (or full name) of the new user.

        Returns:
            ``True`` if the email was sent successfully.
        """
        subject = f"Welcome to YourBrand, {name}!"

        inner = (
            f'<h2 style="color:#FFFFFF;font-size:20px;margin:0 0 20px;">'
            f"Hey {_escape_html(name)}, welcome aboard!</h2>"
            f'<p style="color:#E2E8F0;font-size:15px;line-height:1.7;'
            f'margin:0 0 16px;">'
            f"We are thrilled to have you join the YourBrand community. "
            f"You have just taken the first step toward building something "
            f"amazing with AI.</p>"
            f'<div style="background-color:#0F1117;border:1px solid #2A2D3A;'
            f'border-radius:8px;padding:20px;margin:20px 0;">'
            f'<p style="color:#A855F7;font-weight:700;font-size:14px;'
            f'margin:0 0 12px;text-transform:uppercase;letter-spacing:0.5px;">'
            f"What happens next</p>"
            f'<ul style="color:#E2E8F0;font-size:14px;line-height:2;'
            f'margin:0;padding-left:20px;">'
            f"<li>Check your inbox for resources and next steps</li>"
            f"<li>Explore the platform and start building</li>"
            f"<li>Join our community for support and inspiration</li>"
            f"</ul>"
            f"</div>"
            f'<p style="color:#94A3B8;font-size:14px;line-height:1.7;">'
            f"If you have any questions, just reply to this email. "
            f"We are here to help!</p>"
            f'<div style="text-align:center;padding-top:24px;">'
            f'<a href="#" style="display:inline-block;background:linear-gradient'
            f"(135deg,#6C5CE7,#A855F7);color:#FFFFFF;text-decoration:none;"
            f"font-weight:600;font-size:15px;padding:14px 36px;"
            f'border-radius:8px;">Get Started</a>'
            f"</div>"
        )

        html_body = _base_template(
            title=f"Welcome, {name}!",
            body_html=inner,
            preheader=f"Welcome to YourBrand, {name}! Let's build something great together.",
        )
        return self.send_email(subject, html_body, html=True, to=to)

    # ------------------------------------------------------------------
    # Offer / pitch email
    # ------------------------------------------------------------------

    def send_offer_email(
        self,
        to: str,
        name: str,
        offer_name: str,
        offer_url: str,
    ) -> bool:
        """Send an offer or pitch email.

        Args:
            to: Recipient email address.
            name: Recipient name for personalisation.
            offer_name: Title of the offer/product.
            offer_url: URL to the offer landing page.

        Returns:
            ``True`` if the email was sent successfully.
        """
        subject = f"{name}, a special offer just for you"

        inner = (
            f'<h2 style="color:#FFFFFF;font-size:20px;margin:0 0 20px;">'
            f"Hey {_escape_html(name)},</h2>"
            f'<p style="color:#E2E8F0;font-size:15px;line-height:1.7;'
            f'margin:0 0 20px;">'
            f"We have something special for you. Based on your journey with "
            f"YourBrand, we think you will love this:</p>"
            f'<div style="background:linear-gradient(135deg,rgba(108,92,231,0.15),'
            f"rgba(168,85,247,0.15));border:1px solid #6C5CE7;"
            f'border-radius:12px;padding:28px;margin:20px 0;text-align:center;">'
            f'<h3 style="color:#A855F7;font-size:22px;font-weight:700;'
            f'margin:0 0 12px;">'
            f"{_escape_html(offer_name)}</h3>"
            f'<p style="color:#E2E8F0;font-size:14px;margin:0 0 24px;">'
            f"Take your AI-powered business to the next level.</p>"
            f'<a href="{_escape_html(offer_url)}" style="display:inline-block;'
            f"background:linear-gradient(135deg,#6C5CE7,#A855F7);"
            f"color:#FFFFFF;text-decoration:none;font-weight:700;"
            f"font-size:16px;padding:16px 44px;border-radius:8px;"
            f'letter-spacing:0.3px;">Claim Your Offer</a>'
            f"</div>"
            f'<p style="color:#94A3B8;font-size:13px;line-height:1.6;'
            f'margin-top:20px;">'
            f"This offer is available for a limited time. If you have "
            f"questions, simply reply to this email.</p>"
        )

        html_body = _base_template(
            title=f"Special Offer: {offer_name}",
            body_html=inner,
            preheader=f"{name}, check out {offer_name} - a special offer for you.",
        )
        return self.send_email(subject, html_body, html=True, to=to)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_notifier: Optional[EmailNotifier] = None


def get_notifier() -> EmailNotifier:
    """Return a module-level singleton :class:`EmailNotifier`.

    Creates the instance on first call; subsequent calls return the
    same object.
    """
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = EmailNotifier()
    return _default_notifier
