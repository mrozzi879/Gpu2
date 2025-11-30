# bot.py — Reddit sniper with OCR + Render-friendly health endpoint
# Python 3.8+
import os, re, json, time, io, asyncio, signal
from pathlib import Path
import aiohttp
from aiohttp import web
from PIL import Image, ImageOps, ImageFilter
import pytesseract
import requests

# ---------- CONFIG -----------
SUBREDDITS = os.environ.get("SUBREDDITS", "xboxgamepass,Xbox,gamesir,xboxindia").split(",")
KEYWORDS = os.environ.get("KEYWORDS", "code,free,giveaway,game pass code,gamepass").split(",")
POLL_DELAY = float(os.environ.get("POLL_DELAY", "3.0"))   # seconds between loops — start conservative on Render free
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
USER_AGENT = os.environ.get("USER_AGENT", "linux:sniper.render:v1.0 (by u/your_reddit_username)")
SEEN_FILE = os.environ.get("SEEN_FILE", "seen_ids.json")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "12"))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "4"))
MAX_IMG_PER_POST = int(os.environ.get("MAX_IMG_PER_POST", "2"))
PORT = int(os.environ.get("PORT", "8080"))
# ------------------------------

if not DISCORD_WEBHOOK:
    print("ERROR: Set DISCORD_WEBHOOK environment variable before running.")
    raise SystemExit(1)

# Build whole-word, case-insensitive keyword regex
escaped = [re.escape(k.strip()) for k in KEYWORDS if k.strip()]
pattern = r"\b(?:" + "|".join(escaped) + r")\b" if escaped else r"$^"
KW_RE = re.compile(pattern, flags=re.IGNORECASE)

# Code regexes
CODE_RE_DASH = re.compile(r"\b[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}\b")
CODE_RE_25 = re.compile(r"\b[A-Z0-9]{25}\b")

seen_path = Path(SEEN_FILE)
if seen_path.exists():
    try:
        seen_ids = set(json.loads(seen_path.read_text()))
    except Exception:
        seen_ids = set()
else:
    seen_ids = set()

semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# ---------------- HTTP health server ----------------
async def health(request):
    return web.Response(text="OK")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# ---------------- Reddit fetch ----------------
async def fetch_subreddit(session, sub):
    url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
    headers = {"User-Agent": USER_AGENT}
    async with semaphore:
        try:
            async with session.get(url, headers=headers, timeout=REQUEST_TIMEOUT) as r:
                if r.status == 429:
                    return {"sub": sub, "error": "rate_limited", "status": 429}
                r.raise_for_status()
                data = await r.json()
                items = []
                for child in data.get("data", {}).get("children", []):
                    d = child.get("data", {})
                    items.append({
                        "id": d.get("id"),
                        "title": d.get("title",""),
                        "selftext": d.get("selftext",""),
                        "permalink": d.get("permalink",""),
                        "url": d.get("url",""),
                        "subreddit": d.get("subreddit"),
                        "preview": d.get("preview"),
                        "is_gallery": d.get("is_gallery"),
                        "media_metadata": d.get("media_metadata")
                    })
                return {"sub": sub, "items": items}
        except Exception as e:
            return {"sub": sub, "error": str(e)}

#
