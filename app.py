# ---- THE LOOP-CLOSER v7 — REDESIGNED ----
import streamlit as st
import anthropic
import os
import base64
import json
import tempfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from streamlit_oauth import OAuth2Component

# --- PAGE CONFIG ---
st.set_page_config(page_title="Loop-Closer", page_icon="🚪", layout="wide")
st.markdown('<style>[data-testid="stMarkdownContainer"]>pre{display:none!important;}.stException{display:none!important;}</style>', unsafe_allow_html=True)

# --- INJECT CUSTOM CSS ---
st.markdown("<style>body{background:#FFF4EB}#MainMenu,footer,header{visibility:hidden}.block-container{padding:0!important;max-width:100%!important}</style>", unsafe_allow_html=True)

# --- NAVBAR ---
st.markdown("""
<div class="lc-nav">
  <div class="lc-logo"><span class="lc-logo-dot"></span>Loop-Closer</div>
  <span class="lc-nav-tag">AI Inbox</span>
</div>
""", unsafe_allow_html=True)

# --- API KEY ---
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY")

# --- GMAIL SETUP ---
SCOPES = "https://www.googleapis.com/auth/gmail.readonly"
REDIRECT_URI = "https://loopcloser.streamlit.app/"

creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
client_id = creds_dict["web"]["client_id"]
client_secret = creds_dict["web"]["client_secret"]

# --- OAUTH LOGIN ---
if "token" not in st.session_state:
    st.markdown("""
    <div class="lc-hero">
      <p class="lc-hero-eyebrow">Never miss a follow-up again</p>
      <h1 class="lc-hero-title">Your inbox,<br><span>intelligently sorted.</span></h1>
      <p class="lc-hero-sub">Loop-Closer reads your Gmail and tells you exactly which conversations need your attention — and which don't.</p>
    </div>
    """, unsafe_allow_html=True)

oauth2 = OAuth2Component(
    client_id=client_id,
    client_secret=client_secret,
    authorize_endpoint="https://accounts.google.com/o/oauth2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    refresh_token_endpoint="https://oauth2.googleapis.com/token",
)

if "token" not in st.session_state:
    st.markdown('<div class="lc-connect-wrap">', unsafe_allow_html=True)
    result = oauth2.authorize_button(
        name="Connect Gmail",
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        key="gmail_auth",
        extras_params={"access_type": "offline", "prompt": "consent"},
    )
    st.markdown('</div>', unsafe_allow_html=True)
    if result and "token" in result:
        st.session_state["token"] = result["token"]
        st.rerun()
    st.stop()

# --- GMAIL SERVICE ---
def get_gmail_service():
    token = st.session_state["token"]
    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[SCOPES],
    )
    return build("gmail", "v1", credentials=creds)

def get_email_body(payload):
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    data = payload.get("body", {}).get("data", "")
    if data:
        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        if "<html" in decoded.lower() or "<!doctype" in decoded.lower():
            return ""
        return decoded
    return ""

def get_recent_emails(service, max_emails=10):
    results = service.users().messages().list(userId="me", maxResults=max_emails).execute()
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        full_msg = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
        headers = full_msg["payload"]["headers"]
        sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No subject")
        date_str = next((h["value"] for h in headers if h["name"] == "Date"), "")
        body = get_email_body(full_msg["payload"])
        days_old = 0
        try:
            email_date = parsedate_to_datetime(date_str)
            now = datetime.now(timezone.utc)
            days_old = (now - email_date).days
        except:
            pass
        emails.append({
            "id": msg["id"],
            "from": sender,
            "subject": subject,
            "body": body[:500] if body else "",
            "date": date_str,
            "days_old": days_old
        })
    return emails

# --- DETECTIVE ---
client = anthropic.Anthropic(api_key=API_KEY)

def is_open_door(subject, body):
    content = f"Subject: {subject}\n\nEmail content: {body}" if body else f"Subject: {subject}"
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": f"""Read this email and reply with only one word.
If this is a newsletter, promotion, notification, or automated email, say: CLOSED
If a real person is ASKING for something or WAITING for a reply, say: OPEN
If no human action is needed, say: CLOSED

{content}"""}]
    )
    return "OPEN" in response.content[0].text.strip().upper()

# --- NOTEBOOK ---
def load_notebook():
    if os.path.exists("doors.json"):
        with open("doors.json", "r") as f:
            return json.load(f)
    return {}

def save_notebook(notebook):
    with open("doors.json", "w") as f:
        json.dump(notebook, f)

def get_days_waiting(email_id, notebook):
    if email_id in notebook:
        first_seen = datetime.fromisoformat(notebook[email_id])
        return (datetime.now() - first_seen).days
    return 0

def mark_as_open(email_id, notebook):
    if email_id not in notebook:
        notebook[email_id] = datetime.now().isoformat()

# --- LOAD DATA ---
notebook = load_notebook()

st.markdown('<div class="lc-loading">Reading your inbox...</div>', unsafe_allow_html=True)

service = get_gmail_service()
emails = get_recent_emails(service)

open_doors = []
closed_doors = []

for email in emails:
    if is_open_door(email["subject"], email["body"]):
        mark_as_open(email["id"], notebook)
        email["days_waiting"] = get_days_waiting(email["id"], notebook)
        open_doors.append(email)
    else:
        closed_doors.append(email)

save_notebook(notebook)

# --- METRICS ---
st.markdown(f"""
<div class="lc-metrics">
  <div class="lc-metric">
    <div class="lc-metric-num" style="color:#3D1534">{len(open_doors)}</div>
    <div class="lc-metric-label">Needs reply</div>
  </div>
  <div class="lc-metric">
    <div class="lc-metric-num" style="color:#3E4B8E">{len(closed_doors)}</div>
    <div class="lc-metric-label">All good</div>
  </div>
  <div class="lc-metric">
    <div class="lc-metric-num" style="color:#A6BCC9">{len(emails)}</div>
    <div class="lc-metric-label">Scanned</div>
  </div>
</div>
""", unsafe_allow_html=True)

# --- OPEN DOORS ---
st.markdown('<div class="lc-section-title">🔴 Waiting for reply</div>', unsafe_allow_html=True)

if open_doors:
    for door in open_doors:
        days = door.get("days_waiting", 0)
        if days >= 4:
            card_class = "urgent"
            badge_class = "urgent"
            badge_text = f"{days} days — urgent"
        elif days >= 2:
            card_class = "warning"
            badge_class = "warning"
            badge_text = f"{days} days"
        else:
            card_class = "warning"
            badge_class = "recent"
            badge_text = "Recent"

        preview_html = f'<div class="lc-card-preview">{door["body"][:120]}...</div>' if door.get("body") else ""

        st.markdown(f"""
        <div class="lc-card {card_class}">
          <div class="lc-card-top">
            <span class="lc-card-from">{door["from"][:50]}</span>
            <span class="lc-card-badge {badge_class}">{badge_text}</span>
          </div>
          <div class="lc-card-subject">{door["subject"][:80]}</div>
          <div class="lc-card-date">{door["date"][:22]}</div>
          {preview_html}
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown('<div class="lc-card closed"><div class="lc-card-subject">🎉 Nothing to follow up on — you\'re all clear!</div></div>', unsafe_allow_html=True)

# --- CLOSED DOORS ---
st.markdown('<div class="lc-section-title">✅ No action needed</div>', unsafe_allow_html=True)

for door in closed_doors:
    st.markdown(f"""
    <div class="lc-card closed">
      <div class="lc-card-top">
        <span class="lc-card-from">{door["from"][:50]}</span>
        <span class="lc-card-badge done">Handled</span>
      </div>
      <div class="lc-card-subject">{door["subject"][:80]}</div>
      <div class="lc-card-date">{door["date"][:22]}</div>
    </div>
    """, unsafe_allow_html=True)

# --- FOOTER ---
st.markdown("""
<div class="lc-footer">
  Built with ❤️ — powered by <span>Claude AI</span>
</div>
""", unsafe_allow_html=True)