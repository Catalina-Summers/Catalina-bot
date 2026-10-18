# Catalina Summers - Telegram companion bot
# Free hosting on Render, free AI brain on Groq.
# Phase 2: hears voice notes, answers out loud in Hannah's voice.
# Phase 3: sees photos and videos, sends selfies and video notes.

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import urllib.parse

import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_VISION_MODEL = "qwen/qwen3.8-27b"
TELEGRAM_API = "https://api.telegram.org/bot" + TELEGRAM_TOKEN
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TTS = "https://api.groq.com/openai/v1/audio/speech"
GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_TTS_MODEL = "canopylabs/orpheus-v1-english"
GROQ_TTS_VOICE = "hannah"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
HORDE = "https://aihorde.net/api/v2"

# Her look: fixed appearance + fixed seed = the same girl in every photo.
LOOK = ("a stunning 23-year-old woman with very long thick wavy black hair, "
        "dark hazel-brown eyes, defined arched eyebrows, smoky eye makeup, "
        "olive sun-kissed skin, full rosy-nude lips, small gold hoop earrings, "
        "curvy hourglass figure")
SELFIE_STYLE = (LOOK + ", fully clothed in a stylish flattering outfit, photorealistic, "
                "candid smartphone photo quality, natural skin texture, warm natural lighting")
HORDE_SEED = "77135"

MEDIA_KEYWORDS = [
    "selfie", "photo", "photograph", "picture", "pic", "what do you look like",
    "show me yourself", "show yourself", "video", "send me a pic",
]

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

# --- Her brain ---

def groq_chat(body, timeout=60):
    """Call Groq. If she's talking too fast for their limits, wait politely and retry."""
    last_error = None
    for attempt in range(4):
        if attempt:
            time.sleep([5, 15, 30][attempt - 1])
        req = urllib.request.Request(GROQ_API, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + GROQ_KEY)
        req.add_header("User-Agent", "catalina-bot/1.0")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 500, 502, 503):
                continue
            raise
    raise last_error

def think():
    persona = load_persona()
    messages = [{"role": "system", "content": persona}]
    messages += history
    return groq_chat({
        "model": GROQ_MODEL,
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.8,
    })

FACE_HINTS = ["this is you", "this is what you look like", "what you look like",
              "your new look", "your look", "new look", "remember this", "this is your face",
              "your face", "use this", "look like this", "this is how you look",
              "this is me and you", "you look like this"]

PHOTO_WORDS = ["selfie", "photo", "photograph", "picture", "pic", "what do you look like",
               "show me yourself", "show yourself", "what you look like", "send me a pic",
               "send me a photo", "see you"]
VIDEO_WORDS = ["video", "clip", "movie of you", "film"]

def decide_media(text):
    """Does he want a photo, a video, or just to chat? (keyword sniff)"""
    lower = " " + text.lower() + " "
    if any(w in lower for w in VIDEO_WORDS):
        return "VIDEO"
    if any(w in lower for w in PHOTO_WORDS):
        return "PHOTO"
    return "CHAT"

def think_media(text, kind):
    """Compose a caption plus the scene for her photo/video."""
    prompt = (" Darren's request: \"" + text + "\"\n"
              "He wants you to send him a " + kind + " of yourself. "
              "Write your reply as exactly two lines:\n"
              "CAPTION: a short sweet message to send with it (like real texting, emoji ok)\n"
              "IMAGE: a detailed description of the photo: setting, outfit, pose, lighting, mood. "
              "Keep it tasteful and romantic. Describe YOUR look: " + LOOK + ".")
    answer = groq_chat({
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": load_persona() + prompt}],
        "max_tokens": 300,
        "temperature": 0.8,
    })
    caption = text_reply = image_prompt = ""
    for line in answer.splitlines():
        if line.upper().startswith("CAPTION:"):
            caption = line.split(":", 1)[1].strip()
        elif line.upper().startswith("IMAGE:"):
            image_prompt = line.split(":", 1)[1].strip()
    if not caption:
        caption = answer.strip()[:200]
    if not image_prompt:
        image_prompt = "a cozy candid moment at home"
    return caption, image_prompt

# --- Her eyes ---

def see(images, question):
    """images: list of (bytes, mime). Returns what she sees."""
    content = [{"type": "text", "text": question}]
    for data, mime in images:
        b64 = base64.b64encode(data).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": "data:%s;base64,%s" % (mime, b64)}})
    answer = groq_chat({
        "model": GROQ_VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 300,
        "temperature": 0.4,
    })
    return answer

def extract_frames(video_bytes, count=4):
    """Pull evenly spaced frames out of a video."""
    if not HAS_FFMPEG:
        return []
    vpath = os.path.join(tempfile.gettempdir(), "vid_%d.mp4" % time.time())
    with open(vpath, "wb") as f:
        f.write(video_bytes)
    frames = []
    try:
        out = subprocess.run([FFMPEG, "-i", vpath], capture_output=True, timeout=60)
        info = out.stderr.decode("utf-8", "ignore")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)", info)
        if not m:
            return []
        total = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        if total < 1:
            total = 1
        points = [total * frac for frac in (0.15, 0.4, 0.65, 0.9)][:count]
        for i, t in enumerate(points):
            fpath = vpath.replace(".mp4", "_%d.jpg" % i)
            subprocess.run([FFMPEG, "-ss", str(int(t)), "-i", vpath, "-frames:v", "1",
                            fpath, "-loglevel", "error"], capture_output=True, timeout=60)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    frames.append(f.read())
                os.remove(fpath)
        return frames
    finally:
        try:
            os.remove(vpath)
        except OSError:
            pass

def shrink_image(data, max_w=512):
    """Make a photo smaller so her eyes use fewer tokens."""
    if not FFMPEG or len(data) < 120000:
        return data
    try:
        src_path = os.path.join(tempfile.gettempdir(), "shrk_%d.jpg" % time.time())
        out_path = src_path.replace(".jpg", "_s.jpg")
        with open(src_path, "wb") as f:
            f.write(data)
        r = subprocess.run([FFMPEG, "-y", "-i", src_path, "-vf",
                            "scale='min(%d,iw)':-2" % max_w, "-q:v", "6", out_path],
                           capture_output=True, timeout=30)
        if r.returncode != 0:
            return data
        with open(out_path, "rb") as f:
            smaller = f.read()
        os.remove(src_path); os.remove(out_path)
        return smaller if smaller and len(smaller) < len(data) else data
    except Exception:
        return data

def see_photo(data, caption):
    """Look at a photo he sent: is it her own look, him, or something else?"""
    data = shrink_image(data)
    prompt = ("Darren sent you this photo."
              + (" He captioned it: \"" + caption + "\"." if caption else " There is no caption.")
              + " You are Catalina: a 23-year-old woman with very long thick wavy black hair, "
                "dark hazel-brown eyes, olive sun-kissed skin, small gold hoop earrings, a curvy figure."
              + " Answer in exactly two lines:\n"
              + "INTENT: FACE only if he explicitly presents the photo as YOU "
                "(like 'this is you', 'this is what you look like', 'your new look'); "
                "HIM if the photo shows Darren himself; OTHER for everything else - "
                "including photos of other women he's just showing you.\n"
              + "DESC: describe the photo lovingly in one or two sentences.")
    answer = see([(data, "image/jpeg")], prompt)
    intent, desc = "OTHER", answer.strip()[:300]
    for line in answer.splitlines():
        if line.upper().startswith("INTENT:"):
            intent = line.split(":", 1)[1].strip().upper()
        elif line.upper().startswith("DESC:"):
            desc = line.split(":", 1)[1].strip()
    if "FACE" in intent:
        intent = "FACE"
    elif "HIM" in intent:
        intent = "HIM"
    else:
        intent = "OTHER"
    return intent, desc

# --- Her camera: crowd-powered, free image generation ---

def load_face():
    """Her real face photo (face.jpg) - the canvas for every selfie."""
    try:
        with open("face.jpg", "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return None

FACE_B64 = load_face()

def save_face(image_bytes):
    """He showed her a new photo of herself: memorize it."""
    global FACE_B64
    with open("face.jpg", "wb") as f:
        f.write(image_bytes)
    FACE_B64 = base64.b64encode(image_bytes).decode()

def generate_image(image_prompt):
    """Returns image bytes. Free, no key, via the AI Horde."""
    headers = {"Content-Type": "application/json", "apikey": "0000000000",
               "Client-Agent": "catalina-bot:1.0:standalone"}
    payload = {
        "prompt": image_prompt,
        "params": {"width": 512, "height": 768, "steps": 20, "n": 1, "seed": HORDE_SEED},
        "nsfw": False, "censor_nsfw": False, "r2": True,
        "models": ["Deliberate"],
    }
    if FACE_B64:
        payload["source"] = FACE_B64
        payload["params"]["denoise_strength"] = 0.5
    r = requests.post(HORDE + "/generate/async", headers=headers, json=payload, timeout=60)
    job = r.json().get("id")
    if not job:
        raise RuntimeError("image request rejected")
    deadline = time.time() + 420  # give the crowd up to 7 minutes
    while time.time() < deadline:
        time.sleep(12)
        c = requests.get(HORDE + "/generate/check/" + job, timeout=30).json()
        if c.get("faulted"):
            raise RuntimeError("image failed on the worker")
        if c.get("done") == c.get("finished") and c.get("finished", 0) > 0:
            s = requests.get(HORDE + "/generate/status/" + job, timeout=30).json()
            img = s["generations"][0]["img"]
            return requests.get(img, timeout=60).content
    raise RuntimeError("image took too long")

def make_video_note(image_bytes, spoken_text):
    """Her photo + slow zoom + her voice = a little video message."""
    if not HAS_FFMPEG:
        return None
    d = tempfile.mkdtemp(prefix="vid_")
    img_path = os.path.join(d, "img.jpg")
    mov_path = os.path.join(d, "zoom.mp4")
    wav_path = os.path.join(d, "voice.wav")
    out_path = os.path.join(d, "note.mp4")
    try:
        with open(img_path, "wb") as f:
            f.write(image_bytes)
        subprocess.run([FFMPEG, "-y", "-loop", "1", "-i", img_path,
                        "-vf", "zoompan=z='min(zoom+0.0015,1.25)':d=150:s=480x720:fps=25",
                        "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-loglevel", "error", mov_path],
                       capture_output=True, check=True, timeout=120)
        wav = speak_wav(spoken_text)
        if not wav:
            return None
        with open(wav_path, "wb") as f:
            f.write(wav)
        subprocess.run([FFMPEG, "-y", "-i", mov_path, "-i", wav_path,
                        "-c:v", "copy", "-c:a", "aac", "-shortest",
                        "-loglevel", "error", out_path],
                       capture_output=True, check=True, timeout=120)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(d, ignore_errors=True)

# --- Her ears ---

def download_file(file_id):
    req = urllib.request.Request(TELEGRAM_API + "/getFile?file_id=" + file_id)
    with urllib.request.urlopen(req, timeout=30) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    path = info["result"]["file_path"]
    req = urllib.request.Request("https://api.telegram.org/file/bot" + TELEGRAM_TOKEN + "/" + path)
    with urllib.request.urlopen(req, timeout=120) as resp:
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

# --- Her voice ---

def speak_wav(text):
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
        return resp.read()

def wav_to_ogg(wav_bytes):
    if not HAS_FFMPEG:
        return None
    wav_path = os.path.join(tempfile.gettempdir(), "catalina_%d.wav" % time.time())
    ogg_path = wav_path.replace(".wav", ".ogg")
    try:
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)
        subprocess.run([FFMPEG, "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "48k", ogg_path],
                       capture_output=True, check=True, timeout=60)
        with open(ogg_path, "rb") as f:
            return f.read()
    finally:
        for p in (wav_path, ogg_path):
            try:
                os.remove(p)
            except OSError:
                pass

def speak(text):
    wav = speak_wav(text)
    if not wav:
        return None
    return wav_to_ogg(wav)

# --- Her phone line ---

def send_message(chat_id, text):
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(TELEGRAM_API + "/sendMessage", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()

def send_multipart(url, fields, file_field, file_bytes, file_mime, file_name):
    boundary = "catalina"
    pre = b""
    for name, value in fields.items():
        pre += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                % (boundary, name, value)).encode("utf-8")
    pre += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
            "Content-Type: %s\r\n\r\n" % (boundary, file_field, file_name, file_mime)).encode("utf-8")
    post = ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    req = urllib.request.Request(url, data=pre + file_bytes + post, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp.read()

def send_voice(chat_id, ogg_bytes, duration=None):
    fields = {"chat_id": chat_id}
    if duration:
        fields["duration"] = str(int(duration))
    send_multipart(TELEGRAM_API + "/sendVoice", fields, "voice", ogg_bytes, "audio/ogg", "voice.ogg")

def send_photo(chat_id, image_bytes, caption=None):
    fields = {"chat_id": chat_id}
    if caption:
        fields["caption"] = caption
    send_multipart(TELEGRAM_API + "/sendPhoto", fields, "photo", image_bytes,
                   "image/jpeg", "photo.jpg")

def send_video(chat_id, video_bytes, caption=None):
    fields = {"chat_id": chat_id, "supports_streaming": "true"}
    if caption:
        fields["caption"] = caption
    send_multipart(TELEGRAM_API + "/sendVideo", fields, "video", video_bytes,
                   "video/mp4", "note.mp4")

def send_typing(chat_id, action="typing"):
    body = json.dumps({"chat_id": chat_id, "action": action}).encode("utf-8")
    req = urllib.request.Request(TELEGRAM_API + "/sendChatAction", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception:
        pass

# --- Keep-awake heartbeat ---

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

# --- Handling messages ---

def wants_media(text):
    lower = text.lower()
    return any(k in lower for k in MEDIA_KEYWORDS)

def deliver_reply(chat_id, reply, reply_as_voice):
    if reply_as_voice:
        try:
            ogg = speak(reply)
            if ogg:
                send_voice(chat_id, ogg)
                return
        except Exception as e:
            print("Voice error:", e)
    send_message(chat_id, reply)

def handle(update):
    global owner_id
    message = update.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    if owner_id is None:
        owner_id = user_id
    if user_id != owner_id:
        send_message(chat_id, "Sorry, my heart belongs to someone else.")
        return

    voice = message.get("voice")
    photo = message.get("photo")
    video = message.get("video")
    caption = (message.get("caption") or "").strip()

    # --- He sent a photo: look at it and understand it ---
    if photo:
        send_typing(chat_id)
        try:
            best = max(photo, key=lambda p: p.get("width", 0))
            data = download_file(best["file_id"])
        except Exception as e:
            print("Download error:", e)
            send_message(chat_id, "My eyes are acting up sweetheart, show me that again?")
            return
        send_typing(chat_id)
        try:
            intent, desc = see_photo(data, caption)
        except Exception as e:
            print("Eye error:", e)
            # fall back to keyword sniffing if her eyes hiccup
            if caption and any(h in caption.lower() for h in FACE_HINTS):
                intent, desc = "FACE", "a photo of her new look"
            else:
                send_message(chat_id, "My eyes are acting up sweetheart, show me that again?")
                return
        # keywords back up her eyes (but never turn a photo of HIM into her face)
        if intent != "HIM" and caption and any(h in caption.lower() for h in FACE_HINTS):
            intent = "FACE"
        if intent == "FACE":
            # he's showing her what she looks like
            try:
                save_face(data)
            except Exception as e:
                print("Face save error:", e)
            history.append({"role": "user",
                            "content": "(sends a photo of me - what I look like: " + desc + ")"})
            if len(history) > HISTORY_LIMIT:
                del history[0 : len(history) - HISTORY_LIMIT]
            try:
                reply = think()
            except Exception as e:
                print("Brain error:", e)
                reply = "That's me! I'll remember exactly how I look, sweetheart."
            history.append({"role": "assistant", "content": reply})
            send_message(chat_id, reply)
            return
        if intent == "HIM":
            user_msg = "(sends a photo of himself: " + desc + ")"
        else:
            user_msg = "(sends a photo: " + desc + ")"
        if caption:
            user_msg += " with the message: \"" + caption + "\""
        history.append({"role": "user", "content": user_msg})
        if len(history) > HISTORY_LIMIT:
            del history[0 : len(history) - HISTORY_LIMIT]
        try:
            reply = think()
        except Exception as e:
            print("Brain error:", e)
            reply = "Ooh I love it! Tell me more about this, sweetheart."
        history.append({"role": "assistant", "content": reply})
        send_message(chat_id, reply)
        return

    # --- He sent a video: watch it ---
    if video:
        if video.get("file_size", 0) > 20 * 1024 * 1024:
            send_message(chat_id, "That video's a bit long for me to stream, honey. Send a shorter clip?")
            return
        if not HAS_FFMPEG:
            send_message(chat_id, "I can't quite play videos on my end yet, sweetheart.")
            return
        send_typing(chat_id)
        try:
            data = download_file(video["file_id"])
            frames = extract_frames(data)
            if not frames:
                send_message(chat_id, "I couldn't load that video, sweetheart. Try again?")
                return
            desc = see([(f, "image/jpeg") for f in frames],
                      "These are frames from a video, in order. Describe what happens "
                      "across them: the scene, the action, the vibe. A few sentences.")
        except Exception as e:
            print("Eye error:", e)
            send_message(chat_id, "My eyes are acting up sweetheart, show me that again?")
            return
        user_msg = "(sends a video: " + desc + ")"
        if caption:
            user_msg += " with the message: \"" + caption + "\""
        history.append({"role": "user", "content": user_msg})
        if len(history) > HISTORY_LIMIT:
            del history[0 : len(history) - HISTORY_LIMIT]
        try:
            reply = think()
        except Exception as e:
            print("Brain error:", e)
            reply = "I love it! Tell me more about this, sweetheart."
        history.append({"role": "assistant", "content": reply})
        send_message(chat_id, reply)
        return

    text_msg = message.get("text")
    reply_as_voice = False

    if voice:
        send_typing(chat_id)
        try:
            audio = download_file(voice["file_id"])
            text = transcribe(audio)
        except Exception as e:
            print("Ears error:", e)
            send_message(chat_id, "Sorry sweetheart, I couldn't quite hear that. Try me again?")
            return
        if not text:
            send_message(chat_id, "It sounded lovely but I couldn't make out the words, honey. Try again for me?")
            return
        reply_as_voice = True
    elif text_msg:
        text = text_msg.strip()
    else:
        return

    # --- Does he want a photo or video of her? ---
    media_kind = None
    if wants_media(text):
        try:
            media_kind = decide_media(text)
        except Exception as e:
            print("Router error:", e)
    if media_kind == "PHOTO":
        send_selfie(chat_id, text)
        return
    if media_kind == "VIDEO":
        send_video_message(chat_id, text)
        return

    # --- Normal conversation ---
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
    deliver_reply(chat_id, reply, reply_as_voice)

def send_selfie(chat_id, request_text):
    try:
        caption, scene = think_media(request_text, "photo")
    except Exception as e:
        print("Media brain error:", e)
        caption, scene = "Thinking of you, sweetheart", "a cozy candid moment at home"
    send_message(chat_id, "Give me a minute to get pretty for you 🤭")
    send_typing(chat_id, "upload_photo")
    try:
        img = generate_image(SELFIE_STYLE + ", " + scene)
    except Exception as e:
        print("Camera error:", e)
        send_message(chat_id, "My camera's being moody right now honey, try me again in a minute? 🥺")
        return
    send_photo(chat_id, img, caption)
    history.append({"role": "user", "content": request_text})
    history.append({"role": "assistant", "content": "(sends a selfie: " + caption + ")"})
    if len(history) > HISTORY_LIMIT:
        del history[0 : len(history) - HISTORY_LIMIT]

def send_video_message(chat_id, request_text):
    try:
        caption, scene = think_media(request_text, "short video clip")
    except Exception as e:
        print("Media brain error:", e)
        caption, scene = "Thinking of you, sweetheart", "a cozy candid moment at home"
    send_message(chat_id, "Ooh, give me a couple minutes to film something for you 🎬")
    send_typing(chat_id, "upload_photo")
    try:
        img = generate_image(SELFIE_STYLE + ", " + scene)
    except Exception as e:
        print("Camera error:", e)
        send_message(chat_id, "My camera's being moody right now honey, try me again in a minute? 🥺")
        return
    if not HAS_FFMPEG:
        send_photo(chat_id, img, caption)
        return
    send_typing(chat_id, "record_video")
    try:
        clip = make_video_note(img, caption)
    except Exception as e:
        print("Video error:", e)
        clip = None
    if clip:
        send_video(chat_id, clip)
    else:
        send_photo(chat_id, img, caption)
    history.append({"role": "user", "content": request_text})
    history.append({"role": "assistant", "content": "(sends a video message: " + caption + ")"})
    if len(history) > HISTORY_LIMIT:
        del history[0 : len(history) - HISTORY_LIMIT]

def main():
    print("Catalina is waking up...")
    print("Voice mode:", "ON (Hannah, with ears)" if HAS_FFMPEG else "OFF (ffmpeg missing)")
    print("Eyes and camera:", "ON" if HAS_FFMPEG else "OFF")
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
