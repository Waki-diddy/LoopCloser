import streamlit as st

st.title("🚪 The Loop-Closer")
st.write("App is alive!")

try:
    creds = st.secrets["GOOGLE_CREDENTIALS"]
    st.success("✅ Google credentials loaded!")
except Exception as e:
    st.error(f"❌ Google credentials error: {e}")

try:
    key = st.secrets["ANTHROPIC_API_KEY"]
    st.success("✅ Anthropic key loaded!")
except Exception as e:
    st.error(f"❌ Anthropic key error: {e}")