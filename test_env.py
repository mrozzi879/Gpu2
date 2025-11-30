# test_env.py — debug for Render: prints env and starts an HTTP health server
import os, asyncio, sys
from aiohttp import web

PORT = int(os.environ.get("PORT", "8080"))
print("Starting debug test_env.py")
# Print a few env vars (do NOT paste logs publicly if they include your webhook)
print("DISCORD_WEBHOOK present:", "DISCORD_WEBHOOK" in os.environ)
print("PORT env:", os.environ.get("PORT"))
print("SUBREDDITS:", os.environ.get("SUBREDDITS"))
sys.stdout.flush()

async def health(request):
    return web.Response(text="DEBUG OK")

async def start():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"Health server listening on 0.0.0.0:{PORT}")
    sys.stdout.flush()
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(start())
    except Exception as e:
        print("test_env.py exception:", e)
        raise
