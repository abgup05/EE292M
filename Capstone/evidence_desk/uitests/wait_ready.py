"""Wait until the app container answers, so the headless browser never loads a dead page.

Run inside the app container by `make uitest`; exits non-zero after about 20 seconds.
"""

import sys
import time
import urllib.error
import urllib.request

ROOT = "http://127.0.0.1:8000"
ATTEMPTS = 80
PAUSE_SECONDS = 0.25


def main() -> int:
    """Poll /api/health until it answers 200."""
    for _ in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(ROOT + "/api/health", timeout=5) as response:
                if response.status == 200:
                    return 0
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(PAUSE_SECONDS)
    print("The app did not answer /api/health in time.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
