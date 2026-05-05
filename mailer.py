"""
Email mailer for the personalized crochet pattern report.

Supports SMTP fallback and Resend HTTPS API delivery.
"""

import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pathlib
from dotenv import load_dotenv
from itsdangerous import URLSafeSerializer

load_dotenv(pathlib.Path(__file__).parent / ".env")

EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp").strip().lower() or "smtp"
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
EMAIL_DRY_RUN = os.getenv("EMAIL_DRY_RUN", "false").strip().lower() == "true"
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "YOUR_REAL_EMAIL@gmail.com").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "true").strip().lower() != "false"
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("RESEND_FROM", "").strip()
RESEND_API_URL = os.getenv("RESEND_API_URL", "https://api.resend.com/emails").strip()
RESEND_TIMEOUT_SECONDS = float(os.getenv("RESEND_TIMEOUT_SECONDS", "20"))
RESEND_USER_AGENT = os.getenv("RESEND_USER_AGENT", "crochet-pattern-agent/1.0").strip()
UNSUBSCRIBE_SECRET = os.getenv("UNSUBSCRIBE_SECRET", os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me"))
EMAIL_PREVIEW_PATH = pathlib.Path(
    os.getenv("EMAIL_PREVIEW_PATH", pathlib.Path(__file__).parent / "logs" / "email_preview_latest.html")
)
MATERIALS_SECTION_HEADER = "\U0001F9F6 What You\u2019ll Need (Quick Buy Links)"
_LAST_SEND_ERROR: dict | None = None
BRAND_NAME = "StitchFlow Labs"
NEWSLETTER_NAME = "StitchFlow Labs Crochet Picks"

SKILL_COLORS = {
    "beginner": "#4CAF50",
    "intermediate": "#FF9800",
    "advanced": "#9C27B0",
}


def _unsubscribe_token(email: str) -> str:
    serializer = URLSafeSerializer(UNSUBSCRIBE_SECRET, salt="unsubscribe")
    return serializer.dumps({"email": email})


def _email_base_url() -> str:
    raw = os.getenv("SERVER_BASE_URL", "").strip().rstrip("/")
    if not raw:
        return ""

    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or host in blocked_hosts:
        return ""

    return f"{parsed.scheme}://{parsed.netloc}"


def _summary_text(found_count: int, original_count: int) -> str:
    parts = []
    if found_count:
        parts.append(f"{found_count} curated find{'s' if found_count != 1 else ''}")
    if original_count:
        parts.append(f"{original_count} original design{'s' if original_count != 1 else ''} created for you")
    return " + ".join(parts) if parts else "personalized picks"


def _mask_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email[:1] + "***" if email else ""
    local, domain = email.split("@", 1)
    masked_local = (local[:1] + "***") if local else "***"
    return f"{masked_local}@{domain}"


def _set_last_send_error(**payload) -> None:
    global _LAST_SEND_ERROR
    _LAST_SEND_ERROR = {k: v for k, v in payload.items() if v not in (None, "")}


def _clear_last_send_error() -> None:
    global _LAST_SEND_ERROR
    _LAST_SEND_ERROR = None


def last_send_error() -> dict | None:
    return dict(_LAST_SEND_ERROR) if _LAST_SEND_ERROR else None


def _email_provider() -> str:
    if EMAIL_PROVIDER in {"smtp", "resend"}:
        return EMAIL_PROVIDER
    return "smtp"


def _safe_from_value() -> str:
    if _email_provider() == "resend":
        return RESEND_FROM or "(missing RESEND_FROM)"
    if GMAIL_USER:
        return f"{BRAND_NAME} <{GMAIL_USER}>"
    return "(missing SMTP sender)"


def _reply_to_value() -> str:
    return REPLY_TO_EMAIL or ""


def transport_debug_summary() -> dict:
    return {
        "email_provider": _email_provider(),
        "email_provider_raw": EMAIL_PROVIDER,
        "email_dry_run": EMAIL_DRY_RUN,
        "safe_from": _safe_from_value(),
        "reply_to_configured": bool(_reply_to_value()),
        "reply_to_masked": _mask_email(_reply_to_value()),
        "smtp_host": SMTP_HOST,
        "smtp_port": SMTP_PORT,
        "smtp_use_ssl": SMTP_USE_SSL,
        "gmail_user_configured": bool(GMAIL_USER),
        "gmail_password_configured": bool(GMAIL_APP_PASSWORD),
        "resend_api_key_configured": bool(RESEND_API_KEY),
        "resend_from_configured": bool(RESEND_FROM),
        "resend_configured": bool(RESEND_API_KEY and RESEND_FROM),
        "resend_user_agent": RESEND_USER_AGENT,
    }


def _materials_html(materials: list, link_color: str = "#7B1FA2") -> str:
    if not materials:
        return "<li style='color:#888;'>See pattern page for full materials list</li>"
    items = []
    for m in materials:
        name = m.get("name", "")
        url = m.get("material_cta_url") or m.get("affiliate_url") or m.get("store_url") or ""
        cta_label = m.get("material_cta_label") or "Shop Materials"
        qty = m.get("quantity", "")
        qty_tag = f" <span style='color:#aaa;font-size:11px;'>({qty})</span>" if qty else ""
        if url:
            items.append(
                f"<li style='margin:0 0 12px;'>"
                f"<div style='font-weight:700;color:#4A235A;'>{name}{qty_tag}</div>"
                f"<div style='margin-top:4px;'><a href='{url}' style='color:{link_color};text-decoration:none;'>"
                f"&#128073; {cta_label}</a></div>"
                f"</li>"
            )
        else:
            items.append(
                f"<li style='margin:0 0 12px;'>"
                f"<div style='font-weight:700;color:#4A235A;'>{name}{qty_tag}</div>"
                f"</li>"
            )
    return "\n".join(items)


def _abbrev_html(abbrevs: dict) -> str:
    if not abbrevs:
        return ""
    rows = "".join(
        f"<tr><td style='padding:3px 10px 3px 0;font-weight:700;color:#7B5800;white-space:nowrap;'>"
        f"{k}</td><td style='padding:3px 0;color:#555;'>{v}</td></tr>"
        for k, v in abbrevs.items()
    )
    return f"""
    <p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#7B5800;">Abbreviations:</p>
    <table cellpadding="0" cellspacing="0" style="font-size:12px;margin-bottom:14px;">
      {rows}
    </table>"""


def _instructions_html(instructions: str) -> str:
    if not instructions:
        return ""
    lines = []
    for line in instructions.split("\n"):
        stripped = line.strip()
        if stripped and (stripped.isupper() or stripped.endswith(":")):
            lines.append(
                f"<span style='font-weight:700;color:#7B5800;display:block;"
                f"margin-top:10px;'>{stripped}</span>"
            )
        else:
            lines.append(
                f"<span style='display:block;line-height:1.7;'>{stripped}</span>"
            )
    return "\n".join(lines)


def _material_price_note(materials: list) -> str:
    if any(m.get("material_cta_url") or m.get("affiliate_url") or m.get("store_url") for m in materials or []):
        return (
            "<p style='margin:0 0 14px;font-size:11px;color:#888;'>"
            "Material links are optional shopping helpers. Price varies by retailer."
            "</p>"
        )
    return ""


def _tutorial_guidance_html(pattern: dict) -> str:
    guidance = pattern.get("tutorial_guidance")
    if not guidance:
        return ""
    return (
        '<table cellpadding="0" cellspacing="0" style="margin:0 0 14px;width:100%;">'
        '<tr><td style="background:#FFF8E1;border-left:4px solid #F9A825;'
        'padding:9px 12px;border-radius:0 6px 6px 0;">'
        f'<p style="margin:0;font-size:12px;color:#6D4C00;line-height:1.55;">'
        f'<strong>Tutorial search:</strong> {guidance}</p>'
        '</td></tr></table>'
    )


def _email_button(label: str, url: str, *, bg: str, margin: str = "0 0 8px") -> str:
    if not label or not url:
        return ""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:{margin};">'
        f'<tr><td><a href="{url}" style="display:block;padding:12px 16px;'
        f'background:{bg};color:#fff;text-decoration:none;border-radius:7px;'
        f'font-size:14px;font-weight:800;text-align:center;">{label}</a></td></tr>'
        f'</table>'
    )


def _compact_value(value: str, fallback: str) -> str:
    cleaned = (value or "").strip()
    return cleaned if cleaned else fallback


def _guided_tutorial_html(pattern: dict, action_text: str) -> str:
    skill = _compact_value(pattern.get("skill_level", ""), "beginner").capitalize()
    project = _compact_value(pattern.get("project_type", ""), "project").replace("_", " ").title()
    time_needed = _compact_value(pattern.get("estimated_time", ""), "a short session")
    has_tutorial = bool((pattern.get("video_tutorial") or {}).get("url"))
    start_items = [
        f"Materials: yarn, hook, and basic tools from the list below.",
        f"Time: {time_needed}.",
        f"Skill: {skill} {project.lower()}.",
    ]
    make_steps = [
        action_text,
        "Set out your yarn, hook, scissors, and needle.",
        "Read the first step before you start stitching.",
        "Make the first small section and check the size.",
        "Keep going in short sections so mistakes are easier to fix.",
    ]
    if has_tutorial:
        make_steps.append("Use the video if a step feels unclear.")

    watch_tips = [
        "Keep your loops relaxed, not tight.",
        "Count often so the edges stay even.",
        "Pause if the shape starts looking different from the pattern.",
    ]
    stuck_line = "If you get stuck, reread the last step, undo a small section, and try again slowly."
    start_html = "".join(f"<li style='margin:0 0 4px;'>{item}</li>" for item in start_items)
    make_html = "".join(f"<li style='margin:0 0 4px;'>{step}</li>" for step in make_steps[:6])
    tips_html = "".join(f"<li style='margin:0 0 4px;'>{tip}</li>" for tip in watch_tips)
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px;">'
        '<tr><td style="background:#F7FBFA;border:1px solid #D9ECE7;'
        'border-radius:8px;padding:11px 13px;">'
        '<p style="margin:0 0 6px;font-size:13px;font-weight:800;color:#176B63;">Start Here</p>'
        f'<ul style="margin:0 0 10px;padding-left:18px;font-size:13px;color:#3D372F;line-height:1.55;">{start_html}</ul>'
        '<p style="margin:0 0 6px;font-size:13px;font-weight:800;color:#176B63;">How to Make It</p>'
        f'<ol style="margin:0 0 10px;padding-left:18px;font-size:13px;color:#3D372F;line-height:1.55;">{make_html}</ol>'
        '<p style="margin:0 0 6px;font-size:13px;font-weight:800;color:#176B63;">What to Watch For</p>'
        f'<ul style="margin:0 0 10px;padding-left:18px;font-size:13px;color:#3D372F;line-height:1.55;">{tips_html}</ul>'
        f'<p style="margin:0;font-size:13px;color:#3D372F;line-height:1.55;"><strong>If You Get Stuck:</strong> {stuck_line}</p>'
        '</td></tr></table>'
    )


def _found_pattern_block(p: dict, idx: int) -> str:
    skill = p.get("skill_level", "")
    skill_color = SKILL_COLORS.get(skill, "#888")
    video = p.get("video_tutorial") or {}
    materials = p.get("materials", [])
    description = p.get("snippet") or p.get("why_its_perfect") or ""
    free_tag = "FREE" if p.get("is_free") else (p.get("price") or "Paid")
    free_bg = "#E8F5E9" if p.get("is_free") else "#FFF3E0"
    free_color = "#2E7D32" if p.get("is_free") else "#E65100"

    video_button = ""
    if video.get("url"):
        video_button = _email_button(
            "Watch Tutorial",
            video["url"],
            bg="#D84315",
            margin="0 0 14px",
        )

    pattern_cta_url = p.get("pattern_cta_url") or p.get("url") or ""
    pattern_button = _email_button("View Full Pattern", pattern_cta_url, bg="#6A1B9A")
    guided_tutorial = _guided_tutorial_html(p, "Open the full pattern page.")

    return f"""
<tr><td style="padding:0 32px 24px;">
  <table width="100%" cellpadding="0" cellspacing="0"
    style="border:1.5px solid #E8DEF8;border-radius:12px;overflow:hidden;background:#FFFFFF;
           box-shadow:0 2px 10px rgba(74,20,140,0.08);">
    <tr>
      <td style="background:linear-gradient(135deg,#6A1B9A,#AB47BC);
                 padding:10px 18px;color:#fff;">
        <span style="font-size:20px;font-weight:800;">#{idx}</span>
        <span style="font-size:13px;margin-left:8px;opacity:0.85;">
          {p.get("source_site","")}</span>
        <span style="float:right;background:{free_bg};color:{free_color};
          padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;">
          {free_tag}</span>
      </td>
    </tr>
    <tr><td style="padding:16px 18px;">
      <h3 style="margin:0 0 8px;font-size:17px;">
        <a href="{p.get('url','#')}" style="color:#6A1B9A;text-decoration:none;">
          {p.get("title","")}</a>
      </h3>
      {guided_tutorial}
      {pattern_button}
      {video_button}
      {f'<p style="margin:0 0 12px;font-size:13px;color:#666;line-height:1.7;">{description}</p>' if description else ''}
      <p style="margin:0 0 12px;font-size:12px;color:#888;">
        <span style="background:{skill_color};color:#fff;padding:2px 9px;
          border-radius:12px;">{skill.capitalize()}</span>&nbsp;
        <span style="background:#EDE7F6;color:#4A235A;padding:2px 9px;
          border-radius:12px;">{p.get("project_type","").replace("_"," ").title()}</span>&nbsp;
        <span style="background:#E8EAF6;color:#3949AB;padding:2px 9px;
          border-radius:12px;">Time {p.get("estimated_time","")}</span>&nbsp;
        <span style="background:#E0F2F1;color:#00695C;padding:2px 9px;
          border-radius:12px;">Hook {p.get("hook_size","")}</span>
      </p>
      <table cellpadding="0" cellspacing="0" style="margin-bottom:14px;width:100%;">
        <tr><td style="background:#F3E5F5;border-left:4px solid #9C27B0;
                       padding:10px 14px;border-radius:0 6px 6px 0;">
          <p style="margin:0;font-size:13px;color:#4A235A;font-style:italic;line-height:1.55;">
            <strong>Why it's perfect for you:</strong> {p.get("why_its_perfect","")}
          </p>
          {f'<p style="margin:6px 0 0;font-size:12px;color:#7B1FA2;">Color: {p.get("color_notes","")}</p>' if p.get("color_notes") else ""}
        </td></tr>
      </table>
      {f'<table cellpadding="0" cellspacing="0" style="margin-bottom:14px;width:100%;"><tr><td style="background:#FFF8E1;border-left:4px solid #FFA000;padding:8px 12px;border-radius:0 6px 6px 0;"><p style="margin:0;font-size:12px;color:#5D4037;"><strong>Usage note:</strong> {p["compliance_note"]}</p></td></tr></table>' if p.get("compliance_note") else ""}
      <p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#4A235A;">Materials:</p>
      <ul style="margin:0 0 14px;padding-left:20px;font-size:13px;color:#555;line-height:1.7;">
        {_materials_html(materials)}
      </ul>
      {_material_price_note(materials)}
    </td></tr>
  </table>
</td></tr>"""


def _original_pattern_block(p: dict, idx: int) -> str:
    skill = p.get("skill_level", "")
    skill_color = SKILL_COLORS.get(skill, "#888")
    materials = p.get("materials", [])
    abbrevs = p.get("abbreviations", {})
    instructions = p.get("instructions", "")
    notes = p.get("notes", [])
    notes_html = "".join(f"<li>{n}</li>" for n in notes) if notes else ""
    video = p.get("video_tutorial") or {}
    tutorial_html = ""
    if video.get("url"):
        tutorial_html = _email_button(
            "Watch Tutorial",
            video["url"],
            bg="#D84315",
            margin="0 0 14px",
        )
    instructions_anchor = f"pattern-{idx}-instructions"
    pattern_button = _email_button(
        "View Full Pattern",
        f"#{instructions_anchor}",
        bg="#F57F17",
        margin="0 0 8px",
    )
    guided_tutorial = _guided_tutorial_html(p, "Jump to the full instructions below.")

    return f"""
<tr><td style="padding:0 32px 24px;">
  <table width="100%" cellpadding="0" cellspacing="0"
    style="border:2px solid #F9A825;border-radius:12px;overflow:hidden;background:#FFFDF5;
           box-shadow:0 2px 10px rgba(245,127,23,0.10);">
    <tr>
      <td style="background:linear-gradient(135deg,#F57F17,#FBC02D);
                 padding:10px 18px;color:#fff;">
        <span style="font-size:20px;font-weight:800;">#{idx}</span>
        <span style="font-size:12px;margin-left:8px;background:rgba(255,255,255,0.25);
          padding:3px 10px;border-radius:12px;font-weight:700;display:inline-block;">
          Original Pattern | Created for You
        </span>
        <span style="float:right;background:rgba(255,255,255,0.3);color:#fff;
          padding:2px 10px;border-radius:12px;font-size:11px;font-weight:700;">FREE</span>
      </td>
    </tr>
    <tr><td style="padding:16px 18px;">
      <h3 style="margin:0 0 4px;font-size:17px;color:#7B5800;">
        {p.get("title","")}
      </h3>
      <p style="margin:0 0 12px;font-size:13px;color:#A1670A;font-style:italic;">
        {p.get("tagline","")}
      </p>
      {guided_tutorial}
      {pattern_button}
      {tutorial_html}
      {_tutorial_guidance_html(p)}
      <table cellpadding="0" cellspacing="0" style="margin:0 0 14px;width:100%;font-size:12px;color:#5F5366;">
        <tr>
          <td style="padding:4px 8px 4px 0;"><strong style="color:{skill_color};">Skill:</strong> {skill.capitalize()}</td>
          <td style="padding:4px 8px;"><strong style="color:#E65100;">Project:</strong> {p.get("project_type","").replace("_"," ").title()}</td>
        </tr>
        <tr>
          <td style="padding:4px 8px 4px 0;"><strong style="color:#7B5800;">Time:</strong> {p.get("estimated_time","")}</td>
          <td style="padding:4px 8px;"><strong style="color:#33691E;">Hook:</strong> {p.get("hook_size","")}</td>
        </tr>
        <tr>
          <td colspan="2" style="padding:4px 8px 4px 0;"><strong style="color:#6A1B9A;">Yarn:</strong> {p.get("yarn_weight","").capitalize()} weight</td>
        </tr>
      </table>
      <table cellpadding="0" cellspacing="0" style="margin-bottom:14px;width:100%;">
        <tr><td style="background:#FFF8E1;border-left:4px solid #FBC02D;
                       padding:10px 14px;border-radius:0 6px 6px 0;">
          <p style="margin:0;font-size:13px;color:#5D4037;font-style:italic;line-height:1.55;">
            <strong>Why we made this for you:</strong> {p.get("why_created","")}
          </p>
          {f'<p style="margin:6px 0 0;font-size:12px;color:#A1670A;">Color: {p.get("color_suggestion","")}</p>' if p.get("color_suggestion") else ""}
        </td></tr>
      </table>
      <p style="margin:0 0 4px;font-size:12px;color:#888;">
        <strong style="color:#7B5800;">Gauge:</strong> {p.get("gauge","")}&nbsp;&nbsp;
        <strong style="color:#7B5800;">Finished size:</strong> {p.get("finished_size","")}
      </p>
      <p style="margin:14px 0 6px;font-size:13px;font-weight:700;color:#7B5800;">
        Materials needed:
      </p>
      <ul style="margin:0 0 14px;padding-left:20px;font-size:13px;color:#555;line-height:1.7;">
        {_materials_html(materials, link_color="#A1670A")}
      </ul>
      {_material_price_note(materials)}
      {_abbrev_html(abbrevs)}
      <p id="{instructions_anchor}" style="margin:0 0 8px;font-size:13px;font-weight:700;color:#7B5800;">
        Pattern Instructions:
      </p>
      <div style="background:#FFF9C4;border:1px solid #FDD835;border-radius:8px;
                  padding:14px 16px;font-size:13px;font-family:monospace;
                  color:#333;line-height:1.7;margin-bottom:14px;">
        {_instructions_html(instructions)}
      </div>
      {f'<p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#7B5800;">Pattern Notes:</p><ul style="margin:0 0 14px;padding-left:20px;font-size:13px;color:#555;line-height:1.7;">{notes_html}</ul>' if notes_html else ""}
      <p style="margin:0;font-size:11px;color:#aaa;border-top:1px solid #FDD835;
                padding-top:10px;">
        Original StitchFlow Labs pattern for personal use. No external pattern link required.
      </p>
    </td></tr>
  </table>
</td></tr>"""


def build_html(user: dict, patterns: list[dict]) -> str:
    month = datetime.now().strftime("%B %Y")
    found = [p for p in patterns if not p.get("is_original")]
    originals = [p for p in patterns if p.get("is_original")]
    aesthetic = user.get("aesthetic", "")
    budget = user.get("budget", "")
    summary_text = _summary_text(len(found), len(originals))
    base_url = _email_base_url()
    unsubscribe_url = ""
    update_preferences_url = ""
    if base_url:
        unsubscribe_token = _unsubscribe_token(user["email"])
        unsubscribe_url = f"{base_url}/unsubscribe?token={unsubscribe_token}"
        update_preferences_url = base_url

    footer_links = []
    if unsubscribe_url:
        footer_links.append(
            f'<a href="{unsubscribe_url}" style="color:#9C27B0;text-decoration:none;">Unsubscribe</a>'
        )
    if update_preferences_url:
        footer_links.append(
            f'<a href="{update_preferences_url}" style="color:#9C27B0;text-decoration:none;">Update preferences</a>'
        )
    footer_links_html = "&nbsp;|&nbsp;".join(footer_links)

    intro_line = (
        f"Here is your latest StitchFlow Labs crochet edit: {summary_text}, tailored to your "
        f"<strong>{user['skill_level']}</strong> skill level"
        f"{f' and <strong>{aesthetic}</strong> aesthetic' if aesthetic else ''}"
        f"{f' with a <strong>{budget}</strong> budget' if budget else ''}."
    )
    found_section = ""
    if found:
        found_section = f"""
  <tr><td style="padding:10px 32px 10px;">
    <p style="margin:0;font-size:11px;font-weight:800;text-transform:uppercase;
              letter-spacing:1.2px;color:#9C27B0;">
      Curated from trusted sources
    </p>
  </td></tr>
  <table width="100%" cellpadding="0" cellspacing="0">
    {"".join(_found_pattern_block(p, i + 1) for i, p in enumerate(found))}
  </table>"""

    original_section = ""
    if originals:
        original_section = f"""
  <tr><td style="padding:{'10px' if not found else '6px'} 32px 10px;">
    <p style="margin:0;font-size:11px;font-weight:800;text-transform:uppercase;
              letter-spacing:1.2px;color:#F57F17;">
      Original patterns created by StitchFlow Labs
    </p>
  </td></tr>
  <table width="100%" cellpadding="0" cellspacing="0">
    {"".join(_original_pattern_block(p, len(found) + i + 1) for i, p in enumerate(originals))}
  </table>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<title>{NEWSLETTER_NAME}</title></head>
<body style="margin:0;padding:0;background:#F3EEF8;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:32px 12px;">
<table width="620" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:14px;overflow:hidden;
         box-shadow:0 4px 24px rgba(106,27,154,0.10);max-width:620px;">
  <tr><td style="background:linear-gradient(135deg,#4A148C,#9C27B0,#CE93D8);
                 padding:40px 36px 32px;text-align:center;">
    <div style="font-size:18px;line-height:1.2;margin-bottom:12px;font-weight:800;letter-spacing:1.1px;color:rgba(255,255,255,0.92);">
      STITCHFLOW LABS
    </div>
    <h1 style="margin:0 0 6px;color:#fff;font-size:25px;letter-spacing:0.5px;">
      Crochet Picks Made for You
    </h1>
    <p style="margin:0 0 10px;color:rgba(255,255,255,0.88);font-size:13px;line-height:1.6;">
      Original designs and curated finds selected for your next project.
    </p>
    <p style="margin:0;color:rgba(255,255,255,0.85);font-size:13px;">
      {month} - {summary_text}
    </p>
  </td></tr>
  <tr><td style="padding:30px 32px 18px;">
    <p style="margin:0 0 12px;font-size:20px;color:#333;font-weight:300;">
      Hey <strong style="color:#4A148C;">{user['name']}</strong>,
    </p>
    <p style="margin:0;font-size:15px;color:#555;line-height:1.8;">
      {intro_line}
    </p>
  </td></tr>
  {found_section}
  {original_section}
  <tr><td style="padding:18px 32px 30px;">
    <table width="100%" cellpadding="0" cellspacing="0"
      style="background:#FAF6FF;border:1px solid #EADCF8;border-radius:12px;">
      <tr><td style="padding:18px 18px 8px;">
        <p style="margin:0;font-size:16px;font-weight:800;color:#4A148C;">
          🧶 Materials You'll Need
        </p>
      </td></tr>
      <tr><td style="padding:0 18px 18px;">
        <p style="margin:0;font-size:13px;line-height:1.7;color:#6A5B75;">
          Each pattern card includes a linked materials list. If a product page is unavailable,
          we fall back to a safer search link so you can still find the right yarn, hook, or notion.
        </p>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:0 32px 26px;">
    <table width="100%" cellpadding="0" cellspacing="0"
      style="background:#FFFDF5;border:1px solid #F4D48A;border-radius:12px;">
      <tr><td style="padding:16px 18px;">
        <p style="margin:0 0 8px;font-size:16px;font-weight:800;color:#7B5800;">
          Help improve future pattern picks 💛
        </p>
        <p style="margin:0 0 8px;font-size:13px;line-height:1.7;color:#5D4037;">
          Reply to this email anytime with:
        </p>
        <ul style="margin:0 0 10px;padding-left:20px;font-size:13px;line-height:1.7;color:#5D4037;">
          <li>what confused you</li>
          <li>patterns you want more of</li>
          <li>screenshots of projects</li>
          <li>tutorial requests</li>
          <li>ideas that would make this easier</li>
        </ul>
        <p style="margin:0 0 6px;font-size:13px;font-weight:800;color:#7B5800;">
          Just hit reply — no forms needed.
        </p>
        <p style="margin:0;font-size:13px;line-height:1.7;color:#5D4037;">
          Real feedback directly shapes what gets added next.
        </p>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:0 32px 28px;">
    <p style="margin:0;font-size:15px;color:#4A235A;font-weight:600;">
      Happy crocheting!
    </p>
    <p style="margin:6px 0 0;font-size:13px;color:#999;">
      - {BRAND_NAME}
    </p>
  </td></tr>
  <tr><td style="background:#F5F0FA;padding:18px 32px;text-align:center;
                 border-top:1px solid #E8DEF8;">
    <p style="margin:0;font-size:12px;color:#aaa;">
      Bi-weekly crochet picks personalized just for you.
      {f'&nbsp;|&nbsp;{footer_links_html}' if footer_links_html else ''}
    </p>
    <p style="margin:8px 0 0;font-size:11px;color:#9A92A5;line-height:1.6;">
      Sent because you asked for personalized crochet recommendations. You can opt out any time.
    </p>
    <p style="margin:8px 0 0;font-size:11px;color:#9A92A5;line-height:1.6;">
      This email may contain affiliate links. We may earn a small commission at no extra cost to you.
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    normalized_lines = []
    for line in html.splitlines():
        if "Materials You'll Need" in line:
            normalized_lines.append(f"          {MATERIALS_SECTION_HEADER}")
        else:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _build_message_content(user: dict, patterns: list[dict]) -> tuple[str, str, str, str]:
    found = [p for p in patterns if not p.get("is_original")]
    originals = [p for p in patterns if p.get("is_original")]
    html = build_html(user, patterns)
    summary_text = _summary_text(len(found), len(originals))
    subject = f"{NEWSLETTER_NAME} ({summary_text})"

    plain = [f"Hey {user['name']}!", "", "Here are your personalized crochet patterns:", ""]
    for i, p in enumerate(found, 1):
        direct_url = p.get("url", "")
        fallback_url = p.get("pattern_search_url", "")
        link_line = ""
        if direct_url:
            link_line = f"   Link: {direct_url}"
        elif fallback_url:
            link_line = f"   Search Pattern: {fallback_url}"
        plain += [
            f"{i}. {p.get('title','')} ({p.get('source_site','')})",
            f"   Skill: {p.get('skill_level','').capitalize()} | Time: {p.get('estimated_time','')}",
            f"   Why: {p.get('why_its_perfect','')}",
            link_line,
            "",
        ]
    for i, p in enumerate(originals, len(found) + 1):
        plain += [
            f"{i}. [ORIGINAL PATTERN] {p.get('title','')}",
            f"   Skill: {p.get('skill_level','').capitalize()} | Time: {p.get('estimated_time','')}",
            f"   {p.get('why_created','')}",
            "",
        ]
    plain.append(f"Happy crocheting,\n{BRAND_NAME}")
    return subject, "\n".join(plain), html, summary_text


def _write_dry_run_preview(html: str) -> pathlib.Path:
    EMAIL_PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_PREVIEW_PATH.write_text(html, encoding="utf-8")
    return EMAIL_PREVIEW_PATH


def _valid_recipient(email: str) -> bool:
    _, parsed = parseaddr(email or "")
    if not parsed or parsed != (email or "").strip():
        return False
    local, sep, domain = parsed.rpartition("@")
    return bool(local and sep and domain and "." in domain and " " not in parsed)


def _send_via_smtp(
    user: dict,
    subject: str,
    plain: str,
    html: str,
    summary_text: str,
    effective_dry_run: bool,
) -> bool:
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        _set_last_send_error(
            provider="smtp",
            error="missing_smtp_credentials",
            message="SMTP credentials are not configured.",
        )
        print(
            "  [Mailer] ERROR: SMTP credentials not configured "
            f"(host={SMTP_HOST} port={SMTP_PORT} ssl={SMTP_USE_SSL})."
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{BRAND_NAME} <{GMAIL_USER}>"
    msg["To"] = user["email"]
    if _reply_to_value():
        msg["Reply-To"] = _reply_to_value()
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if SMTP_USE_SSL:
            smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        else:
            smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT)

        with smtp:
            if not SMTP_USE_SSL:
                smtp.starttls()
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_USER, user["email"], msg.as_string())
        print(f"  [Mailer] Sent to {user['email']} ({summary_text})")
        return True
    except Exception as e:
        _set_last_send_error(
            provider="smtp",
            error="smtp_send_failed",
            message=str(e),
        )
        print(
            f"  [Mailer] ERROR: {e} "
            f"(host={SMTP_HOST} port={SMTP_PORT} ssl={SMTP_USE_SSL} dry_run={effective_dry_run})"
        )
        return False


def _send_via_resend(user: dict, subject: str, plain: str, html: str, summary_text: str) -> bool:
    recipient_masked = _mask_email(user.get("email", ""))
    if not RESEND_API_KEY:
        _set_last_send_error(
            provider="resend",
            error="missing_resend_api_key",
            message="RESEND_API_KEY is missing. Add it as a Render secret.",
            recipient_masked=recipient_masked,
        )
        print("  [Mailer] ERROR: RESEND_API_KEY is missing. Add it as a Render secret.")
        return False
    if not RESEND_FROM:
        _set_last_send_error(
            provider="resend",
            error="missing_resend_from",
            message="RESEND_FROM is missing. Use a verified Resend sender.",
            recipient_masked=recipient_masked,
        )
        print(
            "  [Mailer] ERROR: RESEND_FROM is missing. "
            'Use a verified sender such as "StitchFlow Labs <patterns@stitchflowlabs.com>".'
        )
        return False

    payload = {
        "from": RESEND_FROM,
        "to": [user["email"]],
        "subject": subject,
        "text": plain,
        "html": html,
    }
    if _reply_to_value():
        payload["reply_to"] = [_reply_to_value()]
    request = Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": RESEND_USER_AGENT,
        },
        method="POST",
    )
    print(
        "  [Mailer] Resend request "
        f"recipient={recipient_masked} from={RESEND_FROM} user_agent={RESEND_USER_AGENT}"
    )

    try:
        with urlopen(request, timeout=RESEND_TIMEOUT_SECONDS) as response:
            status_code = response.status
            body = response.read().decode("utf-8", errors="replace")
        print(
            "  [Mailer] Resend accepted message "
            f"status={status_code} recipient={recipient_masked} ({summary_text})"
        )
        if body:
            print("  [Mailer] Resend response received.")
        return True
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = body[:500] if body else exc.reason
        friendly = None
        if exc.code == 403 and "1010" in detail:
            friendly = "Resend blocked the request because the HTTP User-Agent header was missing."
        _set_last_send_error(
            provider="resend",
            error="resend_rejected_request",
            status_code=exc.code,
            message=friendly or detail,
            resend_body=detail,
            recipient_masked=recipient_masked,
        )
        print(
            "  [Mailer] ERROR: Resend rejected request "
            f"status={exc.code} recipient={recipient_masked}: {detail}"
        )
        if friendly:
            print(f"  [Mailer] {friendly}")
        return False
    except (TimeoutError, URLError) as exc:
        _set_last_send_error(
            provider="resend",
            error="resend_network_error",
            message=f"Resend timeout/network error after {RESEND_TIMEOUT_SECONDS}s: {exc}",
            recipient_masked=recipient_masked,
        )
        print(
            "  [Mailer] ERROR: Resend timeout/network error "
            f"after {RESEND_TIMEOUT_SECONDS}s: {exc}"
        )
        return False
    except Exception as exc:
        _set_last_send_error(
            provider="resend",
            error="resend_send_failed",
            message=str(exc),
            recipient_masked=recipient_masked,
        )
        print(f"  [Mailer] ERROR: Resend send failed: {exc}")
        return False


def send_report(user: dict, patterns: list[dict], dry_run_override: bool | None = None) -> bool:
    _clear_last_send_error()
    effective_dry_run = EMAIL_DRY_RUN if dry_run_override is None else dry_run_override
    provider = _email_provider()
    recipient_masked = _mask_email(user.get("email", ""))
    print(
        f"  [Mailer] transport provider={provider} dry_run={effective_dry_run} "
        f"from={_safe_from_value()} recipient={recipient_masked}"
    )

    if effective_dry_run:
        _, _, html, _ = _build_message_content(user, patterns)
        preview_path = _write_dry_run_preview(html)
        print(f"  [Mailer] DRY RUN: would send report to {recipient_masked} via {provider}")
        print(f"  [Mailer] DRY RUN: preview saved to {preview_path}")
        return True

    if not _valid_recipient(user.get("email", "")):
        _set_last_send_error(
            provider=provider,
            error="invalid_recipient",
            message="Invalid recipient email address.",
            recipient_masked=recipient_masked,
        )
        print(f"  [Mailer] ERROR: invalid recipient address: {recipient_masked}")
        return False

    subject, plain, html, summary_text = _build_message_content(user, patterns)
    if provider == "resend":
        return _send_via_resend(user, subject, plain, html, summary_text)

    return _send_via_smtp(user, subject, plain, html, summary_text, effective_dry_run)
