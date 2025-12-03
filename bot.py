# bot.py — Robust Reddit sniper (defensive, logs errors instead of crashing)
import os, re, json, time, traceback
from pathlib import Path

# Try imports, but don't crash if they fail — print and continue
try:
    import requests
except Exception as e:
    print("IMPORT ERROR: requests not available:", e)
    requests = None

try:
    from PIL import Image, ImageOps, ImageFilter
    import io
    HAS_PIL = True
except Exception as e:
    print("IMPORT WARNING: PIL unavailable:", e)
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESS = True
except Exception as e:
    print("IMPORT WARNING: pytesseract unavailable:", e)
    HAS_TESS = False

try:
    # aiohttp used only for the health server; fallback handled below
    from aiohttp import web
    HAS_AIOHTTP = True
except Exception:
    HAS_AIOHTTP = False

# ---------- Config ----------
SUBREDDITS = os.environ.get("SUBREDDITS", "xboxgamepass,Xbox,gamesir,xboxindia").split(",")
KEYWORDS = [k.strip() for k in os.environ.get("KEYWORDS", "code,free,giveaway,game pass code,gamepass").split(",")]
POLL_DELAY = float(os.environ.get("POLL_DELAY", "3.0"))
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")  # may be None for now; bot will run anyway
USER_AGENT = os.environ.get("USER_AGENT", "linux:sniper.render:v1.0 (by u/your_reddit_username)")
SEEN_FILE = os.environ.get("SEEN_FILE", "seen_ids.json")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "12"))
MAX_IMG_PER_POST = int(os.environ.get("MAX_IMG_PER_POST", "2"))
PORT = int(os.environ.get("PORT", "10000"))
# -----------------------------

print("=== Bot starting ===")
print("SUBREDDITS:", SUBREDDITS)
print("POLL_DELAY:", POLL_DELAY)
print("DISCORD_WEBHOOK set:", bool(DISCORD_WEBHOOK))
print("HAS_PIL:", HAS_PIL, "HAS_TESS:", HAS_TESS, "HAS_AIOHTTP:", HAS_AIOHTTP)
print("PORT:", PORT)
print("USER_AGENT:", USER_AGENT)
print("=== End startup info ===")

# Build regex
escaped = [re.escape(k) for k in KEYWORDS if k]
pattern = r"\b(?:" + "|".join(escaped) + r")\b" if escaped else r"$^"
KW_RE = re.compile(pattern, flags=re.IGNORECASE)

CODE_RE_DASH = re.compile(r"\b[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}\b")
CODE_RE_25 = re.compile(r"\b[A-Z0-9]{25}\b")

# Load seen ids
seen_path = Path(SEEN_FILE)
try:
    if seen_path.exists():
        seen_ids = set(json.loads(seen_path.read_text()))
    else:
        seen_ids = set()
except Exception as e:
    print("Failed reading seen file:", e)
    seen_ids = set()

# ---------- helper functions ----------
def save_seen():
    try:
        seen_path.write_text(json.dumps(sorted(list(seen_ids))))
    except Exception as e:
        print("Failed saving seen ids:", e)

def fetch_json(url):
    if not requests:
        return None
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code == 429:
            print("RATE LIMIT from Reddit for", url)
            return {"error": "rate_limited"}
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print("fetch_json error:", e)
        return None

def post_discord(content):
    if not requests or not DISCORD_WEBHOOK:
        print("Skipping Discord post (requests/webhook missing). Content:", content[:120])
        return False
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": content}, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print("Discord post failed:", e)
        return False

def post_discord_image(content, image_bytes, filename="image.png"):
    if not requests or not DISCORD_WEBHOOK:
        print("Skipping Discord image post; webhook missing.")
        return False
    try:
        files = {"file": (filename, image_bytes, "image/png")}
        data = {"content": content}
        r = requests.post(DISCORD_WEBHOOK, data=data, files=files, timeout=20)
        r.raise_for_status()
        return True
    except Exception as e:
        print("Discord image post failed:", e)
        return False

def preprocess_image_for_ocr(img_bytes):
    if not HAS_PIL:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        gray = ImageOps.grayscale(img)
        w,h = gray.size
        if max(w,h) < 1000:
            scale = 2 if max(w,h) >= 600 else 3
            gray = gray.resize((w*scale, h*scale), Image.BICUBIC)
        gray = gray.filter(ImageFilter.SHARPEN)
        bw = gray.point(lambda x: 0 if x < 140 else 255, '1')
        return bw.convert("L")
    except Exception as e:
        print("preprocess_image_for_ocr error:", e)
        return None

def run_tesseract(pil_img):
    if not HAS_TESS:
        return ""
    try:
        cfg = "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        return pytesseract.image_to_string(pil_img, config=cfg)
    except Exception as e:
        print("tesseract error:", e)
        return ""

def find_codes_in_text(text):
    if not text:
        return []
    txt = text.upper()
    codes = set(CODE_RE_DASH.findall(txt) + CODE_RE_25.findall(txt))
    return list(codes)

def extract_image_urls(post):
    urls = []
    preview = post.get("preview") or {}
    for img in preview.get("images", []):
        src = img.get("source", {}).get("url") or ""
        if src:
            urls.append(src.replace("&amp;", "&"))
    if post.get("is_gallery") and post.get("media_metadata"):
        md = post.get("media_metadata")
        for v in md.values():
            u = (v.get("s") or {}).get("u") or ""
            if u:
                urls.append(u.replace("&amp;", "&"))
    url = post.get("url","")
    if url and url.lower().endswith((".jpg",".jpeg",".png",".webp")):
        urls.append(url)
    out=[]
    seen=set()
    for u in urls:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out

def download_bytes(url):
    if not requests:
        return None
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print("download error:", e, url)
        return None

# ---------- core loop ----------
def check_once():
    alerted = 0
    for sub in SUBREDDITS:
        try:
            data = fetch_json(f"https://www.reddit.com/r/{sub}/new.json?limit=25")
            if not data:
                continue
            if data.get("error") == "rate_limited":
                print("Rate limited on", sub)
                continue
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                pid = d.get("id")
                if not pid or pid in seen_ids:
                    continue
                title = d.get("title","")
                selftext = d.get("selftext","")
                link = "https://reddit.com" + d.get("permalink","")
                text_combined = (title + " " + selftext)
                matched = bool(KW_RE.search(text_combined))
                codes = []
                # find in text
                codes += find_codes_in_text(text_combined)
                # if image present, attempt OCR
                img_urls = extract_image_urls(d)
                if img_urls and (matched or True):  # attempt OCR if images exist
                    for url in img_urls[:MAX_IMG_PER_POST]:
                        b = download_bytes(url)
                        if not b: continue
                        pil = preprocess_image_for_ocr(b)
                        if pil:
                            t = run_tesseract(pil)
                            if t:
                                codes += find_codes_in_text(t)
                codes = list(dict.fromkeys(codes))
                if codes:
                    for code in codes:
                        msg = f"🔔 Match r/{d.get('subreddit')} — {title}\nCode: `{code}`\n{link}"
                        post_discord(msg)
                    # send first image for verification if available
                    if img_urls:
                        b = download_bytes(img_urls[0])
                        if b:
                            post_discord_image(f"Image from r/{d.get('subreddit')} — OCR candidates: {' | '.join(codes) if codes else 'none'}\n{link}", b)
                    alerted += 1
                    seen_ids.add(pid)
                else:
                    # if keyword matched but no code, send the image for manual check
                    if matched and img_urls:
                        b = download_bytes(img_urls[0])
                        if b:
                            post_discord_image(f"⚠️ Keyword match but no detected code in r/{d.get('subreddit')}: {title}\n{link}", b)
                        seen_ids.add(pid)
        except Exception as e:
            print("Error in checking subreddit", sub, ":", e)
            traceback.print_exc()
    save_seen()
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "iteration done, alerted:", alerted)
    return alerted

# ---------- health server ----------
def start_health_server():
    if HAS_AIOHTTP:
        try:
            async def _run():
                app = web.Application()
                async def health(request):
                    return web.Response(text="OK")
                app.router.add_get("/", health)
                runner = web.AppRunner(app)
                await runner.setup()
                site = web.TCPSite(runner, '0.0.0.0', PORT)
                await site.start()
                print("Health server (aiohttp) listening on 0.0.0.0:%d" % PORT)
            import asyncio
            asyncio.run(_run())
            return True
        except Exception as e:
            print("Health aiohttp error:", e)
    # fallback tiny health server (blocking) using http.server
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type","text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
        def serve():
            try:
                httpd = HTTPServer(('0.0.0.0', PORT), H)
                print("Fallback health server listening on 0.0.0.0:%d" % PORT)
                httpd.serve_forever()
            except Exception as e:
                print("Fallback health server error:", e)
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        return True
    except Exception as e:
        print("Failed to start any health server:", e)
        return False

# ---------- main ----------
def main_loop():
    print("Starting main loop")
    if not start_health_server():
        print("Health server failed to start — continuing anyway")
    backoff = 1
    while True:
        try:
            check_once()
            backoff = 1
            time.sleep(POLL_DELAY)
        except Exception as e:
            print("Main loop exception:", e)
            traceback.print_exc()
            time.sleep(min(300, backoff))
            backoff *= 2

if __name__ == "__main__":
    try:
        main_loop()
    except Exception:
        print("Fatal exception in __main__:")
        traceback.print_exc()
        # keep container alive for inspection
        while True:
            time.sleep(3600)
