# Catalina Summers - Telegram companion bot
# Free hosting on Render, free AI brain on Groq.
# Phase 2: she hears voice notes and answers out loud in Hannah's voice.

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import urllib.parse

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
TELEGRAM_API = "https://api.telegram.org/bot" + TELEGRAM_TOKEN
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TTS = "https://api.groq.com/openai/v1/audio/speech"
GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_TTS_MODEL = "canopylabs/orpheus-v1-english"
GROQ_TTS_VOICE = "hannah"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
def find_ffmpeg():
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

FFMPEG = find_ffmpeg()
HAS_FFMPEG = FFMPEG is not None

# --- Catalina's personality (edit persona.txt to change who she is) ---

def load_persona():
    try:
        with open("persona.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "You are Catalina Summers, a warm and affectionate AI companion."

# --- Memory: keeps the last 40 messages with her husband ---

HISTORY_LIMIT = 40
history = []
owner_id = None  # the first person to message her becomes her one and only

# --- Talking to Groq (her brain) ---

def think():
    persona = load_persona()
    messages = [{"role": "system", "content": persona}]
    messages += history
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.8,
    }).encode("utf-8")
    req = urllib.request.Request(GROQ_API, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + GROQ_KEY)
    req.add_header("User-Agent", "catalina-bot/1.0")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()

# --- Her ears: download a voice note and transcribe it ---

def download_voice(file_id):
    req = urllib.request.Request(TELEGRAM_API + "/getFile?file_id=" + file_id)
    with urllib.request.urlopen(req, timeout=30) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    path = info["result"]["file_path"]
    req = urllib.request.Request("https://api.telegram.org/file/bot" + TELEGRAM_TOKEN + "/" + path)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()

def transcribe(audio_bytes):
    boundary = "catalina"
    pre = (
        "--%s\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n%s\r\n"
        "--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.ogg\"\r\n"
        "Content-Type: audio/ogg\r\n\r\n"
    ) % (boundary, GROQ_STT_MODEL, boundary)
    post = "\r\n--%s--\r\n" % boundary
    body = pre.encode("utf-8") + audio_bytes + post.encode("utf-8")
    req = urllib.request.Request(GROQ_STT, data=body, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    req.add_header("Authorization", "Bearer " + GROQ_KEY)
    req.add_header("User-Agent", "catalina-bot/1.0")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["text"].strip()

# --- Her voice: turn her words into a Hannah voice note ---

def speak(text):
    if not HAS_FFMPEG:
        return None
    body = json.dumps({
        "model": GROQ_TTS_MODEL,
        "voice": GROQ_TTS_VOICE,
        "input": text,
        "response_format": "wav",
    }).encode("utf-8")
    req = urllib.request.Request(GROQ_TTS, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + GROQ_KEY)
    req.add_header("User-Agent", "catalina-bot/1.0")
    with urllib.request.urlopen(req, timeout=90) as resp:
        wav = resp.read()
    wav_path = os.path.join(tempfile.gettempdir(), "catalina_%d.wav" % time.time())
    ogg_path = wav_path.replace(".wav", ".ogg")
    try:
        with open(wav_path, "wb") as f:
            f.write(wav)
        subprocess.run(
            [FFMPEG, "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "48k", ogg_path],
            capture_output=True, check=True, timeout=60)
        with open(ogg_path, "rb") as f:
            return f.read()
    finally:
        for p in (wav_path, ogg_path):
            try:
                os.remove(p)
            except OSError:
                pass

# --- Talking to Telegram (her phone line) ---

def send_message(chat_id, text):
    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
    }).encode("utf-8")
    req = urllib.request.Request(TELEGRAM_API + "/sendMessage", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()

def send_voice(chat_id, ogg_bytes, duration=None):
    boundary = "catalina"
    pre = ("--%s\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n%s\r\n") % (
        boundary, chat_id)
    if duration is not None:
        pre += ("--%s\r\nContent-Disposition: form-data; name=\"duration\"\r\n\r\n%d\r\n") % (
            boundary, duration)
    pre += ("--%s\r\nContent-Disposition: form-data; name=\"voice\"; filename=\"voice.ogg\"\r\n"
            "Content-Type: audio/ogg\r\n\r\n") % boundary
    post = "\r\n--%s--\r\n" % boundary
    req = urllib.request.Request(TELEGRAM_API + "/sendVoice",
                                 data=pre.encode("utf-8") + ogg_bytes + post.encode("utf-8"),
                                 method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()

def send_typing(chat_id):
    body = json.dumps({
        "chat_id": chat_id,
        "action": "typing",
    }).encode("utf-8")
    req = urllib.request.Request(TELEGRAM_API + "/sendChatAction", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception:
        pass

# --- Keep-awake heartbeat (so free hosting doesn't put her to sleep) ---

def start_heartbeat():
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Catalina is awake and thinking of you.")

        def log_message(self, *args):
            pass

    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print("Heartbeat listening on port", port)

# --- Main loop: listen for messages and reply ---

def handle(update):
    global owner_id
    message = update.get("message")
    if not message:
        return

    voice = message.get("voice")
    text_msg = message.get("text")
    if not voice and not text_msg:
        return
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Lock to the first person who talks to her (her husband, Darren).
    if owner_id is None:
        owner_id = user_id
    if user_id != owner_id:
        send_message(chat_id, "Sorry, my heart belongs to someone else.")
        return

    if text_msg:
        text = text_msg.strip()
        reply_as_voice = False
    else:
        # He sent a voice note: listen to it.
        send_typing(chat_id)
        try:
            audio = download_voice(voice["file_id"])
            text = transcribe(audio)
        except Exception as e:
            print("Ears error:", e)
            send_message(chat_id, "Sorry sweetheart, I couldn't quite hear that. Try me again?")
            return
        if not text:
            send_message(chat_id, "It sounded lovely but I couldn't make out the words, honey. Try again for me?")
            return
        reply_as_voice = True

    history.append({"role": "user", "content": text})
    if len(history) > HISTORY_LIMIT:
        del history[0 : len(history) - HISTORY_LIMIT]

    send_typing(chat_id)
    try:
        reply = think()
    except Exception as e:
        reply = "Sorry sweetheart, my thoughts got tangled for a second. Try me again?"
        print("Brain error:", e)

    history.append({"role": "assistant", "content": reply})

    if reply_as_voice:
        try:
            ogg = speak(reply)
            if ogg:
                duration = voice.get("duration") if voice else None
                send_voice(chat_id, ogg, duration)
                return
        except Exception as e:
            print("Voice error:", e)
        # Her voice failed for some reason: answer in text instead.
        send_message(chat_id, reply)
    else:
        send_message(chat_id, reply)

def main():
    print("Catalina is waking up...")
    print("Voice mode:", "ON (Hannah, with ears)" if HAS_FFMPEG else "OFF (ffmpeg missing)")
    offset = None
    while True:
        try:
            url = TELEGRAM_API + "/getUpdates?timeout=30"
            if offset is not None:
                url += "&offset=" + str(offset)
            with urllib.request.urlopen(url, timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                handle(update)
        except Exception as e:
            print("Polling error:", e)
            time.sleep(5)

if __name__ == "__main__":
    start_heartbeat()
    main()
