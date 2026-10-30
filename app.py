import streamlit as st
import requests

API_URL = "http://127.0.0.1:8000"
ASK_URL = f"{API_URL}/ask"
INGEST_URL = f"{API_URL}/ingest"

st.set_page_config(page_title="RAG Assistant", layout="wide")

st.title("🤖 RAG AI Assistant")

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Chat Bar Layout ---
col_pin, col_input = st.columns([1, 12])

# 📎 Pin button
with col_pin:
    if st.button("📎", help="Attach file"):
        st.session_state.show_uploader = True

# Show uploader only when pin clicked
if "show_uploader" not in st.session_state:
    st.session_state.show_uploader = False

if st.session_state.show_uploader:
    uploaded_file = st.file_uploader(
        "",
        type=["txt", "pdf", "docx", "md", "csv"],
        label_visibility="collapsed"
    )

    if uploaded_file:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        response = requests.post(INGEST_URL, files=files)

        if response.status_code == 200:
            st.success(response.json().get("message"))
        else:
            st.error("Upload failed")

        st.session_state.show_uploader = False

# Chat input
with col_input:
    prompt = st.chat_input("Type your message...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})

    response = requests.post(ASK_URL, json={"question": prompt})
    answer = response.json().get("answer", "No response")

    st.session_state.messages.append({"role": "assistant", "content": answer})

    st.rerun()