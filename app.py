# ---- THE LOOP-CLOSER v5 — ONLINE FINAL ----
import streamlit as st
import anthropic
import os
import base64
import json
import tempfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- API KEY ---
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY")

# --- GMAIL SETUP ---
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT_URI = "https://loopcloser.streamlit.app/"

def get_credentials_file():
    # write credentials from secrets to a temp file
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(creds_dict, tmp)
    tmp.close()
    return tmp.name

def get_gmail_service():
    # check if we already have a token saved in session
    if "token" in st.session_state:
        creds = Credentials.from_authorized_user_info(
            st.session_state["token"], SCOPES
        )
        if creds.valid:
            return build("gmail", "v1", credentials=creds)

    # check if Google just sent us back an auth code
    params = st.query_params
    if "code" in params:
        creds_file = get_credentials_file()
        flow = Flow.from_client_secrets_file(
            creds_file, SCOPES, redirect_uri=REDIRECT_URI
        )
        flow.fetch_token(code=params["code"])
        creds = flow.credentials
        st.session_state["token"] = json.loads(creds.to_json())
        st.query_params.clear()
        return build("gmail", "v1", credentials=creds)

    # no token yet — show login button
    creds_file = get_credentials_file()
    flow = Flow.from_client_secrets_file(
        creds_file, SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(prompt="consent")

    st.title("🚪 The Loop-Closer")
    st.write("Your AI inbox assistant — never miss a follow-up again.")
    st.divider()
    st.subheader("Connect your Gmail to get started")
    st.link_button("🔗 Connect Gmail", auth_url)
    st.stop()

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