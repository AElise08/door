"""Did something really appear on the owner's screen? macOS lists the windows that are on screen (owner app and size) without any special
permission, so Door compares the list before and after an `open`: a new window is proof, no new window is "could not confirm".
(It sees which app owns a window, never what is inside it; reading titles or pixels would need Screen Recording, which Door does not ask for.)"""
import json
import subprocess
import time
from collections import Counter

JXA = """ObjC.import('CoreGraphics');
const raw = $.CGWindowListCopyWindowInfo($.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements, 0);
const arr = ObjC.deepUnwrap(ObjC.castRefToObject(raw));
console.log(JSON.stringify(arr.filter(w => w.kCGWindowLayer === 0 && w.kCGWindowBounds && w.kCGWindowBounds.Width > 60 && w.kCGWindowBounds.Height > 60).map(w => w.kCGWindowOwnerName)));"""


def windows():
    """Counter of app name -> number of visible windows, or None when this computer cannot say (not a Mac, no desktop session)."""
    try:
        r = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", JXA], capture_output=True, text=True, timeout=6)
        text = (r.stdout.strip() or r.stderr.strip())            # osascript prints console.log on the error channel
        return Counter(json.loads(text.splitlines()[-1])) if r.returncode == 0 and text else None
    except (OSError, ValueError, subprocess.TimeoutExpired, IndexError):
        return None


def watch(before, seconds=8.0, interval=0.5, listing=windows, sleep=time.sleep):
    """After an open: the apps that gained a window, within `seconds`. Empty list = could not confirm."""
    if before is None:
        return []
    tries = int(seconds / interval) + 1 if interval > 0 else 3          # a fixed number of looks, so it always ends
    for i in range(tries):
        now = listing()
        if now is not None:
            gained = [app for app, n in now.items() if n > before.get(app, 0)]
            if gained:
                return sorted(gained)
        if i < tries - 1:
            sleep(interval)
    return []
