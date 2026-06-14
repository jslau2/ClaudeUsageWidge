# Claude Quota Widget

A small always-on-top desktop widget showing your live Claude plan usage — the
same numbers as the Claude app / `/usage`. Frameless, drag to move.

## Run

Double-click `claude_usage_widget.pyw` (the `.pyw` extension runs it with
`pythonw`, so no console window appears).

To see errors while debugging: `python claude_usage_widget.pyw`

## What it shows

- **5-hour** and **weekly** usage %, color bars (green <50, yellow 50–80, red ≥80),
  and reset countdowns. Per-model rows appear automatically if your plan has them.
- **Weekly daily milestones** — each weekly bar is notched into 7 day-segments,
  with an even-burn **pace marker**. Two styles, switchable live via the header
  `┊`/`▤` button (default `notch`):
  - **notch** — a thin white line marks where even-burn pace would be.
  - **expected** — a dim "expected by now" fill behind the bright actual fill.

  Either way, your fill being past the pace marker = "ahead of pace" (burning
  faster than even), and a `Day N/7 · on track / ahead of pace` label shows the
  current day. Set the startup default with `MILESTONE_STYLE` in the `.pyw`.
- **5-hour pace marker** — the session bar gets the same pace marker (notch line
  or expected fill, per the chosen style) but no day splits.
- Refreshes every 5 min (the endpoint rate-limits faster polling). `⟳` = refresh now.

## Controls

- **Drag** anywhere on the header to move it.
- `▲` always-on-top toggle · `┊`/`▤` weekly pace style (notch ↔ expected) ·
  `□` show/hide OS window frame · `⟳` refresh ·
  `–` collapse to mini-bar · `×` close.
- **Mini-bar** — `–` shrinks the widget to a tiny always-on-top strip docked in
  the bottom-right corner, beside the tray (`Claude 81% wk · 1d`). It shows your
  most-constrained window, color-coded, and keeps updating live. **Click** it to
  expand back; **drag** it to reposition. Pure standard library — no install.

## Features

- **Live data** from `https://api.anthropic.com/api/oauth/usage`, using your
  OAuth token in `~/.claude/.credentials.json` (read fresh each poll, so token
  refreshes are picked up). No local cache.
- **Desktop alert** (native toast) when any window hits **80%**.
- **Live mini-bar** — collapse to a compact strip beside the tray (see Controls).
  Standard library only.
- **Minimize to system tray** — optional fallback, only if you install
  `pip install pystray pillow` (the dormant `to_tray` code path).

## Config (edit top of the .pyw)

| Setting | Default | Meaning |
|---|---|---|
| `REFRESH_SECONDS` | `300` | Auto-poll interval (keep ≥180) |
| `MIN_REFRESH_GAP` | `180` | Manual ⟳ blocked within this many seconds |
| `ALERT_THRESHOLD` | `80` | % that triggers the toast |
| `WIDTH` | `290` | Window width (height auto-fits) |

## Auto-start on login

Double-click `install_autostart.bat` once. It writes `ClaudeUsageWidget.bat`
into your Startup folder, pointing at this widget (paths are auto-resolved, so
it keeps working if you move the repo).

The startup launcher also opens a `claude` CLI session. Its working directory is
resolved without hardcoding, in this order:

1. First argument to the script — `install_autostart.bat "D:\path\to\workspace"`
2. The `CLAUDE_WORKSPACE` environment variable
3. The repo folder itself (fallback)

To remove: delete `ClaudeUsageWidget.bat` from the Startup folder.

## Note

Uses your subscription OAuth token against an undocumented endpoint — personal,
read-only convenience. Don't share the token or build anything public on it.
