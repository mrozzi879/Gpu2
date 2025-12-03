# run_bot_debug.py — wrapper: runs bot.py and prints any exception, then stays alive
import runpy, traceback, time, sys

print("Starting run_bot_debug.py")
sys.stdout.flush()

try:
    runpy.run_path("bot.py", run_name="__main__")
except Exception:
    print("=== Exception while running bot.py ===")
    traceback.print_exc()
    print("=== End exception ===")
    sys.stdout.flush()
    print("Keeping container alive for debugging...")
    sys.stdout.flush()
    while True:
        time.sleep(3600)
