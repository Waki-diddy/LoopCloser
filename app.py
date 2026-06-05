# ---- THE LOOP-CLOSER v6 — STREAMLIT OAUTH ----
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

# --- API KEY ---
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY")

# --- GMAIL SETUP ---
SCOPES = "https://www.googleapis.com/auth/gmail.readonly"
REDIRECT_URI = "https://loopcloser.streamlit.app/"

# --- PAGE CONFIG ---
st.set_page_config(page_title="Loop-Closer", page_icon="🚪", layout="wide")
st.title("🚪 The Loop-Closer")
st.caption("Your AI inbox assistant — never miss a follow-up again.")
st.divider()

# --- OAUTH LOGIN ---
creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
client_id = creds_dict["web"]["client_id"]
client_secret = creds_dict["web"]["client_secret"]

oauth2 = OAuth2Component(
    client_id=client_id,
    client_secret=client_secret,
    authorize_endpoint="https://accounts.google.com/o/oauth2/auth",
    token_endpoint="https://oauth2.googleapis.com/token",
    refresh_token_endpoint="https://oauth2.googleapis.com/token",
)

if "token" not in st.session_state:
    result = oauth2.authorize_button(
        name="🔗 Connect Gmail",
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        key="gmail_auth",
        extras_params={"access_type": "offline", "prompt": "consent"},
    )
    if result and "token" in result:
        st.session_state["token"] = result["token"]
        st.rerun()
    else:
        st.stop()

# --- BUILD GMAIL SERVICE ---
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
    results = service.users().messages().list(
        userId="me", maxResults=max_emails
    ).execute()
    messages = results.get("messages", [])
    emails = []
    for msg in messages:
        full_msg = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()
        headers = full_msg["payload"]["headers"]
        sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No subject")
        date_str = next((h["value"] for h in headers if h["name"] == "Date"), "")
        body = get_email_body(full_msg["payload"])
        body_preview = body[:500] if body else ""
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
            "body": body_preview,
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
NOTEBOOK_FILE = "doors.json"

def load_notebook():
    if os.path.exists(NOTEBOOK_FILE):
        with open(NOTEBOOK_FILE, "r") as f:
            return json.load(f)
    return {}

def save_notebook(notebook):
    with open(NOTEBOOK_FILE, "w") as f:
        json.dump(notebook, f)

def get_days_waiting(email_id, notebook):
    if email_id in notebook:
        first_seen = datetime.fromisoformat(notebook[email_id])
        return (datetime.now() - first_seen).days
    return 0

def mark_as_open(email_id, notebook):
    if email_id not in notebook:
        notebook[email_id] = datetime.now().isoformat()

# --- MAIN DASHBOARD ---
notebook = load_notebook()

with st.spinner("📬 Reading your Gmail..."):
    service = get_gmail_service()
    emails = get_recent_emails(service)

open_doors = []
closed_doors = []

progress = st.progress(0, text="🕵️ Analysing your emails...")
for i, email in enumerate(emails):
    if is_open_door(email["subject"], email["body"]):
        mark_as_open(email["id"], notebook)
        email["days_waiting"] = get_days_waiting(email["id"], notebook)
        open_doors.append(email)
    else:
        closed_doors.append(email)
    progress.progress((i + 1) / len(emails), text=f"🕵️ Analysed {i+1} of {len(emails)} emails...")

save_notebook(notebook)
progress.empty()

col1, col2, col3 = st.columns(3)
col1.metric("🔴 Needs reply", len(open_doors))
col2.metric("✅ All good", len(closed_doors))
col3.metric("📧 Total scanned", len(emails))

st.divider()

st.subheader("🔴 Still waiting on these...")
if open_doors:
    for door in open_doors:
        days = door.get("days_waiting", 0)
        bell = "🚨" if days >= 4 else "🟡" if days >= 2 else "🔔"
        urgency = f"URGENT — {days} days!" if days >= 4 else f"Getting old — {days} days" if days >= 2 else "Recent — keep an eye on this"
        with st.expander(f"{bell} {door['from'][:50]} — {door['subject'][:60]}"):
            st.write(f"**From:** {door['from']}")
            st.write(f"**Subject:** {door['subject']}")
            st.write(f"**Date:** {door['date']}")
            if days >= 4:
                st.error(f"🚨 {urgency}")
            elif days >= 2:
                st.warning(f"🟡 {urgency}")
            else:
                st.info(f"🔔 {urgency}")
            if door['body']:
                st.write(f"**Preview:** {door['body'][:200]}")
else:
    st.success("🎉 Nothing to follow up on!")

st.divider()

st.subheader("✅ No action needed")
for door in closed_doors:
    with st.expander(f"✉️ {door['from'][:50]} — {door['subject'][:60]}"):
        st.write(f"**From:** {door['from']}")
        st.write(f"**Subject:** {door['subject']}")
        st.write(f"**Date:** {door['date']}")

st.divider()
st.caption("Built with ❤️ by you — powered by Claude AI")