#!/usr/bin/env python3
"""
Claude Quota Widget — live plan-usage monitor (mirrors the Claude app / `/usage`).

Fetches the same quota data the Claude app shows from the authenticated
endpoint  GET https://api.anthropic.com/api/oauth/usage  using your local
OAuth token (~/.claude/.credentials.json). No local cache — fresh every poll.

Pure standard library: Tkinter + urllib. No pip installs.

Run:  python claude_usage_widget.py

Note: this uses your Claude subscription OAuth token to read your own usage.
It is an unofficial endpoint; treat it as a personal, read-only convenience.
"""

import json
import os
import ssl
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
import tkinter as tk
from tkinter import font as tkfont

# Optional: minimize-to-tray. Activates only if both are installed:
#   pip install pystray pillow
try:
    import pystray
    from PIL import Image, ImageDraw
    HAVE_TRAY = True
except Exception:
    HAVE_TRAY = False

# --- Configuration -----------------------------------------------------------

CREDS_PATH = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLI_VERSION = "2.1.177"                 # used in User-Agent
REFRESH_SECONDS = 300                   # >=180s; endpoint rate-limits per token
TIMEOUT = 15
ALERT_THRESHOLD = 80                    # desktop toast when a window hits this %
MIN_REFRESH_GAP = 180                   # block manual ⟳ within this many seconds
MILESTONE_STYLE = "notch"               # weekly pace style: "notch" or "expected"
                                        # (toggle live with the header ┊/▤ button)

# Friendly labels + display order for the windows the endpoint returns.
WINDOW_LABELS = [
    ("five_hour",          "5-hour (session)"),
    ("seven_day",          "Weekly (all models)"),
    ("seven_day_opus",     "Weekly · Opus"),
    ("seven_day_sonnet",   "Weekly · Sonnet"),
    ("seven_day_oauth_apps", "Weekly · apps"),
    ("seven_day_cowork",   "Weekly · cowork"),
]

# Colors
BG = "#1e1e2e"
PANEL = "#181825"
FG = "#cdd6f4"
DIM = "#6c7086"
ACCENT = "#89b4fa"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
RED = "#f38ba8"
TRACK = "#313244"          # empty bar
EXPECTED = "#585b70"       # dim "should be here by now" fill (even-burn pace)


# --- Data fetch --------------------------------------------------------------

class RateLimited(Exception):
    def __init__(self, retry_after):
        super().__init__("Rate limited (429)")
        self.retry_after = retry_after


def read_token():
    with open(CREDS_PATH, "r", encoding="utf-8") as f:
        creds = json.load(f)
    oauth = creds.get("claudeAiOauth") or {}
    return oauth.get("accessToken"), oauth.get("expiresAt"), oauth.get("subscriptionType")


def fetch_usage():
    """Return (data_dict, sub_type). Raises on error."""
    token, expires_at, sub = read_token()
    if not token:
        raise RuntimeError("No OAuth token found — run any `claude` command to log in.")

    req = urllib.request.Request(USAGE_URL, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("anthropic-beta", "oauth-2025-04-20")
    req.add_header("User-Agent", f"claude-cli/{CLI_VERSION} (external)")
    req.add_header("Content-Type", "application/json")

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8")), sub
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("Token expired (401). Run any `claude` command "
                               "to refresh, then Refresh here.")
        if e.code == 429:
            ra = e.headers.get("retry-after") if e.headers else None
            try:
                ra = int(ra)
            except (TypeError, ValueError):
                ra = 300
            raise RateLimited(ra)
        raise RuntimeError(f"HTTP {e.code}: {e.reason}")


def pace_fraction(reset_iso, window_days):
    """How far through the rolling window we are, 0..1 (None if unknown).

    The window started window_days before it resets, so elapsed fraction is
    1 - (time_until_reset / window). Lets us mark even-burn pace on the bar.
    """
    if not reset_iso or not window_days:
        return None
    try:
        t = datetime.fromisoformat(reset_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    total = window_days * 86400.0
    remaining = (t - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, min(1.0, 1.0 - remaining / total))


def color_for(pct):
    if pct is None:
        return DIM
    if pct >= 80:
        return RED
    if pct >= 50:
        return YELLOW
    return GREEN


def notify(title, msg):
    """Best-effort native Windows balloon toast (no extra installs)."""
    try:
        ps = (
            '[reflection.assembly]::LoadWithPartialName("System.Windows.Forms")>$null;'
            '$n=New-Object System.Windows.Forms.NotifyIcon;'
            '$n.Icon=[System.Drawing.SystemIcons]::Warning;$n.Visible=$true;'
            f'$n.ShowBalloonTip(8000,"{title}","{msg}",'
            '[System.Windows.Forms.ToolTipIcon]::Warning);'
            'Start-Sleep -Seconds 9;$n.Dispose()'
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def fmt_reset(iso):
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    local = t.astimezone()
    delta = t - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "resetting…"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h >= 24:
        d = h // 24
        rel = f"{d}d {h % 24}h"
    elif h:
        rel = f"{h}h {m}m"
    else:
        rel = f"{m}m"
    return f"resets in {rel}  ({local.strftime('%a %d %b %H:%M')})"


def fmt_reset_short(iso):
    """Terse single-unit time-to-reset: '4d' / '3h' / '45m' / 'now'."""
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    secs = int((t - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "now"
    h, rem = divmod(secs, 3600)
    if h >= 24:
        return f"{h // 24}d"
    if h:
        return f"{h}h"
    return f"{rem // 60}m"


def fmt_reset_hm(iso):
    """Reset time with hour+minute granularity: '2h 13m' / '45m' / '1d 3h'."""
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    secs = int((t - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "now"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h >= 24:
        return f"{h // 24}d {h % 24}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# --- GUI ---------------------------------------------------------------------

WIDTH = 290

class Widget:
    def __init__(self, root):
        self.root = root
        self.alerted = set()        # windows already toasted this period
        self.tray = None
        self.last = None            # last good (data, sub)
        self._after_id = None
        self._last_attempt = 0.0    # monotonic time of last network attempt
        self.topmost = True
        self.framed = False         # start frameless
        self.minimized = False      # collapsed to the mini-bar?
        self._mini_moved = False    # distinguish a drag from a click on the bar
        self.milestone_style = MILESTONE_STYLE  # "notch" | "expected"

        root.title("Claude Quota")
        root.configure(bg=BG)
        root.overrideredirect(True)         # frameless: no OS title bar
        root.attributes("-topmost", True)
        root.geometry(f"{WIDTH}x120+80+80")
        root.protocol("WM_DELETE_WINDOW", self.quit)

        self.f_label = tkfont.Font(family="Segoe UI", size=10)
        self.f_bold = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.f_pct = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_small = tkfont.Font(family="Segoe UI", size=8)
        self.f_btn = tkfont.Font(family="Segoe UI", size=10, weight="bold")

        # Header doubles as the drag handle (no title bar to grab).
        self.hdr = hdr = tk.Frame(root, bg=BG)
        hdr.pack(fill="x", padx=8, pady=(6, 2))
        self.title_lbl = tk.Label(hdr, text="CLAUDE USAGE", font=self.f_bold,
                                  bg=BG, fg=ACCENT)
        self.title_lbl.pack(side="left")
        tk.Button(hdr, text="×", font=self.f_btn, command=self.quit,
                  bg=BG, fg=DIM, bd=0, activebackground=BG,
                  activeforeground=RED).pack(side="right")
        tk.Button(hdr, text="–", font=self.f_btn, command=self.to_mini,
                  bg=BG, fg=DIM, bd=0, activebackground=BG,
                  activeforeground=FG).pack(side="right")
        tk.Button(hdr, text="⟳", font=self.f_btn, command=self.refresh,
                  bg=BG, fg=DIM, bd=0, activebackground=BG,
                  activeforeground=ACCENT).pack(side="right")
        tk.Button(hdr, text="□", font=self.f_btn, command=self.toggle_frame,
                  bg=BG, fg=DIM, bd=0, activebackground=BG,
                  activeforeground=FG).pack(side="right")
        self.style_btn = tk.Button(
            hdr, text=("┊" if self.milestone_style == "notch" else "▤"),
            font=self.f_btn, command=self.toggle_milestone, bg=BG, fg=DIM,
            bd=0, activebackground=BG, activeforeground=FG)
        self.style_btn.pack(side="right")
        self.pin_btn = tk.Button(hdr, text="▲", font=self.f_btn,
                                 command=self.toggle_top, bg=BG, fg=ACCENT, bd=0,
                                 activebackground=BG, activeforeground=FG)
        self.pin_btn.pack(side="right")
        for w in (hdr, self.title_lbl):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        # Persistent footer: last successful refresh time (not cleared on redraw).
        self.status = tk.Label(root, text="—", font=self.f_small, bg=BG, fg=DIM,
                               anchor="e")
        self.status.pack(fill="x", side="bottom", padx=10, pady=(0, 5))

        self.body = tk.Frame(root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # Minimized "mini-bar" — built once, packed only while collapsed.
        self.mini = tk.Frame(root, bg=BG, cursor="hand2")
        mini_inner = tk.Frame(self.mini, bg=PANEL)
        mini_inner.pack(fill="both", expand=True, padx=2, pady=2)
        self.mini_title = tk.Label(mini_inner, text="Claude", font=self.f_bold,
                                   bg=PANEL, fg=ACCENT)
        self.mini_title.pack(side="left", padx=(8, 4), pady=4)
        # 5-hour session: the headline — big, bold, colored % + its reset time.
        self.mini_pct = tk.Label(mini_inner, text="—", font=self.f_pct,
                                 bg=PANEL, fg=DIM)
        self.mini_pct.pack(side="left", padx=(0, 4), pady=4)
        self.mini_sub = tk.Label(mini_inner, text="", font=self.f_small,
                                 bg=PANEL, fg=DIM)
        self.mini_sub.pack(side="left", padx=(0, 8), pady=4)
        # Weekly: de-emphasized — small, dim, no color.
        self.mini_week = tk.Label(mini_inner, text="", font=self.f_small,
                                  bg=PANEL, fg=DIM)
        self.mini_week.pack(side="left", padx=(0, 8), pady=4)
        for w in (self.mini, mini_inner, self.mini_title, self.mini_pct,
                  self.mini_sub, self.mini_week):
            w.bind("<Button-1>", self._mini_press)
            w.bind("<B1-Motion>", self._mini_drag)
            w.bind("<ButtonRelease-1>", self._mini_release)

        self.refresh()
        self._stay_on_top()

    # --- keep above the (topmost) Windows taskbar ---
    def _stay_on_top(self):
        # The taskbar is itself a topmost window; clicking it re-raises it above
        # us. Re-asserting -topmost periodically climbs us back to the front of
        # the topmost band. This doesn't steal keyboard focus.
        if self.topmost:
            try:
                self.root.attributes("-topmost", True)
                self.root.lift()
            except tk.TclError:
                pass
        self.root.after(REFRESH_SECONDS * 1000, self._stay_on_top)

    # --- window move (frameless) ---
    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        self.root.geometry(f"+{self.root.winfo_pointerx() - self._dx}"
                           f"+{self.root.winfo_pointery() - self._dy}")

    def toggle_top(self):
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.pin_btn.config(fg=ACCENT if self.topmost else DIM)

    def toggle_milestone(self):
        self.milestone_style = ("expected" if self.milestone_style == "notch"
                                else "notch")
        self.style_btn.config(
            text="┊" if self.milestone_style == "notch" else "▤")
        if self.last is not None:
            self._render(*self.last)

    def toggle_frame(self):
        self.framed = not self.framed
        # On Windows the frame change only takes effect after a re-map.
        self.root.overrideredirect(not self.framed)
        self.root.withdraw()
        self.root.after(10, self._remap)

    def _remap(self):
        self.root.deiconify()
        self.root.attributes("-topmost", self.topmost)
        self._fit()

    def quit(self):
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    # --- tray (optional) ---
    def to_tray(self):
        self.root.withdraw()
        if self.tray:
            return
        img = Image.new("RGB", (64, 64), BG)
        ImageDraw.Draw(img).ellipse((12, 12, 52, 52), fill=ACCENT)
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: self.root.after(0, self.root.deiconify),
                             default=True),
            pystray.MenuItem("Refresh", lambda: self.root.after(0, self.refresh)),
            pystray.MenuItem("Quit", lambda: self.root.after(0, self.quit)),
        )
        self.tray = pystray.Icon("claude_quota", img, "Claude Usage", menu)
        self.tray.run_detached()

    # --- mini-bar (collapsed, lives beside the tray) ---
    def _update_mini(self, data):
        # 5-hour session is the headline: bold colored % + "resets in xx hr/min".
        five = data.get("five_hour") if isinstance(data, dict) else None
        if isinstance(five, dict) and five.get("utilization") is not None:
            pct = float(five["utilization"])
            self.mini_pct.config(text=f"{pct:.0f}%", fg=color_for(pct))
            rel = fmt_reset_hm(five.get("resets_at"))
            self.mini_sub.config(text=rel)
        else:
            self.mini_pct.config(text="—", fg=DIM)
            self.mini_sub.config(text="")

        # Weekly: small, dim, no color — just a quiet reference figure.
        week = data.get("seven_day") if isinstance(data, dict) else None
        if isinstance(week, dict) and week.get("utilization") is not None:
            wpct = float(week["utilization"])
            wrel = fmt_reset_short(week.get("resets_at"))
            self.mini_week.config(text=f"{wpct:.0f}%  {wrel}" if wrel
                                  else f"{wpct:.0f}%")
        else:
            self.mini_week.config(text="")

    def to_mini(self):
        if self.minimized:
            return
        self.minimized = True
        self.hdr.pack_forget()
        self.body.pack_forget()
        self.status.pack_forget()
        self.mini.pack(fill="both", expand=True)
        self.root.overrideredirect(True)
        if self.last is not None:
            self._update_mini(self.last[0])
        # Size to content, then dock at the bottom-right, just above the tray.
        self.root.update_idletasks()
        w = self.mini.winfo_reqwidth()
        h = self.mini.winfo_reqheight()
        x = self.root.winfo_screenwidth() - w - 16
        y = self.root.winfo_screenheight() - h - 56
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.attributes("-topmost", True)

    def from_mini(self):
        if not self.minimized:
            return
        self.minimized = False
        self.mini.pack_forget()
        self.hdr.pack(fill="x", padx=8, pady=(6, 2))
        self.status.pack(fill="x", side="bottom", padx=10, pady=(0, 5))
        self.body.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.root.overrideredirect(not self.framed)
        self.root.attributes("-topmost", self.topmost)
        if self.last is not None:
            self._render(*self.last)
        else:
            self._fit()

    def _mini_press(self, e):
        self._mini_moved = False
        self._dx, self._dy = e.x, e.y

    def _mini_drag(self, e):
        self._mini_moved = True
        self.root.geometry(f"+{self.root.winfo_pointerx() - self._dx}"
                           f"+{self.root.winfo_pointery() - self._dy}")

    def _mini_release(self, e):
        if not self._mini_moved:
            self.from_mini()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _row(self, label, pct, reset_iso, segments=0, window_days=0):
        c = color_for(pct)
        wrap = tk.Frame(self.body, bg=PANEL)
        wrap.pack(fill="x", pady=3)
        top = tk.Frame(wrap, bg=PANEL)
        top.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(top, text=label, font=self.f_label, bg=PANEL, fg=FG).pack(side="left")
        tk.Label(top, text=("—" if pct is None else f"{pct:.0f}%"),
                 font=self.f_pct, bg=PANEL, fg=c).pack(side="right")

        track = tk.Frame(wrap, bg=TRACK, height=8)
        track.pack(fill="x", padx=10, pady=(0, 2))
        track.pack_propagate(False)
        frac = 0 if pct is None else max(0.0, min(1.0, pct / 100.0))
        pace = pace_fraction(reset_iso, window_days)

        # Style "expected": dim "expected by now" fill behind the actual fill,
        # so any bright poking past the dim region = ahead of pace. Behind fill.
        if segments and pace is not None and self.milestone_style == "expected":
            tk.Frame(track, bg=EXPECTED, height=8).place(
                relwidth=pace, relheight=1.0)

        fill = tk.Frame(track, bg=c, height=8)
        fill.place(relwidth=frac, relheight=1.0)

        # Day-segment notches (weekly only), on top of the fills.
        if segments:
            for i in range(1, segments):
                tk.Frame(track, bg=PANEL, width=1).place(
                    relx=i / segments, rely=0.0, relheight=1.0)
        # Style "notch": thin pace marker line — drawn for any window with a
        # known pace (weekly and the 5-hour session), over the notches.
        if pace is not None and self.milestone_style == "notch":
            tk.Frame(track, bg=FG, width=2).place(
                relx=min(pace, 0.992), rely=0.0, relheight=1.0)

        if segments and pace is not None:
            day = min(segments, int(pace * segments) + 1)
            ahead = pct is not None and frac > pace
            tag = "ahead of pace" if ahead else "on track"
            tk.Label(wrap, text=f"Day {day}/{segments} · {tag}",
                     font=self.f_small, bg=PANEL,
                     fg=(RED if ahead else GREEN), anchor="w").pack(
                     fill="x", padx=10, pady=(0, 0))

        if reset_iso:
            tk.Label(wrap, text=fmt_reset(reset_iso), font=self.f_small, bg=PANEL,
                     fg=DIM, anchor="w").pack(fill="x", padx=10, pady=(0, 6))
        else:
            tk.Frame(wrap, bg=PANEL, height=4).pack()

    def _message(self, text, color=DIM):
        tk.Label(self.body, text=text, font=self.f_small, bg=BG, fg=color,
                 wraplength=WIDTH - 30, justify="left").pack(pady=10, padx=8)

    def _check_alert(self, key, label, pct):
        if pct is not None and pct >= ALERT_THRESHOLD:
            if key not in self.alerted:
                self.alerted.add(key)
                notify("Claude usage high", f"{label}: {pct:.0f}% used")
        else:
            self.alerted.discard(key)

    def _schedule(self, secs):
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(int(secs * 1000), self.refresh)

    def _render(self, data, sub, banner=None, banner_color=DIM):
        # While collapsed, only the mini-bar is visible — keep it fresh and skip
        # the (hidden) full rebuild + the geometry refit it would trigger.
        if self.minimized:
            self._update_mini(data)
            return
        self._clear()
        if banner:
            tk.Label(self.body, text=banner, font=self.f_small, bg=BG,
                     fg=banner_color, anchor="w").pack(fill="x", padx=10, pady=(2, 0))
        self.title_lbl.config(text=f"CLAUDE · {(sub or 'plan').upper()}")
        shown = 0
        for key, label in WINDOW_LABELS:
            win = data.get(key)
            if isinstance(win, dict) and win.get("utilization") is not None:
                pct = float(win["utilization"])
                # Weekly windows get 7 daily milestone ticks + a pace marker;
                # the 5-hour session gets the pace marker only (no splits).
                if key.startswith("seven_day"):
                    segs, wdays = 7, 7
                elif key == "five_hour":
                    segs, wdays = 0, 5 / 24
                else:
                    segs, wdays = 0, 0
                self._row(label, pct, win.get("resets_at"),
                          segments=segs, window_days=wdays)
                self._check_alert(key, label, pct)
                shown += 1
        extra = data.get("extra_usage")
        if isinstance(extra, dict) and extra.get("is_enabled"):
            util = extra.get("utilization")
            self._row("Extra usage credits",
                      float(util) if util is not None else None,
                      extra.get("resets_at"))
            shown += 1
        if not shown:
            self._message("No active usage windows.\n"
                          "(API-key accounts have no subscription quota.)")
        self._update_mini(data)
        self._fit()

    def refresh(self):
        # Guard against ⟳ spam: don't hit the network more than once per gap.
        gap = time.monotonic() - self._last_attempt
        if gap < MIN_REFRESH_GAP and self.last is not None:
            wait = int(MIN_REFRESH_GAP - gap)
            self._render(*self.last,
                         banner=f"too soon — wait {wait}s", banner_color=YELLOW)
            self._schedule(MIN_REFRESH_GAP - gap)
            return

        self._last_attempt = time.monotonic()
        try:
            data, sub = fetch_usage()
        except RateLimited as e:
            wait = max(e.retry_after, 180)
            if self.last is not None:
                self._render(*self.last,
                             banner=f"rate limited — retry in {wait}s (showing last)",
                             banner_color=YELLOW)
            else:
                self._clear()
                self.title_lbl.config(text="CLAUDE USAGE")
                self._message(f"Rate limited (429). Retrying in {wait}s.\n"
                              "Tip: avoid clicking ⟳ repeatedly.", YELLOW)
                self._fit()
            self._schedule(wait)
            return
        except Exception as e:
            if self.last is not None:
                self._render(*self.last, banner=f"error: {e} (showing last)",
                             banner_color=RED)
            else:
                self._clear()
                self.title_lbl.config(text="CLAUDE USAGE")
                self._message(str(e), RED)
                self._fit()
            self._schedule(REFRESH_SECONDS)
            return

        self.last = (data, sub)
        self.status.config(text="updated " + datetime.now().strftime("%H:%M:%S"))
        self._render(data, sub)
        self._schedule(REFRESH_SECONDS)

    def _fit(self):
        """Shrink height to exactly fit the content."""
        if self.minimized:
            return  # the mini-bar manages its own (fixed) geometry
        self.root.update_idletasks()
        self.root.geometry(f"{WIDTH}x{self.root.winfo_reqheight()}")


def main():
    root = tk.Tk()
    Widget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
