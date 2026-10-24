NOPHOTO_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800">'
               '<rect width="100%" height="100%" fill="#1b1b1b"/>'
               '<text x="50%" y="52%" fill="#8a8a8a" font-family="sans-serif" '
               'font-size="30" text-anchor="middle">no photo saved yet</text>'
               '<text x="50%" y="58%" fill="#5f5f5f" font-family="sans-serif" '
               'font-size="20" text-anchor="middle">ask ani for one, then reload'
               '</text></svg>')

def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def canvas_page():
    img = gh_read("canvas/last_photo.jpg", branch=DATA_BRANCH)
    raw = gh_read("canvas/last_photo.txt", branch=DATA_BRANCH)
    info = (raw or b"").decode("utf-8", "replace").strip()
    if img:
        b64 = base64.b64encode(img).decode()
        shot = ('<img src="data:image/jpeg;base64,' + b64 + '" '
                'style="width:100%;border-radius:14px;display:block">')
    else:
        shot = ('<div style="padding:70px 18px;text-align:center;color:#8a8a8a;'
                'background:#1b1b1b;border-radius:14px;font-size:15px">'
                'no photo saved yet.<br><span style="color:#666;font-size:13px">'
                'ask ani for a photo, then reload this page.</span></div>')
    body = (
        '<!doctype html><meta name="viewport" content="width=device-width,'
        'initial-scale=1"><title>ani - last photo</title>'
        '<body style="margin:0;background:#111;color:#eee;'
        'font:15px -apple-system,BlinkMacSystemFont,sans-serif;padding:16px">'
        '<div style="max-width:520px;margin:0 auto">'
        '<h2 style="font-size:17px;margin:0 0 12px;font-weight:600">ani - last photo</h2>'
        + shot +
        '<h3 style="font-size:12px;margin:20px 0 6px;color:#8f8f8f;'
        'text-transform:uppercase;letter-spacing:1px">exactly what made it</h3>'
        '<pre style="white-space:pre-wrap;word-break:break-word;background:#1b1b1b;'
        'padding:12px;border-radius:10px;font-size:12px;color:#cfcfcf;margin:0">'
        + _esc(info or "nothing saved yet") +
        '</pre>'
        '<p style="font-size:12px;color:#6f6f6f;margin-top:18px">'
        'saved as canvas/last_photo.jpg on the data branch.</p>'
        '</div></body>')
    return body

def health_server():
    port = os.environ.get("PORT", "10000")
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def _out(self, text, code=200, ctype="text/plain; charset=utf-8"):
            b = text if isinstance(text, bytes) else text.encode("utf-8", "replace")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            path, qs = u.path, urllib.parse.parse_qs(u.query)
            try:
                if path == "/ping":
                    self._out("ok")
                elif path == "/debug":
                    self._out(debug_report())
                elif path == "/selftest":
                    self._out(selftest())
                elif path == "/voice":
                    self._out(voice_test())
                elif path == "/lint":
                    self._out(lint_remote())
                elif path == "/boot":
                    self._out(BOOT_ERROR or "booted clean")
                elif path == "/file":
                    self._out(tool_read((qs.get("path") or ["main.py"])[0]))
                elif path == "/logins":
                    self._out(tool_list_logins())
                elif path == "/kudos":
                    self._out(horde_kudos())
                elif path == "/hordetest":
                    self._out(horde_test())
                elif path in ("/canvas", "/lastphoto"):
                    d = gh_read("canvas/last_photo.jpg", branch=DATA_BRANCH)
                    if path == "/canvas":
                        self._out(canvas_page(), 200, "text/html; charset=utf-8")
                    elif d:
                        self._out(d, 200, "image/jpeg")
                    else:
                        self._out(NOPHOTO_SVG, 200, "image/svg+xml")
                elif path == "/lastprompt":
                    d = gh_read("canvas/last_photo.txt", branch=DATA_BRANCH)
                    self._out((d or b"").decode("utf-8", "replace")
                              or "no photo saved yet - ask ani for one")
                elif path == "/apps":
                    self._out(tool_list_apps())
                elif path.startswith("/apps/"):
                    n, d = _app_bytes(path[len("/apps/"):])
                    if not d:
                        self._out(f"no app called {n}", 404)
                    else:
                        ext = os.path.splitext(n)[1].lower()
                        self._out(d, 200, CTYPES.get(ext, "application/octet-stream"))
                elif path == "/tools":
                    self._out("\n".join(f"{t['function']['name']}: "
                                        f"{t['function']['description']}"
                                        for t in TOOL_SPECS))
                elif path == "/notes":
                    self._out(NOTES or "(no notes yet)")
                elif path == "/agent":
                    task = (qs.get("task") or ["what time is it in tokyo"])[0]
                    try:
                        reply, used = agent_guard(task, max_steps=6)
                        self._out(f"task: {task}\ntools: {used}\n\n{reply}")
                    except Exception as e:
                        self._out(f"agent failed: {e}")
                elif path == "/video":
                    desc = (qs.get("desc") or ["a wolf running through snow"])[0]
                    try:
                        data = build_video(desc, int((qs.get("shots") or ["2"])[0]),
                                           3, (qs.get("say") or [""])[0])
                        self._out(data, 200, "video/mp4")
                    except Exception as e:
                        self._out(f"video failed: {e}")
                elif path == "/scrub":
                    before = len(history)
                    scrub_history()
                    save_history(force=True)
                    self._out(f"scrubbed {before - len(history)} off-voice lines")
                elif path == "/reset":
                    history.clear()
                    PENDING_MEMORY.clear()
                    save_history(force=True)
                    self._out("history cleared")
                else:
                    self._out("ani is awake")
            except Exception as e:
                try:
                    self._out(f"error: {e}", 500)
                except Exception:
                    pass

        def log_message(self, *a):
            pass

    try:
        HTTPServer(("0.0.0.0", int(port)), H).serve_forever()
    except Exception as e:
        print("health", e)

def env_report():
    print(f"--- ani {VERSION} ---")
    for n in ["TELEGRAM_BOT_TOKEN", "GROQ_API_KEY", "GITHUB_TOKEN",
              "STUDIO_GITHUB_TOKEN", "GITHUB_REPO", "STUDIO_REPO",
              "HORDE_API_KEY", "HORDE_API_K", "RENDER_API_KEY",
              "RENDER_EXTERNAL_URL", "CHAT_MODEL", "AGENT_MODEL", "PORT"]:
        v = os.environ.get(n)
        print(f"  {n}: SET ({len(v)} chars)" if v else f"  {n}: missing")
    print("------------------")

if __name__ == "__main__":
    threading.Thread(target=health_server, daemon=True).start()
    try:
        load_persona()
        load_settings()
        load_notes()
        load_secrets()
        load_cookies()
        load_history()
        ensure_branch(DATA_BRANCH)
        save_history(force=True)
        scrub_history()
    except Exception:
        BOOT_ERROR = traceback.format_exc()
        print("BOOT ERROR:\n" + BOOT_ERROR)
    try:
        env_report()
    except Exception:
        traceback.print_exc()
    threading.Thread(target=self_ping, daemon=True).start()
    print(f"ani is awake - {len(TOOL_SPECS)} tools - {VERSION}")
    while True:
        try:
            poll()
        except Exception:
            traceback.print_exc()
            time.sleep(5)