# ---- THE LOOP-CLOSER v4 — FINAL ----
# Smarter + Prettier + Reminder Bell 🔔

import streamlit as st
import anthropic
import os
import base64
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- YOUR ANTHROPIC API KEY (loaded safely from .env file) ---
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY")
# --- GMAIL SETUP ---
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def get_email_body(payload):
    # try to get plain text version of email
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    # fallback to body directly
    data = payload.get("body", {}).get("data", "")
    if data:
        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        # if it looks like HTML, skip it
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
        # calculate how many days ago this email arrived
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

# --- THE REMINDER NOTEBOOK ---
NOTEBOOK_FILE = "doors.json"

def load_notebook():
    # load our saved notebook of open doors
    if os.path.exists(NOTEBOOK_FILE):
        with open(NOTEBOOK_FILE, "r") as f:
            return json.load(f)
    return {}

def save_notebook(notebook):
    with open(NOTEBOOK_FILE, "w") as f:
        json.dump(notebook, f)

def get_days_waiting(email_id, notebook):
    # how many days has this door been open in our notebook?
    if email_id in notebook:
        first_seen = datetime.fromisoformat(notebook[email_id])
        days = (datetime.now() - first_seen).days
        return days
    return 0

def mark_as_open(email_id, notebook):
    # write it in the notebook if it's new
    if email_id not in notebook:
        notebook[email_id] = datetime.now().isoformat()

# --- THE DETECTIVE ---
client = anthropic.Anthropic(api_key=API_KEY)

def is_open_door(subject, body):
    content = f"Subject: {subject}\n\nEmail content: {body}" if body else f"Subject: {subject}"
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[
            {
                "role": "user",
                "content": f"""Read this email and reply with only one word.
If the sender is ASKING for something, WAITING for a reply, or NEEDS action from you, say: OPEN
If the sender is just CONFIRMING, INFORMING, ANSWERING, or no reply is needed, say: CLOSED

{content}"""
            }
        ]
    )
    answer = response.content[0].text.strip().upper()
    return "OPEN" in answer

# --- DASHBOARD ---
st.set_page_config(
    page_title="Loop-Closer",
    page_icon="🚪",
    layout="wide"
)

st.title("🚪 The Loop-Closer")
st.caption("Your AI inbox assistant — never miss a follow-up again.")
st.divider()

# load the notebook
notebook = load_notebook()

with st.spinner("📬 Connecting to Gmail..."):
    service = get_gmail_service()
    emails = get_recent_emails(service)

open_doors = []
closed_doors = []

progress = st.progress(0, text="🕵️ Analysing your emails...")
for i, email in enumerate(emails):
    if is_open_door(email["subject"], email["body"]):
        mark_as_open(email["id"], notebook)
        days_waiting = get_days_waiting(email["id"], notebook)
        email["days_waiting"] = days_waiting
        open_doors.append(email)
    else:
        closed_doors.append(email)
    progress.progress((i + 1) / len(emails), text=f"🕵️ Analysed {i+1} of {len(emails)} emails...")

# save updated notebook
save_notebook(notebook)
progress.empty()

# --- SCORE SUMMARY ---
col1, col2, col3 = st.columns(3)
col1.metric("🔴 Needs reply", len(open_doors))
col2.metric("✅ All good", len(closed_doors))
col3.metric("📧 Total scanned", len(emails))

st.divider()

# --- OPEN DOORS WITH REMINDER BELL ---
st.subheader("🔴 Still waiting on these...")
if open_doors:
    for door in open_doors:
        days = door.get("days_waiting", 0)

        # pick the right urgency colour
        if days >= 4:
            bell = "🚨"
            urgency = f"URGENT — {days} days with no reply!"
        elif days >= 2:
            bell = "🟡"
            urgency = f"Getting old — {days} days waiting"
        else:
            bell = "🔔"
            urgency = "Recent — keep an eye on this"

        with st.expander(f"{bell} {door['from'][:50]} — {door['subject'][:60]}"):
            st.write(f"**From:** {door['from']}")
            st.write(f"**Subject:** {door['subject']}")
            st.write(f"**Date received:** {door['date']}")
            # show the reminder bell message
            if days >= 4:
                st.error(f"🚨 {urgency}")
            elif days >= 2:
                st.warning(f"🟡 {urgency}")
            else:
                st.info(f"🔔 {urgency}")
            if door['body']:
                st.write(f"**Preview:** {door['body'][:200]}")
else:
    st.success("🎉 Nothing to follow up on — you're all clear!")

st.divider()

# --- CLOSED DOORS ---
st.subheader("✅ No action needed")
if closed_doors:
    for door in closed_doors:
        with st.expander(f"✉️ {door['from'][:50]} — {door['subject'][:60]}"):
            st.write(f"**From:** {door['from']}")
            st.write(f"**Subject:** {door['subject']}")
            st.write(f"**Date:** {door['date']}")
else:
    st.info("No closed doors found.")

st.divider()
st.caption("Built with ❤️ by you — powered by Claude AI")