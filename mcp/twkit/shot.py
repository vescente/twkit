"""Channel 4: a screenshot of the Tableau window — the product's own render."""
from __future__ import annotations

import json
import re
import os
import sys
import subprocess
import tempfile
import time

_SWIFT = """
import CoreGraphics
import Foundation
let opts = CGWindowListOption(arrayLiteral: .optionOnScreenOnly, .excludeDesktopElements)
guard let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] else { exit(1) }
var out: [[String: Any]] = []
for w in list {
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    out.append(["owner": w[kCGWindowOwnerName as String] as? String ?? "",
                "name": w[kCGWindowName as String] as? String ?? "",
                "id": w[kCGWindowNumber as String] as? Int ?? 0,
                "x": b["X"] ?? 0, "y": b["Y"] ?? 0,
                "w": b["Width"] ?? 0, "h": b["Height"] ?? 0])
}
print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!)
"""

_SWIFT_CLICK = """
import CoreGraphics
import Foundation
let a = CommandLine.arguments
guard a.count >= 3, let x = Double(a[1]), let y = Double(a[2]) else { exit(2) }
let p = CGPoint(x: x, y: y)
let src = CGEventSource(stateID: .hidSystemState)
CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: p,
        mouseButton: .left)?.post(tap: .cghidEventTap)
usleep(120_000)
CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: p,
        mouseButton: .left)?.post(tap: .cghidEventTap)
usleep(60_000)
CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: p,
        mouseButton: .left)?.post(tap: .cghidEventTap)
"""

_SWIFT_PARK = """
import CoreGraphics
import Foundation
let a = CommandLine.arguments
guard a.count >= 5, let x = Double(a[1]), let y = Double(a[2]),
      let w = Double(a[3]), let h = Double(a[4]) else { exit(2) }
let cur = CGEvent(source: nil)?.location ?? CGPoint(x: -1, y: -1)
if cur.x >= x && cur.x <= x + w && cur.y >= y + 28 && cur.y <= y + h {
    let p = CGPoint(x: x + w / 2, y: y + 10)
    let src = CGEventSource(stateID: .hidSystemState)
    CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: p,
            mouseButton: .left)?.post(tap: .cghidEventTap)
    print("moved")
}
"""

_SWIFT_TYPE = """
import CoreGraphics
import Foundation
guard let line = readLine(strippingNewline: true), !line.isEmpty else { exit(2) }
let src = CGEventSource(stateID: .hidSystemState)
for ch in line.unicodeScalars {
    var u = UniChar(ch.value)
    if let down = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: true) {
        down.keyboardSetUnicodeString(stringLength: 1, unicodeString: &u)
        down.post(tap: .cghidEventTap)
    }
    usleep(12_000)
    if let up = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: false) {
        up.keyboardSetUnicodeString(stringLength: 1, unicodeString: &u)
        up.post(tap: .cghidEventTap)
    }
    usleep(12_000)
}
"""

TABLEAU_APP = "/Applications/Tableau Desktop (Apple silicon) 2026.1.app"

TABLEAU_OWNER = "Tableau"

_CAPTURE_TRIES = 4
_CAPTURE_PAUSE = 2.0


def _window_lister() -> list:
    """Window listing command."""
    cache = os.path.join(tempfile.gettempdir(), "twkit_winlist")
    if os.path.exists(cache) and os.access(cache, os.X_OK):
        return [cache]
    src = cache + ".swift"
    try:
        with open(src, "w") as f:
            f.write(_SWIFT)
        r = subprocess.run(["swiftc", "-O", "-o", cache, src],
                           capture_output=True, timeout=180)
        if r.returncode == 0 and os.path.exists(cache):
            return [cache]
    except Exception:
        pass
    return ["swift", src]


def _clicker() -> list:
    """Compiled click helper."""
    cache = os.path.join(tempfile.gettempdir(), "twkit_click")
    if os.path.exists(cache) and os.access(cache, os.X_OK):
        return [cache]
    src = cache + ".swift"
    try:
        with open(src, "w") as f:
            f.write(_SWIFT_CLICK)
        r = subprocess.run(["swiftc", "-O", "-o", cache, src],
                           capture_output=True, timeout=180)
        if r.returncode == 0 and os.path.exists(cache):
            return [cache]
    except Exception:
        pass
    return []


def _typer() -> list:
    """Compiled typing helper."""
    cache = os.path.join(tempfile.gettempdir(), "twkit_type")
    if os.path.exists(cache) and os.access(cache, os.X_OK):
        return [cache]
    src = cache + ".swift"
    try:
        with open(src, "w") as f:
            f.write(_SWIFT_TYPE)
        r = subprocess.run(["swiftc", "-O", "-o", cache, src],
                           capture_output=True, timeout=180)
        if r.returncode == 0 and os.path.exists(cache):
            return [cache]
    except Exception:
        pass
    return []


def _parker() -> list:
    """Compiled cursor-park helper."""
    cache = os.path.join(tempfile.gettempdir(), "twkit_park")
    if os.path.exists(cache) and os.access(cache, os.X_OK):
        return [cache]
    src = cache + ".swift"
    try:
        with open(src, "w") as f:
            f.write(_SWIFT_PARK)
        r = subprocess.run(["swiftc", "-O", "-o", cache, src],
                           capture_output=True, timeout=180)
        if r.returncode == 0 and os.path.exists(cache):
            return [cache]
    except Exception:
        pass
    return []


def park_mouse(w: dict) -> bool:
    """If the cursor is over the canvas, park it on the title bar and let the tooltip fade."""
    cmd = _parker()
    if not cmd or not w:
        return False
    try:
        r = subprocess.run(cmd + [str(int(w.get(k) or 0)) for k in ("x", "y", "w", "h")],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    moved = "moved" in (r.stdout or "")
    if moved:
        time.sleep(1.2)
    return moved


def type_text(text: str) -> bool:
    """Type a string into the focused window without touching the clipboard."""
    cmd = _typer()
    if not cmd or not text:
        return False
    try:
        r = subprocess.run(cmd, input=text + "\n", text=True,
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def click(x: int, y: int) -> bool:
    """Click at a screen point."""
    cmd = _clicker()
    if not cmd:
        return False
    try:
        r = subprocess.run(cmd + [str(int(x)), str(int(y))],
                           capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def list_windows(owner: str = "Tableau") -> list[dict]:
    """Application windows on screen: id, title, size."""
    try:
        r = subprocess.run(_window_lister(), capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return []
        wins = json.loads(r.stdout)
    except Exception:
        return []
    return [w for w in wins
            if owner.lower() in str(w.get("owner", "")).lower()
            and w.get("w", 0) > 400 and w.get("h", 0) > 300]


def pick_window(book_hint: str = "", owner: str = "Tableau") -> dict | None:
    """The window holding the given workbook."""
    wins = list_windows(owner)
    if not wins:
        return None
    if book_hint:
        stem = os.path.splitext(os.path.basename(book_hint))[0].lower()
        for w in wins:
            if stem in str(w.get("name", "")).lower():
                return w
    return max(wins, key=lambda w: w["w"] * w["h"])


def window_of(book: str, owner: str = "Tableau") -> dict | None:
    """The window of exactly this workbook, with no largest-window fallback."""
    stem = os.path.splitext(os.path.basename(book))[0].lower()
    for w in list_windows(owner):
        if stem in str(w.get("name", "")).lower():
            return w
    return None


def screen_locked() -> bool:
    """Whether the screen is locked."""
    try:
        r = subprocess.run(["ioreg", "-n", "Root", "-d1", "-a"],
                           capture_output=True, timeout=10, text=True)
    except Exception:
        return False
    return bool(re.search(r"<key>CGSSessionScreenIsLocked</key>\s*<true/>", r.stdout or ""))


def capture(out_path: str, book_hint: str = "") -> dict:
    """Capture the Tableau window to a file."""
    w = pick_window(book_hint)
    if not w:
        return {"ok": False, "why": "Tableau window not found (closed, minimized "
                                       "or no Screen Recording permission)"}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if os.path.exists(out_path):
        os.unlink(out_path)
    if TABLEAU_OWNER.lower() not in str(w.get("owner", "")).lower():
        return {"ok": False, "why": f"the window belongs to '{w.get('owner')}'; "
                                       f"only {TABLEAU_OWNER} may be captured"}
    if not w.get("id"):
        return {"ok": False, "why": "the window has no id; full-screen capture is not allowed"}
    park_mouse(w)
    err = ""
    for attempt in range(_CAPTURE_TRIES):
        if attempt:
            time.sleep(_CAPTURE_PAUSE)
            fresh = pick_window(book_hint)
            if fresh and fresh.get("id"):
                w = fresh
        r = subprocess.run(["screencapture", "-x", "-o", f"-l{w['id']}", out_path],
                           capture_output=True, timeout=60, text=True)
        err = (r.stderr or "").strip()
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path):
            break
    if "could not create image" in err.lower() and screen_locked():
        return {"ok": False, "window": w.get("name", ""),
                "attempts": _CAPTURE_TRIES, "screen": "locked",
                "why": "the screen is locked; macOS returns no window images "
                          "(not a Screen Recording issue); capture after unlocking, "
                          "check opening via tableau_log"}
    if "could not create image" in err.lower():
        return {"ok": False, "window": w.get("name", ""),
                "attempts": _CAPTURE_TRIES,
                "why": f"macOS returned no window image in {_CAPTURE_TRIES} attempts; "
                          "re-confirm the Screen Recording permission "
                          "(restart the terminal)"}
    v = looks_rendered(out_path)
    if not v["ok"] and err:
        v["stderr"] = err[:160]
    v.update({"file": out_path, "window": w.get("name", ""),
              "window_size": f"{int(w['w'])}x{int(w['h'])}"})
    foreign = wrong_window(w.get("name", ""), book_hint)
    if foreign:
        v["ok"] = False
        v["why"] = foreign
    return v


def wrong_window(window_name: str, book_hint: str) -> str:
    """Did we capture someone else's window?"""
    if not window_name or not book_hint:
        return ""
    expected = os.path.splitext(os.path.basename(book_hint))[0].strip()
    if not expected or expected.lower() in window_name.lower():
        return ""
    return (f"captured the WRONG window '{window_name}', expected '{expected}': "
            "another workbook is open in Tableau and covers ours; "
            "do not trust the image, close the extra window and retry")


def looks_rendered(path: str) -> dict:
    """Tell a real render from a Loading placeholder or a blank white canvas."""
    if not os.path.exists(path) or os.path.getsize(path) < 200:
        return {"ok": False, "why": "file missing or truncated"}
    try:
        from PIL import Image
    except ImportError:
        return {"ok": True, "why": "PIL is not installed; content check skipped"}
    try:
        im = Image.open(path).convert("RGB")
    except Exception as exc:
        return {"ok": False, "why": f"not readable as an image: {str(exc)[:80]}"}
    if min(im.size) < 100:
        return {"ok": False, "why": f"image too small: {im.size[0]}x{im.size[1]}"}
    colors = im.getcolors(maxcolors=300_000) or []
    if not colors:
        return {"ok": True, "colors": ">300k", "why": "very colorful image"}
    total = im.size[0] * im.size[1]
    top = max(colors)[0] / total
    ok = len(colors) > 50 and top < 0.97
    return {"ok": ok, "colors": len(colors), "background_share": round(top, 3),
            "why": "" if ok else "the image is almost one color: probably a blank canvas "
                                    "or a loading screen"}


_DIALOG_SUBROLES = '{"AXDialog", "AXSystemDialog"}'

_DIALOG_MAX = (900, 600)
_UNTITLED = "(untitled window)"

_PROGRESS_TITLES = ("Processing Request", "\u041e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u0437\u0430\u043f\u0440\u043e\u0441\u0430", "Executing Query",
                    "Loading Data", "Connecting")


def is_progress(title: str) -> bool:
    t = str(title).strip().lower()
    return any(t.startswith(p.lower()) for p in _PROGRESS_TITLES)


def wait_progress(timeout: float = 180.0, pause: float = 2.0) -> dict:
    """Wait until Tableau finishes running a query."""
    waited = 0.0
    seen = []
    while waited < timeout:
        live = [t for t in _cg_dialog_titles() if is_progress(t)]
        if not live:
            return {"ok": True, "waited_sec": round(waited, 1), "before": seen}
        for t in live:
            if t not in seen:
                seen.append(t)
        time.sleep(pause)
        waited += pause
    return {"ok": False, "waited_sec": round(waited, 1), "before": seen,
            "why": "progress did not finish in time"}


_KEY = {"a": 0, "c": 8, "d": 2, "v": 9, "w": 13}


def _osa(script: str, timeout: float = 25.0):
    try:
        return subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def all_windows(owner: str = "Tableau") -> list:
    """All application windows, without size filtering."""
    try:
        r = subprocess.run(_window_lister(), capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return []
        wins = json.loads(r.stdout)
    except Exception:
        return []
    return [w for w in wins if owner.lower() in str(w.get("owner", "")).lower()
            and str(w.get("name", "")).strip()]


_CLOSE_X_AT = (0.962, 0.077)


def close_dialog_windows(titles: list) -> int:
    """Close windows with these titles via their close button."""
    wins = all_windows()
    closed = 0
    for w in wins:
        nm = str(w.get("name", "")).strip()
        untitled = (not nm or nm == "Tableau") and len(wins) > 1 \
            and int(w.get("w") or 0) <= _DIALOG_MAX[0] and int(w.get("h") or 0) <= _DIALOG_MAX[1]
        if nm not in titles and not (untitled and _UNTITLED in titles):
            continue
        x = int(w["x"] + w["w"] * _CLOSE_X_AT[0])
        y = int(w["y"] + w["h"] * _CLOSE_X_AT[1])
        _osa('tell application "Tableau" to activate')
        time.sleep(0.3)
        if click(x, y):
            closed += 1
        time.sleep(0.8)
    return closed


_OK_BUTTON_AT = (0.86, 0.87)


def press_ok(title: str = "") -> bool:
    """Press the dialog confirm button (OK / Yes), not cancel."""
    wins = all_windows()
    for w in wins:
        nm = str(w.get("name", "")).strip()
        if title and nm != title and not (title == _UNTITLED and nm in ("", "Tableau")):
            continue
        if not title and (nm.startswith("Tableau - ") or nm == "Tableau"):
            continue
        x = int(w["x"] + w["w"] * _OK_BUTTON_AT[0])
        y = int(w["y"] + w["h"] * _OK_BUTTON_AT[1])
        _osa('tell application "Tableau" to activate')
        time.sleep(0.3)
        if click(x, y):
            time.sleep(0.8)
            return True
    return False


def _cg_dialog_titles() -> list:
    """Tableau windows that are neither a document nor the start page."""
    out, wins = [], all_windows()
    for w in wins:
        name = str(w.get("name", "")).strip()
        if name and name != "Tableau" and not name.startswith("Tableau - "):
            out.append(name)
            continue
        if name.startswith("Tableau - "):
            continue
        area = int(w.get("w") or 0) * int(w.get("h") or 0)
        biggest = max((int(x.get("w") or 0) * int(x.get("h") or 0)) for x in wins)
        if (len(wins) > 1 and area < biggest
                and int(w.get("w") or 0) <= _DIALOG_MAX[0]
                and int(w.get("h") or 0) <= _DIALOG_MAX[1]):
            out.append(name or _UNTITLED)
    return out


def is_signin(title: str) -> bool:
    """A data source sign-in window."""
    t = str(title).strip().lower()
    return t.startswith("sign in") or t.startswith("sign_in")


def _real_dialogs() -> list:
    """Dialogs that really wait for a click."""
    return [t for t in list_dialogs() if not is_progress(t) and not is_signin(t)]


def _ax_window_names() -> list:
    """Tableau windows visible through Accessibility, except the document window."""
    r = _osa('tell application "System Events"\n'
             '  if not (exists process "Tableau") then return ""\n'
             '  tell process "Tableau" to return name of every window\n'
             'end tell', timeout=20)
    if r is None or r.returncode != 0:
        return []
    names = [t.strip() for t in r.stdout.split(",")]
    return [n for n in names if not n.startswith("Tableau - ")]


def list_dialogs() -> list:
    """Titles of Tableau modal windows."""
    r = _osa('tell application "System Events"\n'
             '  if not (exists process "Tableau") then return ""\n'
             '  tell process "Tableau"\n'
             '    set out to ""\n'
             '    repeat with w in windows\n'
             '      try\n'
             f'        if subrole of w is in {_DIALOG_SUBROLES} then '
             'set out to out & (name of w) & linefeed\n'
             '      end try\n'
             '    end repeat\n'
             '    return out\n'
             '  end tell\n'
             'end tell', timeout=20)
    found = [] if (r is None or r.returncode != 0) else \
        [t.strip() for t in r.stdout.splitlines() if t.strip()]
    for t in _cg_dialog_titles():
        if t not in found:
            found.append(t)
    return found


def read_dialog() -> list:
    """Full text of a Tableau dialog, including the defect location."""
    titles = list_dialogs()
    if not titles:
        return []
    saved = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    r = _osa('tell application "System Events" to tell process "Tableau"\n'
             '  set frontmost to true\n'
             '  delay 0.4\n'
             f'  try\n'
             f'    perform action "AXRaise" of (first window whose name is "{titles[0]}")\n'
             '    delay 0.3\n'
             '  end try\n'
             '  key code 8 using command down\n'
             'end tell')
    text = ""
    if r is not None and r.returncode == 0:
        time.sleep(0.8)
        text = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    if saved:
        subprocess.run(["pbcopy"], input=saved, text=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0] not in titles:
        return []
    return lines


def _press_default(title: str = "") -> bool:
    """Press the default button of a Tableau dialog."""
    raise_it = ""
    if title and title != _UNTITLED:
        raise_it = ('  try\n'
                    f'    perform action "AXRaise" of (first window whose name is "{title}")\n'
                    '  end try\n')
    r = _osa('tell application "Tableau" to activate\n'
             'delay 0.4\n'
             'tell application "System Events" to tell process "Tableau"\n'
             '  set frontmost to true\n'
             '  delay 0.3\n'
             + raise_it +
             '  keystroke return\n'
             '  delay 0.4\n'
             '  key code 36\n'
             'end tell')
    return r is not None and r.returncode == 0


def dismiss_dialog(tries: int = 3) -> dict:
    """Close stuck Tableau dialogs and return their text."""
    prog = wait_progress()
    if not _real_dialogs():
        signin = [t for t in list_dialogs() if is_signin(t)]
        if signin:
            return {"ok": False, "sign_in_needed": True, "dialogs": signin,
                    "action": "this is a data source sign-in window; do not close it, "
                                "call tableau_sign_in"}
    said, closed = [], 0
    for _ in range(tries):
        before = _real_dialogs()
        if not before:
            return {"ok": True, "closed": closed, "text": said,
                    "waited_progress_sec": prog.get("waited_sec", 0),
                    "action": "no dialogs" if not closed else "dialogs closed"}
        said = said or read_dialog()
        if not _press_default(before[0]):
            return {"ok": False, "closed": closed, "dialogs": before, "text": said,
                    "action": "the terminal has no Accessibility permission; "
                                "close the dialog manually"}
        time.sleep(1.0)
        wait_progress(timeout=60.0)
        if not _real_dialogs():
            return {"ok": True, "closed": closed + len(before), "text": said,
                    "action": "dialogs closed (Return)"}
        press_ok(before[0])
        wait_progress(timeout=60.0)
        if not _real_dialogs():
            return {"ok": True, "closed": closed + len(before), "text": said,
                    "action": "dialogs closed (confirm button)"}
        close_dialog_windows(before)
        time.sleep(0.8)
        if not _real_dialogs():
            return {"ok": True, "closed": closed + len(before), "text": said,
                    "action": "dialogs closed (close button)"}
        _osa('tell application "Tableau" to activate\n'
             'delay 0.3\n'
             'tell application "System Events" to tell process "Tableau"\n'
             '  key code 53\n'
             'end tell')
        time.sleep(0.8)
        closed += max(0, len(before) - len(_real_dialogs()))
    left = _real_dialogs()
    return {"ok": not left, "closed": closed, "dialogs": left, "text": said,
            "action": "dialogs closed" if not left
                        else "the dialog did not close; close it manually"}


_SIGNIN_TITLES = ("Sign in", "\u0412\u0445\u043e\u0434", "Sign In")
_SIGNIN_PASSWORD_AT = (0.59, 0.345)
_SIGNIN_BUTTON_AT = (0.834, 0.930)


def signin_window() -> dict | None:
    for w in list_windows():
        name = str(w.get("name", ""))
        if any(t.lower() in name.lower() for t in _SIGNIN_TITLES):
            return w
    return None


def sign_in(password: str, tries: int = 2) -> dict:
    """Enter the password into the Tableau sign-in window and press Sign In."""
    if not password:
        return {"ok": False, "action": "no password given"}
    for _ in range(tries):
        w = signin_window()
        if not w:
            return {"ok": True, "action": "no sign-in window"}
        for _ in range(4):
            blocking = [t for t in list_dialogs()
                        if t != w.get("name") and not is_progress(t)]
            if not blocking:
                break
            close_dialog_windows(blocking)
            time.sleep(0.8)
            w = signin_window() or w
        px = int(w["x"] + w["w"] * _SIGNIN_PASSWORD_AT[0])
        py = int(w["y"] + w["h"] * _SIGNIN_PASSWORD_AT[1])
        bx = int(w["x"] + w["w"] * _SIGNIN_BUTTON_AT[0])
        by = int(w["y"] + w["h"] * _SIGNIN_BUTTON_AT[1])
        _osa('tell application "Tableau" to activate')
        time.sleep(0.5)
        if not click(px, py):
            return {"ok": False, "action": "click on the password field failed"}
        time.sleep(0.4)
        _osa('tell application "System Events" to tell process "Tableau"\n'
             '  key code 0 using command down\n'
             '  delay 0.1\n'
             '  key code 51\n'
             'end tell')
        time.sleep(0.3)
        if not type_text(password):
            return {"ok": False, "action": "typing the password failed"}
        time.sleep(0.4)
        click(bx, by)
        for _ in range(12):
            time.sleep(1.5)
            if not signin_window():
                return {"ok": True, "action": "signed in"}
    return {"ok": False,
            "action": "the sign-in window stayed after typing; check the password "
                        "in the twkit settings (config) or sign in manually"}


_LINK_RGB = ((190, 255), (90, 160), (0, 90))


def find_link(book_hint: str = "", out_path: str = "") -> tuple | None:
    """Screen coordinates of the orange link in the Tableau window, if present."""
    try:
        from PIL import Image
    except ImportError:
        return None
    w = pick_window(book_hint)
    if not w:
        return None
    tmp = out_path or os.path.join(tempfile.gettempdir(), "twkit_link.png")
    if not capture(tmp, book_hint).get("file"):
        return None
    try:
        im = Image.open(tmp).convert("RGB")
    except Exception:
        return None
    if not int(w["w"]):
        return None
    scale = im.size[0] / float(int(w["w"]))
    if scale < 0.5 or scale > 4.0:
        return None
    px, pts = im.load(), []
    (rlo, rhi), (glo, ghi), (blo, bhi) = _LINK_RGB
    for y in range(0, im.size[1], 2):
        for x in range(0, im.size[0], 2):
            r, g, b = px[x, y]
            if rlo <= r <= rhi and glo <= g <= ghi and blo <= b <= bhi:
                pts.append((x, y))
    if len(pts) < 5:
        return None
    cx = int(w["x"]) + int((sum(p[0] for p in pts) / len(pts)) / scale)
    cy = int(w["y"]) + int((sum(p[1] for p in pts) / len(pts)) / scale)
    return cx, cy


def edit_connection(book_hint: str = "") -> dict:
    """Press the orange sign-in link on the Dashboard Unavailable banner."""
    pt = find_link(book_hint)
    if not pt:
        return {"ok": False, "action": "no Edit Connection link on screen"}
    _osa('tell application "Tableau" to activate')
    time.sleep(0.4)
    if not click(pt[0], pt[1]):
        return {"ok": False, "action": "click failed"}
    for _ in range(10):
        time.sleep(1.0)
        if signin_window():
            return {"ok": True, "action": "sign-in window opened"}
    return {"ok": False, "action": "no sign-in window after the click"}


def ensure_signed_in(book_hint: str = "") -> dict:
    """If Tableau waits for a ClickHouse sign-in, sign in and continue."""
    pwd = ch_mysql_password()
    if not pwd:
        return {"ok": False, "action": "no password in the twkit settings (config); sign in manually"}
    if not signin_window():
        opened = edit_connection(book_hint)
        if not opened["ok"]:
            return {"ok": True, "action": "sign-in not required"}
    return sign_in(pwd)


def ch_mysql_password() -> str:
    """Password of the MySQL-protocol database user, from `config`."""
    from . import config
    return config.get("password")


def close_tableau(wait: float = 60.0) -> dict:
    """Quit Tableau so the next screenshot shows the rebuilt file."""
    dismiss_dialog()
    if not list_windows():
        return {"ok": True, "action": "Tableau is already closed"}
    closed_docs = close_documents()
    if _gone(min(wait, 6.0)):
        return {"ok": True, "documents_closed": closed_docs,
                "action": "quit after closing the documents"}
    for name in _app_names():
        try:
            subprocess.run(["osascript", "-e",
                            f'tell application "{name}" to quit saving no'],
                           capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            pass
        if _gone(min(wait, 8.0)):
            return {"ok": True, "documents_closed": closed_docs,
                    "action": f"quit via AppleScript ({name})"}
    subprocess.run(["pkill", "-x", "Tableau"], capture_output=True, timeout=10)
    if _gone(wait):
        return {"ok": True, "documents_closed": closed_docs,
                "action": "killed by signal (abnormal; Tableau will show [Recovered])"}
    return {"ok": False, "action": "the Tableau window remains; close it manually"}


def wait_until(cond, timeout: float = 90.0, pause: float = 0.8,
               settle: float = 0.0) -> bool:
    """Wait for an event, not for time."""
    deadline = time.time() + max(timeout, pause)
    while time.time() < deadline:
        try:
            if cond():
                if settle:
                    time.sleep(settle)
                return True
        except Exception:
            pass
        time.sleep(pause)
    try:
        return bool(cond())
    except Exception:
        return False


def _is_doc(name: str) -> bool:
    """A window with a real workbook, not an empty Tableau Book."""
    n = str(name or "")
    if not n.startswith("Tableau - "):
        return False
    return not re.fullmatch(r"Book\d+", n[len("Tableau - "):].strip())


def _doc_windows() -> list:
    return [w for w in list_windows() if _is_doc(w.get("name", ""))]


def close_blank_books() -> int:
    """Close the empty Book N windows Tableau opens by itself."""
    killed = 0
    for _ in range(4):
        blanks = [w for w in list_windows()
                  if str(w.get("name", "")).startswith("Tableau - ")
                  and not _is_doc(w.get("name", ""))]
        if not blanks or not _doc_windows():
            break
        if not _close_window(blanks[0]["name"]):
            break
        time.sleep(1.0)
        killed += 1
    return killed


def _ax_all_windows() -> list:
    """All Tableau windows via Accessibility, documents included."""
    r = _osa('tell application "System Events"\n'
             '  if not (exists process "Tableau") then return ""\n'
             '  tell process "Tableau" to return name of every window\n'
             'end tell', timeout=20)
    if r is None or r.returncode != 0:
        return []
    return [t.strip() for t in (r.stdout or "").split(",") if t.strip()]


def window_alive(title: str) -> bool:
    """Whether a window is really alive."""
    ax = _ax_all_windows()
    if ax:
        return title in ax
    return title in [w.get("name") for w in list_windows()]


def _close_window_strict(title: str) -> bool:
    """Close a window by address only."""
    if title not in _ax_all_windows():
        return False
    lit = '"' + str(title).replace("\\", "\\\\").replace('"', '\\"') + '"'
    r = _osa('tell application "System Events" to tell process "Tableau"\n'
             '  set frontmost to true\n'
             '  delay 0.3\n'
             f'  set w to (first window whose name is {lit})\n'
             '  click button 1 of w\n'
             'end tell', timeout=15)
    if r is None or r.returncode != 0:
        return False
    time.sleep(1.0)
    dismiss_dialog()
    return title not in _ax_all_windows()


def _close_front_until_gone(title: str, tries: int = 6) -> bool:
    """Close the front document until the named window is gone."""
    for _ in range(tries):
        if not window_alive(title):
            return True
        r = _osa('tell application "System Events" to tell process "Tableau"\n'
                 '  set frontmost to true\n'
                 '  delay 0.3\n'
                 '  key code 13 using command down\n'
                 '  delay 1.0\n'
                 '  key code 2 using command down\n'
                 'end tell', timeout=20)
        if r is None or r.returncode != 0:
            return False
        time.sleep(1.0)
        dismiss_dialog()
    return not window_alive(title)


def _close_window(title: str) -> bool:
    """Close exactly this window via its close button, not Cmd+W."""
    lit = '"' + str(title).replace("\\", "\\\\").replace('"', '\\"') + '"'
    r = _osa('tell application "System Events" to tell process "Tableau"\n'
             '  set frontmost to true\n'
             '  delay 0.3\n'
             f'  set w to (first window whose name is {lit})\n'
             '  click button 1 of w\n'
             'end tell', timeout=15)
    if r is None or r.returncode != 0:
        return _close_front_until_gone(title)
    wait_until(lambda: not window_alive(title) or bool(list_dialogs()),
               timeout=20.0, pause=0.5)
    dismiss_dialog()
    return wait_until(lambda: not window_alive(title), timeout=20.0, pause=0.5)


def reload_book(book: str, wait: float = 90.0) -> dict:
    """Reload the workbook from disk without quitting the application."""
    stem = os.path.splitext(os.path.basename(book))[0]
    win = window_of(book)
    if win is not None:
        if not _close_window(win["name"]):
            return {"ok": False, "action": "the workbook window did not close"}
        if not wait_until(lambda: not window_alive(win["name"]), timeout=30.0):
            return {"ok": False, "action": f"document {stem!r} did not close"}
    res = open_book(book, wait=wait)
    close_blank_books()
    return {"ok": res["ok"], "action": "reloaded from disk without quitting the application",
            "open": res["action"]}


def close_documents(tries: int = 8) -> int:
    """Close open workbooks politely: Cmd+W, answering Don't Save."""
    closed = 0
    for _ in range(tries):
        docs = _doc_windows()
        if not docs:
            break
        r = _osa('tell application "System Events" to tell process "Tableau"\n'
                 '  set frontmost to true\n'
                 '  delay 0.3\n'
                 '  key code 13 using command down\n'
                 '  delay 1.2\n'
                 '  key code 2 using command down\n'
                 'end tell', timeout=20)
        if r is None or r.returncode != 0:
            break
        time.sleep(1.2)
        dismiss_dialog()
        if len(_doc_windows()) < len(docs):
            closed += 1
    return closed


def _app_names() -> list:
    """Application names for AppleScript: the exact one from /Applications, then the short one."""
    names = []
    if os.path.exists(TABLEAU_APP):
        names.append(os.path.splitext(os.path.basename(TABLEAU_APP))[0])
    names.append("Tableau Desktop")
    return names


def _gone(wait: float) -> bool:
    deadline = time.time() + wait
    while time.time() < deadline:
        if not list_windows():
            return True
        time.sleep(1.5)
    return not list_windows()


def open_book(book: str, wait: float = 90.0, reopen: bool = False) -> dict:
    """Open a workbook in Tableau."""
    if reopen and window_of(book):
        r = reload_book(book, wait)
        return {"ok": r["ok"], "action": r["action"]}
    dismiss_dialog()
    if window_of(book):
        return {"ok": True, "action": "the workbook is already open; left as is"}
    app = TABLEAU_APP if os.path.exists(TABLEAU_APP) else ""
    cmd = ["open"] + (["-a", app] if app else []) + [os.path.abspath(book)]
    subprocess.run(cmd, capture_output=True, timeout=60)
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(2.0)
        if window_of(book):
            return {"ok": True, "action": "opened"}
        if list_dialogs():
            d = dismiss_dialog()
            said = d.get("text") or []
            stem = os.path.splitext(os.path.basename(book))[0]
            if any(stem in t for t in said):
                return {"ok": False, "text": said,
                        "action": "Tableau refused to open the workbook: "
                                    + " · ".join(said[1:])}
    return {"ok": False, "action": "no window appeared in time"}


def wait_stable(book_hint: str = "", tries: int = 20, pause: float = 2.0,
                need: int = 2) -> bool:
    """Wait until rendering settles: the image stops changing for `need` samples in a row."""
    prev, same = None, 0
    tmp = os.path.join(tempfile.gettempdir(), "twkit_stable.png")
    for _ in range(max(tries, need + 1)):
        capture(tmp, book_hint)
        try:
            cur = open(tmp, "rb").read()
        except OSError:
            return False
        if prev is not None and abs(len(cur) - len(prev)) < len(cur) * 0.005:
            same += 1
            if same >= need:
                return True
        else:
            same = 0
        prev = cur
        time.sleep(pause)
    return False


WORK_PREFIX = "twkit_shoot_"

LOCK_PATH = os.path.join(tempfile.gettempdir(), "twkit_tableau.lock")
LOCK_STALE = 900.0


def _lock_owner() -> dict | None:
    """Who holds the lock."""
    try:
        with open(LOCK_PATH, encoding="utf-8") as f:
            held = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() - float(held.get("time", 0)) > LOCK_STALE:
        return None
    pid = int(held.get("pid") or 0)
    if pid and pid != os.getpid():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        except OSError:
            return None
    return held


def acquire_window(book: str = "", wait: float = 0.0) -> dict:
    """Take the Tableau window lock."""
    deadline = time.time() + max(0.0, wait)
    while True:
        held = _lock_owner()
        if held is None:
            try:
                fd = os.open(LOCK_PATH, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"pid": os.getpid(), "time": time.time(),
                               "book": os.path.basename(book)}, f)
                return {"ok": True, "action": "Tableau window lock taken"}
            except OSError as exc:
                return {"ok": False, "why": f"cannot create the lock: {exc}"}
        if held.get("pid") == os.getpid():
            return {"ok": True, "action": "the lock is already ours"}
        if time.time() >= deadline:
            ago = int(time.time() - float(held.get("time", 0)))
            return {"ok": False,
                    "why": f"the Tableau window is held by another session (pid "
                              f"{held.get('pid')}, workbook {held.get('book') or '?'}, "
                              f"{ago} s ago); wait or capture later"}
        time.sleep(1.0)


def release_window() -> None:
    """Release our lock."""
    held = _lock_owner()
    if held is None or held.get("pid") == os.getpid():
        try:
            os.unlink(LOCK_PATH)
        except OSError:
            pass


def work_copy(book: str) -> str:
    """Open only a COPY in Tableau, never the owner's file."""
    import glob
    import shutil
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "twkit_shots")
    os.makedirs(d, exist_ok=True)
    base = os.path.basename(book)
    dst = os.path.join(d, base if base.startswith(WORK_PREFIX) else WORK_PREFIX + base)
    if os.path.abspath(book) == os.path.abspath(dst):
        return book
    for junk in glob.glob(os.path.join(d, ".~*.twbr")):
        try:
            os.remove(junk)
        except OSError:
            pass
    shutil.copy2(book, dst)
    return dst


_WORK_DIRS = ("twkit_shots", "twkit_states")


def work_copies_open(keep: str = "") -> list:
    """Windows of our working copies, except `keep`."""
    stems = set()
    for d in _WORK_DIRS:
        root = os.path.join(tempfile.gettempdir(), d)
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if name.endswith((".twb", ".twbx")):
                stems.add(os.path.splitext(name)[0])
    keep_stem = os.path.splitext(os.path.basename(keep))[0] if keep else None
    out = []
    for w in list_windows():
        name = str(w.get("name", ""))
        if not name.startswith("Tableau - "):
            continue
        stem = name[len("Tableau - "):].strip()
        if stem in stems and stem != keep_stem:
            out.append(name)
    return out


def close_work_copies(keep: str = "") -> int:
    """Close the windows of our working copies."""
    closed = 0
    for name in work_copies_open(keep):
        if _close_window_strict(name):
            closed += 1
    return closed


def compare(before: str, after: str, out_path: str = "") -> dict:
    """How much a screenshot changed."""
    from PIL import Image, ImageChops
    a, b = Image.open(before).convert("RGB"), Image.open(after).convert("RGB")
    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a, b)
    box = diff.getbbox()
    hist = diff.convert("L").histogram()
    changed = sum(hist[24:])
    total = a.size[0] * a.size[1]
    res = {"changed_share": round(changed / total, 4),
           "change_area": box, "size": a.size}
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        diff.save(out_path)
        res["diff_map"] = out_path
    return res


def shoot(book: str, out_path: str = "", wait_render: bool = True,
          reopen: bool = True, settle: float = 45.0) -> dict:
    """Full cycle: reload the workbook, wait for rendering, capture."""
    out_path = out_path or os.path.join(
        os.path.dirname(os.path.abspath(book)), "_shots",
        os.path.splitext(os.path.basename(book))[0] + ".png")
    got = acquire_window(book)
    if not got["ok"]:
        return {"ok": False, "why": got["why"]}
    try:
        prev = _keep_previous(out_path)
        copy = work_copy(book)
        if reopen and not book_changed(book) and window_of(copy):
            reopen = False
        opened = open_book(copy, reopen=reopen)
        if not opened["ok"]:
            return {"ok": False, "why": opened["action"],
                    "error_text": opened.get("text") or []}
        signed = ensure_signed_in(copy)
        if wait_render:
            if settle:
                time.sleep(settle)
            wait_stable(copy, tries=30, pause=3.0)
        res = capture(out_path, copy)
        res["open"] = opened["action"]
        if signed.get("action") and signed["action"] != "sign-in not required":
            res["sign_in"] = signed["action"]
        if res.get("ok") and prev:
            res["change"] = changed_since(prev, out_path)
        return res
    finally:
        release_window()


def _seen_path() -> str:
    return os.path.join(tempfile.gettempdir(), "twkit_seen.json")


def book_changed(book: str) -> bool:
    """Whether the workbook file changed since the last screenshot."""
    try:
        st = os.stat(book)
        sig = [int(st.st_mtime), st.st_size]
    except OSError:
        return True
    try:
        seen = json.load(open(_seen_path(), encoding="utf-8"))
    except Exception:
        seen = {}
    key = os.path.abspath(book)
    changed = seen.get(key) != sig
    seen[key] = sig
    try:
        json.dump(seen, open(_seen_path(), "w", encoding="utf-8"))
    except Exception:
        pass
    return changed


def _keep_previous(out_path: str) -> str:
    """Keep the previous screenshot next to it (`<name>.prev.png`) and return its path, or ''."""
    if not os.path.exists(out_path):
        return ""
    import shutil
    prev = os.path.splitext(out_path)[0] + ".prev.png"
    try:
        shutil.copy2(out_path, prev)
    except OSError:
        return ""
    return prev


def changed_since(prev: str, cur: str) -> dict:
    """What changed on screen since the last screenshot, with an interpretation."""
    try:
        res = compare(prev, cur)
    except Exception as e:
        return {"verdict": f"comparison failed: {e}", "reference": prev}
    share = res.get("changed_share", 0.0)
    res["reference"] = prev
    if share == 0.0:
        res["verdict"] = ("the image did NOT change by a single pixel; if the workbook "
                          "was rebuilt, Tableau showed the old one")
    else:
        res["verdict"] = (f"changed {share:.1%} of the area, region {res.get('change_area')}"
                          "; check that the change is where expected")
    return res


def pages(book: str, sheets: bool = False) -> list:
    """Workbook pages in declaration order; `sheets=True` adds sheets."""
    from . import safexml
    root = safexml.from_twbx(book) if book.endswith(".twbx") else safexml.from_file(book)
    out = [d.get("name") for d in root.iter("dashboard") if d.get("name")]
    if sheets:
        out += [w.get("name") for w in root.iter("worksheet") if w.get("name")]
    return out


def set_active_page(root, name: str) -> bool:
    """Make a page or sheet the one Tableau opens the workbook on."""
    found = False
    for w in root.iter("window"):
        if w.get("class") not in ("dashboard", "worksheet"):
            continue
        if w.get("name") == name:
            w.set("maximized", "true")
            found = True
        elif w.get("maximized"):
            del w.attrib["maximized"]
    return found


def shoot_all_pages(book: str, out_dir: str = "", only: list = None,
                    settle: float = 45.0) -> dict:
    """Capture every page of a workbook."""
    import shutil
    import zipfile

    from lxml import etree

    from . import safexml

    book = os.path.abspath(book)
    stem = os.path.splitext(os.path.basename(book))[0]
    out_dir = out_dir or os.path.join(os.path.dirname(book), "_shots", stem)
    os.makedirs(out_dir, exist_ok=True)

    want = only or pages(book)
    got, failed = {}, {}
    work = os.path.join(tempfile.gettempdir(), f"twkit_shoot_{stem}.twbx")
    with zipfile.ZipFile(book) as z:
        names = z.namelist()
        twb = next(n for n in names if n.endswith(".twb"))

    for page in want:
        root = safexml.from_twbx(book)
        if not set_active_page(root, page):
            failed[page] = "page not in the workbook"
            continue
        body = etree.tostring(root, xml_declaration=False, encoding="utf-8")
        if not body.lstrip().startswith(b"<?xml"):
            body = b"<?xml version='1.0' encoding='utf-8' ?>\n\n" + body
        with zipfile.ZipFile(book) as src, \
             zipfile.ZipFile(work, "w", zipfile.ZIP_DEFLATED) as dst:
            for n in names:
                dst.writestr(n, body if n == twb else src.read(n))
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in page).strip()
        out = os.path.join(out_dir, f"{safe}.png")
        res = shoot(work, out_path=out, reopen=True, settle=settle)
        if res.get("ok"):
            got[page] = out
        else:
            failed[page] = res.get("why") or res
        close_work_copies()
    if os.path.exists(work):
        os.unlink(work)
    write_gallery(out_dir, stem, got)
    return {"removed": got, "failed": failed, "gallery": os.path.join(out_dir, "index.html")}


def write_gallery(out_dir: str, title: str, shots: dict) -> str:
    """Gallery: index.html with all pages, for viewing in a browser."""
    import datetime as _dt
    import html

    items = "\n".join(
        f'<figure><figcaption>{html.escape(p)}</figcaption>'
        f'<img src="{html.escape(os.path.basename(f))}" loading="lazy"></figure>'
        for p, f in shots.items())
    doc = f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(title)} - pages</title>
<style>
 body{{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:24px;background:#f7f8fa;color:#111}}
 h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#666;margin:0 0 20px}}
 figure{{margin:0 0 28px;background:#fff;border:1px solid #e3e6ea;border-radius:8px;overflow:hidden}}
 figcaption{{padding:10px 14px;font-weight:600;border-bottom:1px solid #eef1f3}}
 img{{display:block;width:100%;height:auto}}
</style>
<h1>{html.escape(title)}</h1>
<p class="sub">captured {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')} - pages {len(shots)} -
a REAL Tableau render, not our model</p>
{items}
"""
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


def shoot_states(book: str, param: str, values: list = None, out_dir: str = "",
                 settle: float = 18.0) -> dict:
    """Capture a dashboard in every state of a switcher."""
    from twkit import edit as ED
    from twkit import safexml

    root = safexml.from_twbx(book)
    values = values or ED.parameter_members(root, param)
    if not values:
        return {"ok": False, "why": f"parameter '{param}' is not in the workbook"}
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(book)), "_shots")
    os.makedirs(out_dir, exist_ok=True)

    shots, problems, prev_copy = {}, [], ""
    for value in values:
        root = safexml.from_twbx(book)
        if not ED.set_parameter_value(root, param, value):
            problems.append(f"{value}: value was not set")
            continue
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in value).strip()
        copy = os.path.join(tempfile.gettempdir(), "twkit_states",
                            f"{WORK_PREFIX}"
                            f"{os.path.splitext(os.path.basename(book))[0]} — {safe}.twbx")
        os.makedirs(os.path.dirname(copy), exist_ok=True)
        safexml.to_twbx(book, root, copy)
        close_work_copies(keep=copy)
        prev_copy = copy
        opened = open_book(copy, reopen=False)
        if not opened["ok"]:
            problems.append(f"{value}: {opened['action']}")
            continue
        ensure_signed_in(copy)
        time.sleep(settle)
        wait_stable(copy, tries=6, pause=2.5)
        png = os.path.join(out_dir, f"{param}_{safe}.png")
        res = capture(png, copy)
        shots[value] = png if res.get("ok") else ""
        close_work_copies()
        if not res.get("ok"):
            problems.append(f"{value}: {res.get('why', '')}")
    return {"ok": not problems, "screenshots": shots, "failed": problems,
            "next": "open each screenshot with Read and look"}


_GREYISH = 26


def color_census(png: str, palette: dict, box: tuple = None) -> dict:
    """Pixel count of each given color in a screenshot."""
    try:
        from PIL import Image
    except ImportError:
        return {"ok": False, "why": "PIL is not installed"}
    if not os.path.exists(png):
        return {"ok": False, "why": f"file not found: {png}"}
    im = Image.open(png).convert("RGB")
    x0, y0, x1, y1 = box or (0, 0, im.size[0], im.size[1])
    want = {}
    for name, hexv in palette.items():
        h = hexv.lstrip("#")
        want[name] = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    counts = {name: 0 for name in want}
    px = im.load()
    for y in range(max(0, y0), min(im.size[1], y1), 2):
        for x in range(max(0, x0), min(im.size[0], x1), 2):
            r, g, b = px[x, y]
            if max(r, g, b) - min(r, g, b) < _GREYISH:
                continue
            for name, (tr, tg, tb) in want.items():
                if abs(r - tr) + abs(g - tg) + abs(b - tb) <= 60:
                    counts[name] += 1
                    break
    return {"ok": True, "pixels": counts}


def _open_ledger_path() -> str:
    return os.path.join(tempfile.gettempdir(), "twkit_open_ledger.json")


def check_open(books: list, timeout: float = 150.0, close_after: bool = True,
               only_changed: bool = True) -> list:
    """Whether a workbook opens in Tableau, judged by the log without a screenshot (13-60 s each)."""
    from . import tablog
    out = []
    try:
        with open(_open_ledger_path()) as f:
            ledger = json.load(f)
    except Exception:
        ledger = {}
    todo = []
    for b in books:
        fp = book_fingerprint(b)
        if only_changed and ledger.get(fp) == "opened":
            out.append({"book": os.path.basename(b), "result": "opened",
                        "text": "unchanged since the last check; not opened", "sec": 0})
        else:
            todo.append((b, fp))
    if not todo:
        return out
    try:
        for b, fp in todo:
            close_tableau()
            hint = os.path.splitext(os.path.basename(b))[0]
            t0 = time.time()
            since = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(t0 - 1))
            open_book(b, wait=5)
            verdict, text = "timeout", ""
            while time.time() - t0 < timeout:
                dl = [d for d in tablog.error_dialogs(2_000_000)
                      if hint in d["text"] and (d["ts"] or "") >= since]
                if dl:
                    verdict = "warning dialog" if dl[-1]["warning"] else "error dialog"
                    text = dl[-1]["text"]
                    break
                if window_of(hint):
                    verdict = "opened"
                    break
                time.sleep(3)
            out.append({"book": os.path.basename(b), "result": verdict, "text": text,
                        "sec": round(time.time() - t0)})
            ledger[fp] = verdict
            try:
                with open(_open_ledger_path(), "w") as f:
                    json.dump(ledger, f)
            except Exception:
                pass
    finally:
        if close_after:
            close_tableau()
    return out


_UUID_RE = re.compile(r"\{?[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}?")
_CALC_RE = re.compile(r"Calculation_[0-9A-Fa-f]{16,32}")
_FP_FILE = "_fingerprints.json"


def book_fingerprint(path: str) -> str:
    """Content fingerprint of a workbook; stable across rebuilds without edits."""
    import hashlib
    import zipfile
    h = hashlib.sha1()
    if path.lower().endswith(".twbx"):
        with zipfile.ZipFile(path) as z:
            for n in sorted(z.namelist()):
                data = z.read(n)
                if n.lower().endswith(".twb"):
                    txt = _UUID_RE.sub("U", data.decode("utf-8", "replace"))
                    txt = _CALC_RE.sub("Calculation_X", txt)
                    data = "\n".join(sorted(txt.split(">"))).encode()
                    data = re.sub(rb"<!--[^>]*-->", b"", data)
                h.update(n.encode() + b"\0" + data)
    else:
        with open(path, "rb") as f:
            h.update(_UUID_RE.sub("U", f.read().decode("utf-8", "replace")).encode())
    return h.hexdigest()


def needs_shot(books: list, shots_dir: str) -> list:
    """Workbooks without a screenshot or changed since the last one."""
    try:
        with open(os.path.join(shots_dir, _FP_FILE)) as f:
            known = json.load(f)
    except Exception:
        known = {}
    out = []
    for b in books:
        png = os.path.join(shots_dir, os.path.splitext(os.path.basename(b))[0] + ".png")
        if not os.path.exists(png) or known.get(os.path.basename(b)) != book_fingerprint(b):
            out.append(b)
    return out


def remember_shot(book: str, shots_dir: str) -> None:
    """Record the fingerprint of a workbook just captured."""
    p = os.path.join(shots_dir, _FP_FILE)
    try:
        with open(p) as f:
            known = json.load(f)
    except Exception:
        known = {}
    known[os.path.basename(book)] = book_fingerprint(book)
    os.makedirs(shots_dir, exist_ok=True)
    with open(p, "w") as f:
        json.dump(known, f, ensure_ascii=False, indent=1)


def remember_open(book: str, verdict: str = "opened") -> None:
    """Record a successful open: a good screenshot proves the workbook opened."""
    p = _open_ledger_path()
    try:
        with open(p) as f:
            ledger = json.load(f)
    except Exception:
        ledger = {}
    ledger[book_fingerprint(book)] = verdict
    with open(p, "w") as f:
        json.dump(ledger, f)
