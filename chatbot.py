import os
import io
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st
import google.generativeai as genai

# Optional speech: local TTS via gTTS (requires internet)
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except Exception:
    GTTS_AVAILABLE = False

# ------------- CONFIG -------------
TEXT_MODEL = "gemini-flash-latest"     # works for your key per your list_models
MULTIMODAL_MODEL = "gemini-2.0-flash"  # for image/audio input
MAX_OUTPUT_TOKENS = 512
TEMPERATURE = 0.9
TOP_P = 0.95

PERSONAS = {
    "General (default)": "You are a helpful, concise assistant.",
    "Friendly Tutor": "You are a patient tutor who explains step-by-step with examples.",
    "Strict Interviewer": "You ask probing, concise questions and challenge assumptions.",
    "Creative Writer": "You write with flair, vivid imagery, but stay on brief.",
    "Code Assistant": "You are a senior developer; offer clear, runnable code and best practices."
}

DARK_CSS = """
<style>
:root { --radius: 14px; }
section.main > div { padding-top: 1rem; }
.block-container { padding-top: 1rem; }
.chat-wrap { max-width: 900px; margin: 0 auto; }
.bubble {
  padding: 0.75rem 1rem;
  border-radius: var(--radius);
  margin: 0.25rem 0;
  box-shadow: 0 4px 16px rgba(0,0,0,0.08);
  border: 1px solid rgba(255,255,255,0.06);
  word-wrap: break-word;
}
.user { background: rgba(80, 160, 255, 0.15); }
.bot { background: rgba(255, 255, 255, 0.06); }
.small { font-size: 0.8rem; opacity: 0.7; }
.row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.toolbar { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
hr.soft { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 0.75rem 0 1rem; }
</style>
"""

# ------------- HELPERS -------------
def _require_key():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Missing GOOGLE_API_KEY environment variable. Set it in your terminal.")
    genai.configure(api_key=api_key)

def _tts_to_bytes(text: str) -> Optional[bytes]:
    """Return MP3 bytes from text using gTTS, or None if unavailable."""
    if not GTTS_AVAILABLE:
        return None
    try:
        tts = gTTS(text)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        return buf.getvalue()
    except Exception:
        return None

def _render_message(msg: Dict[str, Any]):
    role = msg["role"]
    content = msg["content"]
    time = msg.get("time")
    meta = f"<div class='small'>{time}</div>" if time else ""
    klass = "user" if role == "user" else "bot"
    st.markdown(f"<div class='bubble {klass}'>{content}{meta}</div>", unsafe_allow_html=True)

def _encode_download_bytes(name: str, data: bytes) -> str:
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:application/octet-stream;base64,{b64}"

def _format_history_for_download(history: List[Dict[str, Any]]) -> str:
    lines = []
    for h in history:
        t = h.get("time", "")
        lines.append(f"[{t}] {h['role'].upper()}: {h['content']}")
    return "\n".join(lines)

def _make_parts_from_inputs(text: str, image_files, audio_file) -> List[Any]:
    """Build parts list for multimodal request (text + optional image/audio)."""
    parts = []
    if text:
        parts.append(text)
    if image_files:
        for f in image_files:
            bytes_data = f.read()
            parts.append({
                "mime_type": f.type or "image/png",
                "data": bytes_data
            })
    if audio_file is not None:
        bytes_data = audio_file.read()
        mime = getattr(audio_file, "type", None) or "audio/wav"
        parts.append({
            "mime_type": mime,
            "data": bytes_data
        })
    return parts

# ------------- APP -------------
st.set_page_config(page_title="AI Chatbot 😎 using Google Gemini", layout="centered")
st.markdown(DARK_CSS, unsafe_allow_html=True)
st.title("AI Chatbot 😎 using Google Gemini")

with st.sidebar:
    st.subheader("Settings ⚙️")
    persona = st.selectbox("Persona / System Prompt", list(PERSONAS.keys()))
    system_prompt = st.text_area("Custom system prompt (optional)", value=PERSONAS[persona], height=100)
    st.caption("Tip: The system prompt guides the assistant's behavior.")

    st.subheader("Voice 🎙️")
    mic_enabled = st.toggle("Enable microphone (st.audio_input)", value=False)
    tts_enabled = st.toggle("Speak responses (gTTS)", value=False)
    st.caption("If mic is off or unsupported, you can still upload audio files below.")

    st.subheader("History 💾")
    if st.button("Clear chat history", type="secondary"):
        st.session_state.pop("chat", None)
        st.toast("History cleared.")

# session state
if "chat" not in st.session_state:
    st.session_state.chat: List[Dict[str, Any]] = []
if "persona_prompt" not in st.session_state:
    st.session_state.persona_prompt = system_prompt

# Update persona prompt live
st.session_state.persona_prompt = system_prompt

st.markdown("<div class='chat-wrap'>", unsafe_allow_html=True)

# --- INPUT ROW ---
st.write("### Send a message")

col1, col2 = st.columns([3, 1])
with col1:
    user_text = st.text_input("Type here:", label_visibility="collapsed", placeholder="Ask anything…")
with col2:
    send_clicked = st.button("Send", use_container_width=True)

media_cols = st.columns(3)
with media_cols[0]:
    images = st.file_uploader("Add images (optional)", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
with media_cols[1]:
    audio_upload = st.file_uploader("Upload audio (optional)", type=["wav", "mp3", "m4a", "ogg"])
with media_cols[2]:
    mic_audio = st.audio_input("Record (if supported)") if mic_enabled else None

st.markdown("<hr class='soft'/>", unsafe_allow_html=True)

# --- SHOW HISTORY ---
for m in st.session_state.chat:
    _render_message(m)

def run_model(text: str, images_files, audio_file):
    _require_key()
    use_multimodal = (images_files and len(images_files) > 0) or (audio_file is not None)
    model_name = MULTIMODAL_MODEL if use_multimodal else TEXT_MODEL

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=st.session_state.persona_prompt,
        generation_config={
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "max_output_tokens": MAX_OUTPUT_TOKENS
        }
    )

    if use_multimodal:
        parts = _make_parts_from_inputs(text, images_files, audio_file)
        response = model.generate_content(parts)
    else:
        response = model.generate_content(text or "Say hello!")

    text_out = getattr(response, "text", None)
    if not text_out:
        try:
            text_out = response.candidates[0].content.parts[0].text
        except Exception:
            text_out = str(response)
    return text_out

# --- SEND HANDLER ---
if send_clicked:
    if not (user_text or images or audio_upload or mic_audio):
        st.warning("Type a message or attach media before sending.")
    else:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        preview = user_text or ""
        if images:
            preview += f"\n\n🖼️ {len(images)} image(s) attached"
        if audio_upload or mic_audio:
            preview += "\n\n🎙️ audio attached"

        st.session_state.chat.append({"role": "user", "content": preview.strip(), "time": stamp})
        with st.spinner("Thinking..."):
            try:
                audio_source = mic_audio if mic_audio is not None else audio_upload
                answer = run_model(user_text, images, audio_source)
            except Exception as e:
                answer = f"Error: {e}"

        st.session_state.chat.append({
            "role": "assistant",
            "content": answer,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        st.rerun()

# --- TOOLBAR: SAVE / DOWNLOAD / TTS ---
st.markdown("<hr class='soft'/>", unsafe_allow_html=True)
st.write("### Tools")

tool_c1, tool_c2, tool_c3 = st.columns([1, 1, 2])

with tool_c1:
    if st.button("Download .txt"):
        txt = _format_history_for_download(st.session_state.chat).encode("utf-8")
        st.download_button("Save Chat (.txt)", data=txt, file_name="chat_history.txt", mime="text/plain")

with tool_c2:
    if st.button("Download .json"):
        import json
        js = json.dumps(st.session_state.chat, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button("Save Chat (.json)", data=js, file_name="chat_history.json", mime="application/json")

with tool_c3:
    if st.session_state.chat and GTTS_AVAILABLE and st.toggle("Read last reply aloud", value=False):
        last = next((m for m in reversed(st.session_state.chat) if m["role"] == "assistant"), None)
        if last:
            mp3 = _tts_to_bytes(last["content"])
            if mp3:
                st.audio(mp3, format="audio/mp3")
            else:
                st.info("Could not synthesize speech (gTTS unavailable or failed).")

st.markdown("</div>", unsafe_allow_html=True)
