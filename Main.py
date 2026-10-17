# Catalina Summers - Telegram companion bot
# Free hosting on Render, free AI brain on Groq.

import json
import os
import time
import urllib.request
import urllib.parse

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
TELEGRAM_API = "https://api.telegram.org/bot" + TELEGRAM_TOKEN
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

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

# --- Main loop: listen for messages and reply ---

def handle(update):
    global owner_id
    message = update.get("message")
    if not message or not message.get("text"):
        return
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Lock to the first person who talks to her (her husband, Darren).
    if owner_id is None:
        owner_id = user_id
    if user_id != owner_id:
        send_message(chat_id, "Sorry, my heart belongs to someone else.")
        return

    text = message["text"].strip()
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
    send_message(chat_id, reply)

def main():
    print("Catalina is waking up...")
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
    main()
