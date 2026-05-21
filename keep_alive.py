import subprocess, time, logging, sys
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "keepalive.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

PYTHON = sys.executable
BOT    = str(Path(__file__).parent / "bot.py")

def run():
    attempt = 0
    while True:
        attempt += 1
        log.info(f"Starting bot (attempt #{attempt})...")
        try:
            proc = subprocess.run([PYTHON, BOT], cwd=Path(__file__).parent)
            log.warning(f"Bot exited with code {proc.returncode}. Restarting in 5s...")
        except Exception as e:
            log.error(f"Failed to launch bot: {e}. Retrying in 5s...")
        time.sleep(5)

if __name__ == "__main__":
    run()
