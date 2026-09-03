"""Email delivery of the daily brief (plan 11, Phase 2).

Phase 3 replaces this with `expo-notifications`. Until then email is the
delivery mechanism, and it renders the brief's JSON — the same structured
output the app will render — rather than asking the model for HTML.

The styling follows the Glacier language in plan §10.3, restricted to what
mail clients actually support: inline styles, tables, no flexbox, no
webfonts.
"""

from __future__ import annotations

import html
import logging

import httpx

from app.config import Settings, get_settings
from app.models import Brief

log = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 20.0

# Glacier, dark, inlined (plan 10.3.1).
_BG = "#080B10"
_SURFACE = "#12171E"
_HAIRLINE = "#232A33"
_INK = "#EAF0F6"
_INK_2 = "#9BA9B8"
_INK_3 = "#68747F"
_ACCENT = "#5FD0E6"
_STATUS = {
    "green": "#7CC46A",
    "amber": "#E9A94A",
    "red": "#EE6C63",
    "insufficient_data": "#68747F",
}
_MONO = "'SFMono-Regular',Consolas,'Liberation Mono',monospace"
_SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


class EmailDeliveryError(RuntimeError):
    """Delivery failed. Recorded, not swallowed."""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _label(text: str) -> str:
    return (
        f'<div style="font-family:{_MONO};font-size:10px;letter-spacing:1.4px;'
        f'text-transform:uppercase;color:{_INK_3};padding:0 0 8px">{_esc(text)}</div>'
    )


def render_html(brief: Brief, *, checkin_url: str | None = None) -> str:
    """The brief as an email. Every number comes from the stored output."""
    output = brief.output or {}
    snapshot = brief.input_snapshot or {}
    status = output.get("status", "insufficient_data")
    accent = _STATUS.get(status, _INK_3)
    readiness = (snapshot.get("readiness") or {}).get("score")
    completeness = snapshot.get("data_completeness_pct")

    def section(title: str, body: str) -> str:
        if not body:
            return ""
        return f'<tr><td style="padding:22px 24px 0">{_label(title)}{body}</td></tr>'

    why = "".join(
        f'<div style="border-left:2px solid {_HAIRLINE};padding:0 0 0 12px;margin:0 0 14px">'
        f'<div style="color:{_INK};font-size:15px;line-height:1.5">{_esc(item.get("observation"))}'
        f'<span style="font-family:{_MONO};font-size:9px;letter-spacing:1px;'
        f"text-transform:uppercase;color:{_INK_3};border:1px solid {_HAIRLINE};"
        f'border-radius:4px;padding:1px 5px;margin-left:8px">'
        f"{_esc(item.get('confidence'))}</span></div>"
        f'<div style="font-family:{_MONO};font-size:12px;color:{_INK_2};padding-top:4px">'
        f"{_esc(item.get('evidence'))}</div></div>"
        for item in output.get("why", [])
    )

    do_today = "".join(
        f'<div style="margin:0 0 10px"><span style="font-family:{_MONO};font-size:10px;'
        f"color:{_ACCENT};border:1px solid {_HAIRLINE};border-radius:5px;padding:2px 6px;"
        f'margin-right:8px">{_esc(item.get("priority"))}</span>'
        f'<span style="color:{_INK};font-size:15px">{_esc(item.get("action"))}</span>'
        f'<div style="color:{_INK_2};font-size:13px;padding:3px 0 0 30px">'
        f"{_esc(item.get('rationale'))}</div></div>"
        for item in output.get("do_today", [])
    )

    def bullets(items: list) -> str:
        return "".join(
            f'<div style="color:{_INK_2};font-size:14px;padding:0 0 6px">— {_esc(i)}</div>'
            for i in items
        )

    supplement_note = output.get("supplement_note")
    supplements = _esc(supplement_note) if supplement_note else ""

    recommendation = output.get("training_recommendation") or {}
    training = (
        f'<div style="background:{_SURFACE};border:1px solid {_HAIRLINE};border-radius:12px;'
        f'padding:14px 16px"><div style="font-family:{_MONO};font-size:11px;letter-spacing:1.2px;'
        f'text-transform:uppercase;color:{_INK};padding-bottom:6px">'
        f"{_esc(str(recommendation.get('verdict', '')).replace('_', ' '))}</div>"
        f'<div style="color:{_INK_2};font-size:14px;line-height:1.5">'
        f"{_esc(recommendation.get('rationale'))}</div></div>"
        if recommendation
        else ""
    )

    caveats = "".join(
        f'<div style="border-left:2px solid {_STATUS["amber"]};padding-left:12px;'
        f'color:{_INK_2};font-size:13px;margin:0 0 6px">{_esc(c)}</div>'
        for c in output.get("data_caveats", [])
    )

    cta = (
        f'<tr><td style="padding:24px"><a href="{_esc(checkin_url)}" '
        f'style="display:block;background:{_ACCENT};color:#04161C;text-decoration:none;'
        f'font-weight:700;font-size:15px;text-align:center;padding:14px;border-radius:12px">'
        f"Check in</a></td></tr>"
        if checkin_url
        else ""
    )

    readiness_line = (
        f"{'—' if readiness is None else _esc(readiness)}"
        f'<span style="font-family:{_MONO};font-size:11px;color:{_INK_3};'
        f'letter-spacing:1px"> / 100</span>'
    )

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{_BG};font-family:{_SANS}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{_BG};padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="max-width:560px;background:{_SURFACE};border:1px solid {_HAIRLINE};
              border-radius:18px;overflow:hidden">

  <tr><td style="padding:24px 24px 0">
    <div style="font-family:{_MONO};font-size:10px;letter-spacing:1.4px;
                text-transform:uppercase;color:{_INK_3}">
      {_esc(brief.date.isoformat())} &nbsp;·&nbsp; {_esc(brief.phase)}
      &nbsp;·&nbsp; {_esc(completeness)}% complete
    </div>
    <div style="color:{accent};font-family:{_MONO};font-size:34px;font-weight:600;
                padding:14px 0 2px">{readiness_line}</div>
    <div style="font-family:{_MONO};font-size:10px;letter-spacing:1.4px;
                text-transform:uppercase;color:{accent}">{_esc(status)}</div>
    <div style="color:{_INK};font-size:21px;line-height:1.35;font-weight:600;
                padding:18px 0 0">{_esc(output.get("headline"))}</div>
  </td></tr>

  {section("What the data shows", why)}
  {section("Do today", do_today)}
  {section("Avoid today", bullets(output.get("avoid_today", [])))}
  {section("Watch", bullets(output.get("watch_items", [])))}
  {section("Training", training)}
  {section("Supplements", supplements)}
  {section("Caveats", caveats)}
  {cta}

  <tr><td style="padding:8px 24px 24px;border-top:1px solid {_HAIRLINE}">
    <div style="font-family:{_MONO};font-size:10px;color:{_INK_3};letter-spacing:1px">
      Not a medical device. Every figure computed by the metrics engine;
      prompt {_esc(brief.prompt_version)}.
    </div>
  </td></tr>

</table></td></tr></table></body></html>"""


def send_brief(brief: Brief, settings: Settings | None = None) -> str:
    """Deliver one brief. Returns the provider's message id.

    Raises `EmailDeliveryError` rather than returning quietly: a brief that
    was generated but never arrived is exactly the silent failure the sync-run
    bookkeeping exists to prevent.
    """
    settings = settings or get_settings()
    if not settings.resend_api_key:
        raise EmailDeliveryError("RESEND_API_KEY is not set.")
    if not settings.brief_email_to:
        raise EmailDeliveryError("BRIEF_EMAIL_TO is not set.")

    status = (brief.output or {}).get("status", "")
    subject = f"{brief.date.strftime('%a %d %b')} · {status or 'brief'}"

    try:
        response = httpx.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.brief_email_from,
                "to": [settings.brief_email_to],
                "subject": subject,
                "html": render_html(brief, checkin_url=settings.checkin_url),
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EmailDeliveryError(f"Resend rejected the brief: {exc}") from exc

    message_id = response.json().get("id", "")
    log.info("Brief for %s delivered (%s)", brief.date, message_id)
    return message_id


def mark_delivered(session, brief: Brief, via: str = "email") -> None:
    brief.delivered_via = via
    session.commit()
