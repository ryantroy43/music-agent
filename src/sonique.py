"""
Sonique — AI Music Recommendation Agent
Windows system tray app with Now Playing detection.

Install:  pip install anthropic pystray pillow pywin32
Run:      pythonw sonique.py   (no console window)
          python  sonique.py   (with console, for debugging)
"""

import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from pathlib import Path

# ── Dependency check ──────────────────────────────────────────────────────────
missing = []
try:
    import anthropic
except ImportError:
    missing.append("anthropic")
try:
    from PIL import Image, ImageDraw
    import pystray
except ImportError:
    missing.append("pystray pillow")

if missing:
    root = tk.Tk(); root.withdraw()
    from tkinter import messagebox
    messagebox.showerror(
        "Missing packages",
        f"Run this in PowerShell:\n\npy -m pip install {' '.join(missing)}"
    )
    sys.exit(1)

# pywin32 is optional — needed for window title scanning
try:
    import win32gui
    import win32process
    import psutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

# ── Config ────────────────────────────────────────────────────────────────────
DATA_FILE     = Path.home() / ".sonique_history.json"
SETTINGS_FILE = Path.home() / ".sonique_settings.json"
MODEL         = "claude-opus-4-5"

GENRES = [
    "Pop", "Hip-Hop / Rap", "R&B / Soul", "Rock", "Indie / Alternative",
    "Electronic / EDM", "Jazz", "Classical", "Country", "Metal",
    "Folk / Acoustic", "Latin", "K-Pop", "Afrobeats", "Reggae", "Other",
]

ACCENT  = "#1D9E75"
DARK    = "#0F6E56"
BG      = "#F8F8F7"
SURFACE = "#FFFFFF"
BORDER  = "#E0DED8"
TEXT    = "#1A1A18"
MUTED   = "#6B6B68"
RED     = "#A32D2D"
RED_BG  = "#FCEBEB"
AMBER   = "#854F0B"

# ── Now Playing detection ─────────────────────────────────────────────────────

# YouTube title formats vary by browser and whether playing:
#   Chrome/Edge:  "Song - Artist - YouTube"  or  "▶ Song - Artist - YouTube"
#   Firefox:      "Song - Artist — YouTube"
#   Some videos:  "Song - YouTube"  (no artist in title)
# SoundCloud:     "Song - Artist on SoundCloud"  or  "Song by Artist on SoundCloud"
# Tidal:          "Song - Artist | TIDAL"
# Apple Music:    "Song - Artist - Apple Music"
# Amazon Music:   "Song by Artist - Amazon Music"
# Deezer:         "Song - Artist - Deezer"  or  "Song by Artist - Deezer"
# Spotify:        "Song - Artist"  (bare, no suffix — checked last to avoid false positives)

_YT = re.compile(
    r"^[▶►\s]*"                       # optional playing indicator
    r"(?:\(\d+\)\s*)?"             # optional notification count e.g. "(3) "
    r"(.+?)"                           # song (and maybe artist)
    r"(?:\s*[-–]\s*(.+?))?"     # optional " - Artist" portion
    r"\s*[-–—]\s*YouTube"  # "- YouTube" marker
    r"(?:\s*[-–—]\s*.+?)?$",  # optional browser suffix: "- Opera", "- Chrome"
    re.IGNORECASE,
)
_SC = re.compile(
    r"^(.+?)\s+(?:by|[-–])\s+(.+?)\s+on SoundCloud",
    re.IGNORECASE,
)
_TIDAL = re.compile(r"^(.+?)\s*[-–]\s*(.+?)\s*\|\s*TIDAL", re.IGNORECASE)
_AM    = re.compile(r"^(.+?)\s*[-–]\s*(.+?)\s*[-–]\s*Apple Music$", re.IGNORECASE)
_AMZ   = re.compile(r"^(.+?)\s+by\s+(.+?)\s*(?:[-–]|on)\s*Amazon Music", re.IGNORECASE)
_DEZ   = re.compile(r"^(.+?)\s*(?:by\s+(.+?)\s*[-–]|[-–]\s*(.+?))\s*[-–]\s*Deezer$", re.IGNORECASE)
_SPOT  = re.compile(
    r"^(?!.*(?:Visual Studio|Code|Chrome|Firefox|Edge|Opera|Brave|Explorer|"
    r"Notepad|Word|Excel|PowerPoint|Outlook|Teams|Slack|Discord|Steam|cmd|"
    r"PowerShell|Task Manager|Settings|Control Panel|File Explorer|"
    r"\.[a-z]{2,4}\s*[-–]))(.+?)\s*[-–]\s*(.+?)$"
)


def _parse_youtube(title):
    m = _YT.match(title)
    if not m:
        return None
    part1 = m.group(1).strip()
    part2 = (m.group(2) or "").strip()
    # If we have two parts, part1=song, part2=artist
    # If only one part, the whole thing is the video title (song only)
    return {"source": "YouTube", "song": part1, "artist": part2, "raw": title}


def _parse_generic(source, m, title):
    if not m:
        return None
    groups = [g.strip() for g in m.groups() if g]
    song   = groups[0] if groups else ""
    artist = groups[1] if len(groups) > 1 else ""
    if len(song) < 2:
        return None
    return {"source": source, "song": song, "artist": artist, "raw": title}


NOW_PLAYING_PATTERNS = []  # not used directly anymore

SKIP_TITLES = {"", "Program Manager", "Windows Default Lock Screen"}


def get_process_name(hwnd):
    """Return the exe name (lowercase) for a given window handle."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        return proc.name().lower()
    except Exception:
        return ""


def get_all_window_titles():
    """Return list of (title, process_name) for all visible windows."""
    if not HAS_WIN32:
        return []
    results = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd).strip()
            if t and t not in SKIP_TITLES:
                proc = get_process_name(hwnd)
                results.append((t, proc))
    win32gui.EnumWindows(callback, None)
    return results


# Browser process names for YouTube/SoundCloud/web players
BROWSER_PROCS = {
    "chrome.exe", "msedge.exe", "firefox.exe",
    "opera.exe", "opera_gx.exe", "opera_autoupdate.exe",  # Opera & Opera GX
    "brave.exe", "vivaldi.exe", "iexplore.exe", "chromium.exe",
    "waterfox.exe", "librewolf.exe", "palemoon.exe", "basilisk.exe",
    "thorium.exe", "arc.exe",
}

# Partial process name matches (substring) for browsers that use generic names
BROWSER_PROC_SUBSTRINGS = ("opera", "browser", "chrom", "firefox", "brave", "vivaldi")
# Spotify process names
SPOTIFY_PROCS = {"spotify.exe"}


def detect_now_playing():
    windows = get_all_window_titles()
    for title, proc in windows:
        is_browser = (proc in BROWSER_PROCS or
                      any(s in proc for s in BROWSER_PROC_SUBSTRINGS))
        is_spotify = proc in SPOTIFY_PROCS

        # YouTube — must be a browser
        if is_browser:
            result = _parse_youtube(title)
            if result:
                return result

        # SoundCloud — must be a browser
        if is_browser:
            result = _parse_generic("SoundCloud", _SC.match(title), title)
            if result:
                return result

        # Tidal — browser or desktop app
        result = _parse_generic("Tidal", _TIDAL.match(title), title)
        if result:
            return result

        # Apple Music — browser
        if is_browser:
            result = _parse_generic("Apple Music", _AM.match(title), title)
            if result:
                return result

        # Amazon Music — browser
        if is_browser:
            result = _parse_generic("Amazon Music", _AMZ.match(title), title)
            if result:
                return result

        # Deezer — browser
        if is_browser:
            dm = _DEZ.match(title)
            if dm:
                song   = (dm.group(1) or "").strip()
                artist = (dm.group(2) or dm.group(3) or "").strip()
                if len(song) >= 2:
                    return {"source": "Deezer", "song": song, "artist": artist, "raw": title}

        # Spotify — ONLY match if the process is actually spotify.exe
        if is_spotify:
            result = _parse_generic("Spotify", _SPOT.match(title), title)
            if result:
                return result

    return None

# ── Data layer ────────────────────────────────────────────────────────────────

def load_history():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            return []
    return []


def save_history(history):
    DATA_FILE.write_text(json.dumps(history, indent=2))

# ── AI layer ──────────────────────────────────────────────────────────────────

def taste_summary(history):
    genre_map, artist_map, moods = {}, {}, []
    for e in history:
        if e.get("genre"):
            genre_map[e["genre"]] = genre_map.get(e["genre"], 0) + e["mins"]
        artist_map[e["artist"]] = artist_map.get(e["artist"], 0) + e["mins"]
        if e.get("mood"):
            moods.append(e["mood"].lower())
    top_genres   = sorted(genre_map.items(),  key=lambda x: -x[1])[:5]
    top_artists  = sorted(artist_map.items(), key=lambda x: -x[1])[:6]
    unique_moods = list(dict.fromkeys(moods))[:6]
    recent = [f'"{e["song"]}" by {e["artist"]} ({round(e["mins"])} min)' for e in history[:15]]
    total  = round(sum(e["mins"] for e in history))
    return "\n".join([
        f"Total listening time: {total} minutes",
        f"Top genres: {', '.join(f'{g} ({round(m)} min)' for g,m in top_genres) or 'mixed'}",
        f"Top artists: {', '.join(f'{a} ({round(m)} min)' for a,m in top_artists) or 'various'}",
        f"Preferred moods: {', '.join(unique_moods) or 'not specified'}",
        f"Recent songs: {', '.join(recent)}",
    ])


def _call_ai(prompt, api_key, max_tokens=1500):
    if not api_key:
        raise RuntimeError("No API key. Go to Settings and enter your Anthropic API key.")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=MODEL, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in msg.content if hasattr(b, "text"))
    return raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()


def get_recommendations(history, mood_filter="", count=5, api_key=""):
    profile   = taste_summary(history)
    mood_line = f"\nUser's current mood: {mood_filter}" if mood_filter else ""
    prompt = f"""You are an expert music recommendation AI.
Based on this listener's profile, recommend {count} songs they would love.

LISTENER PROFILE:
{profile}{mood_line}

Respond ONLY with a valid JSON array — no markdown, no extra text.
Each element must have exactly these keys:
  "song", "artist", "genre", "match" (e.g. "94%"),
  "why" (2-3 sentences referencing their taste),
  "tags" (array of 3 short tags)
"""
    return json.loads(_call_ai(prompt, api_key))


def get_now_playing_recommendations(now_playing, history, count=5, api_key=""):
    song   = now_playing["song"]
    artist = now_playing.get("artist", "")
    source = now_playing["source"]

    history_context = ""
    if history:
        profile = taste_summary(history)
        history_context = f"\n\nADDITIONAL CONTEXT — listener's broader taste:\n{profile}"

    seed = f'"{song}"' + (f" by {artist}" if artist else "")
    prompt = f"""You are an expert music recommendation AI.
The listener is currently playing {seed} on {source}.
Recommend {count} songs that would sound great playing next — similar vibe, energy, or style.{history_context}

Respond ONLY with a valid JSON array — no markdown, no extra text.
Each element must have exactly these keys:
  "song", "artist", "genre", "match" (e.g. "94%"),
  "why" (2-3 sentences explaining why it flows well from the current song),
  "tags" (array of 3 short tags)
"""
    return json.loads(_call_ai(prompt, api_key))

# ── Tray icon ─────────────────────────────────────────────────────────────────

def make_icon_image():
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.ellipse([2, 2, size-2, size-2], fill="#1D9E75")
    d.ellipse([18, 38, 30, 48], fill="white")
    d.rectangle([28, 20, 32, 44], fill="white")
    d.polygon([(32, 20), (46, 26), (32, 32)], fill="white")
    return img

# ── Shared reco card renderer ─────────────────────────────────────────────────

def render_reco_cards(inner, recos, wrap=600):
    for w in inner.winfo_children():
        w.destroy()
    for i, r in enumerate(recos):
        border = ACCENT if i == 0 else BORDER
        card   = tk.Frame(inner, bg=SURFACE,
                          highlightthickness=2 if i == 0 else 1,
                          highlightbackground=border)
        card.pack(fill="x", pady=(0, 10), padx=2)

        top = tk.Frame(card, bg=SURFACE)
        top.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(top, text=("✦ " if i == 0 else f"#{i+1}  ") + r["song"],
                 font=("Georgia", 13, "italic", "bold"),
                 bg=SURFACE, fg=ACCENT if i == 0 else TEXT,
                 anchor="w").pack(side="left")
        tk.Label(top, text=r.get("match", ""),
                 font=("Segoe UI", 10, "bold"),
                 bg=SURFACE, fg=ACCENT).pack(side="right")

        tk.Label(card, text=f"{r['artist']}  ·  {r.get('genre','')}",
                 font=("Segoe UI", 10), bg=SURFACE, fg=MUTED,
                 anchor="w").pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(card, text="  ".join(f"#{t}" for t in r.get("tags", [])),
                 font=("Segoe UI", 9), bg=SURFACE, fg=MUTED,
                 anchor="w").pack(fill="x", padx=14)
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=14, pady=8)
        tk.Label(card, text=r.get("why", ""),
                 font=("Segoe UI", 10), bg=SURFACE, fg=MUTED,
                 wraplength=wrap, justify="left",
                 anchor="w").pack(fill="x", padx=14, pady=(0, 14))


def make_scroll_canvas(parent):
    """Return (canvas, inner_frame) with auto-scroll setup."""
    frame  = tk.Frame(parent, bg=BG)
    frame.pack(fill="both", expand=True)
    canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
    vsb    = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    inner    = tk.Frame(canvas, bg=BG)
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def on_cfg(event):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfig(inner_id, width=canvas.winfo_width())

    inner.bind("<Configure>", on_cfg)
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(inner_id, width=e.width))
    return canvas, inner

# ── App ───────────────────────────────────────────────────────────────────────

class SoniqueApp:
    def __init__(self):
        self.history = load_history()
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.tray    = None
        self._last_np     = None
        self._polling     = False
        self._load_settings()

    def _load_settings(self):
        if SETTINGS_FILE.exists():
            try:
                s = json.loads(SETTINGS_FILE.read_text())
                if s.get("api_key"):
                    self.api_key = s["api_key"]
                if s.get("extra_browsers"):
                    for b in s["extra_browsers"]:
                        BROWSER_PROCS.add(b.lower().strip())
            except Exception:
                pass

    def _save_settings(self, extra_browsers=None):
        data = {"api_key": self.api_key}
        if extra_browsers is not None:
            data["extra_browsers"] = extra_browsers
        elif SETTINGS_FILE.exists():
            try:
                prev = json.loads(SETTINGS_FILE.read_text())
                if prev.get("extra_browsers"):
                    data["extra_browsers"] = prev["extra_browsers"]
            except Exception:
                pass
        SETTINGS_FILE.write_text(json.dumps(data))

    # ── Tray ──────────────────────────────────────────────────────────────────

    def run(self):
        self._start_polling()
        icon_img = make_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("Sonique", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Now Playing",     lambda: self._open("nowplaying")),
            pystray.MenuItem("Log a song",      lambda: self._open("add")),
            pystray.MenuItem("History",         lambda: self._open("history")),
            pystray.MenuItem("Recommendations", lambda: self._open("reco")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings",        lambda: self._open("settings")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",            self._quit),
        )
        self.tray = pystray.Icon("Sonique", icon_img, "Sonique — Music AI", menu)
        self.tray.run()

    def _open(self, tab):
        threading.Thread(target=lambda: self._show_window(tab), daemon=True).start()

    def _quit(self):
        self._polling = False
        if self.tray:
            self.tray.stop()
        os._exit(0)

    # ── Polling ───────────────────────────────────────────────────────────────

    def _start_polling(self):
        if not HAS_WIN32:
            return
        self._polling = True
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self):
        while self._polling:
            np = detect_now_playing()
            if np and np.get("song") != (self._last_np or {}).get("song"):
                self._last_np = np
                if self.tray:
                    try:
                        tip = f"{np['song']}"
                        if np.get("artist"):
                            tip += f" - {np['artist']}"
                        self.tray.title = tip
                    except Exception:
                        pass
            time.sleep(4)

    # ── Window ────────────────────────────────────────────────────────────────

    def _show_window(self, tab="nowplaying"):
        root = tk.Tk()
        root.title("Sonique")
        root.configure(bg=BG)
        root.resizable(True, True)
        try:
            root.iconbitmap(default="")
        except Exception:
            pass
        w, h = 720, 600
        x = (root.winfo_screenwidth()  - w) // 2
        y = (root.winfo_screenheight() - h) // 2
        root.geometry(f"{w}x{h}+{x}+{y}")
        self._build_ui(root, tab)
        root.mainloop()

    def _build_ui(self, root, initial_tab):
        hdr = tk.Frame(root, bg=ACCENT, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Sonique", font=("Georgia", 17, "italic"),
                 bg=ACCENT, fg="white").pack(side="left", padx=18, pady=10)
        tk.Label(hdr, text="AI Music Taste Engine", font=("Segoe UI", 10),
                 bg=ACCENT, fg="#A8E8D0").pack(side="left", pady=14)
        tk.Button(hdr, text="Exit", font=("Segoe UI", 10),
                  bg=DARK, fg="white", relief="flat",
                  padx=14, pady=6, cursor="hand2",
                  activebackground="#0A3D2E", activeforeground="white",
                  command=self._quit).pack(side="right", padx=14, pady=10)

        tab_frame = tk.Frame(root, bg=BG)
        tab_frame.pack(fill="x")

        TABS = [
            ("Now Playing", "nowplaying"),
            ("Log Song",    "add"),
            ("History",     "history"),
            ("Recs",        "reco"),
            ("Settings",    "settings"),
        ]
        tab_btns     = {}
        content_area = tk.Frame(root, bg=BG)
        content_area.pack(fill="both", expand=True)
        frames = {}

        def switch(name):
            for frm in frames.values():
                frm.pack_forget()
            frames[name].pack(fill="both", expand=True, padx=18, pady=14)
            for n, b in tab_btns.items():
                b.configure(bg=ACCENT if n == name else BG,
                            fg="white"  if n == name else MUTED)
            if name == "history" and hasattr(frames["history"], "_refresh"):
                frames["history"]._refresh()

        for label, name in TABS:
            b = tk.Button(tab_frame, text=label, font=("Segoe UI", 10),
                          bg=BG, fg=MUTED, relief="flat", bd=0,
                          padx=14, pady=8, cursor="hand2",
                          command=lambda n=name: switch(n))
            b.pack(side="left")
            tab_btns[name] = b

        tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

        frames["nowplaying"] = self._build_nowplaying(content_area)
        frames["add"]        = self._build_add(content_area)
        frames["history"]    = self._build_history(content_area)
        frames["reco"]       = self._build_reco(content_area)
        frames["settings"]   = self._build_settings(content_area)

        switch(initial_tab)

    # ── Now Playing tab ───────────────────────────────────────────────────────

    def _build_nowplaying(self, parent):
        f = tk.Frame(parent, bg=BG)

        # Detection card
        det_card = tk.Frame(f, bg=SURFACE, highlightthickness=1,
                            highlightbackground=BORDER)
        det_card.pack(fill="x", pady=(0, 12))

        det_top = tk.Frame(det_card, bg=SURFACE)
        det_top.pack(fill="x", padx=14, pady=(10, 4))

        source_var = tk.StringVar(value="Scanning for music…")
        song_var   = tk.StringVar(value="")
        artist_var = tk.StringVar(value="")

        tk.Label(det_top, textvariable=source_var,
                 font=("Segoe UI", 9), bg=SURFACE, fg=MUTED).pack(side="left")

        refresh_btn = tk.Button(det_top, text="Refresh",
                                font=("Segoe UI", 9), bg=SURFACE, fg=ACCENT,
                                relief="flat", cursor="hand2", bd=0)
        refresh_btn.pack(side="right")

        tk.Label(det_card, textvariable=song_var,
                 font=("Georgia", 15, "italic", "bold"),
                 bg=SURFACE, fg=TEXT, anchor="w").pack(fill="x", padx=14, pady=(0, 2))
        tk.Label(det_card, textvariable=artist_var,
                 font=("Segoe UI", 10), bg=SURFACE, fg=MUTED,
                 anchor="w").pack(fill="x", padx=14, pady=(0, 10))

        if not HAS_WIN32:
            tk.Label(det_card,
                     text="Auto-detection needs pywin32 + psutil:  py -m pip install pywin32 psutil",
                     font=("Segoe UI", 9), bg=SURFACE, fg=AMBER,
                     anchor="w").pack(fill="x", padx=14, pady=(0, 8))

        # Manual entry
        man_frame = tk.Frame(f, bg=BG)
        man_frame.pack(fill="x", pady=(0, 10))

        tk.Label(man_frame, text="Or enter a song manually:",
                 font=("Segoe UI", 9), bg=BG, fg=MUTED).pack(anchor="w")

        man_row = tk.Frame(man_frame, bg=BG)
        man_row.pack(fill="x", pady=(4, 0))

        man_song_var   = tk.StringVar()
        man_artist_var = tk.StringVar()

        tk.Label(man_row, text="Song", font=("Segoe UI", 9),
                 bg=BG, fg=MUTED, width=5).pack(side="left")
        tk.Entry(man_row, textvariable=man_song_var, font=("Segoe UI", 10),
                 bg=SURFACE, fg=TEXT, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT, width=24
                 ).pack(side="left", ipady=5, padx=(2, 10))
        tk.Label(man_row, text="Artist", font=("Segoe UI", 9),
                 bg=BG, fg=MUTED).pack(side="left")
        tk.Entry(man_row, textvariable=man_artist_var, font=("Segoe UI", 10),
                 bg=SURFACE, fg=TEXT, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT, width=22
                 ).pack(side="left", ipady=5, padx=(4, 0))

        # Controls row
        ctrl = tk.Frame(f, bg=BG)
        ctrl.pack(fill="x", pady=(0, 10))

        count_var = tk.StringVar(value="5")
        tk.Label(ctrl, text="Count:", font=("Segoe UI", 10),
                 bg=BG, fg=MUTED).pack(side="left")
        ttk.Spinbox(ctrl, from_=1, to=10, textvariable=count_var,
                    width=4, font=("Segoe UI", 10)).pack(side="left", padx=(4, 14))

        get_btn = tk.Button(ctrl,
                            text="Get recommendations for this song",
                            font=("Segoe UI", 10, "bold"),
                            bg=ACCENT, fg="white", relief="flat",
                            padx=14, pady=6, cursor="hand2",
                            activebackground=DARK, activeforeground="white")
        get_btn.pack(side="left")

        _, inner = make_scroll_canvas(f)

        status_var = tk.StringVar()
        tk.Label(f, textvariable=status_var, font=("Segoe UI", 10),
                 bg=BG, fg=MUTED, wraplength=660).pack(anchor="w", pady=(4, 0))

        current_np = {"data": None}

        def refresh_np():
            np = self._last_np if HAS_WIN32 else None
            if np:
                source_var.set(f"Now playing via {np['source']}")
                song_var.set(np["song"])
                artist_var.set(np.get("artist", ""))
                current_np["data"] = np
            else:
                msg = ("Nothing detected — play a song on Spotify, YouTube, or SoundCloud"
                       if HAS_WIN32 else "Install pywin32 for auto-detection")
                source_var.set(msg)
                song_var.set("")
                artist_var.set("")
                current_np["data"] = None

        refresh_btn.configure(command=refresh_np)

        def _auto():
            refresh_np()
            f.after(4000, _auto)
        f.after(300, _auto)

        def fetch():
            man_song = man_song_var.get().strip()
            if man_song:
                np = {"source": "manual entry",
                      "song": man_song,
                      "artist": man_artist_var.get().strip()}
            elif current_np["data"]:
                np = current_np["data"]
            else:
                status_var.set("Nothing is playing and no song was entered manually.")
                return

            seed = f'"{np["song"]}"'
            if np.get("artist"):
                seed += f' by {np["artist"]}'

            get_btn.configure(state="disabled", text="Fetching…")
            status_var.set(f"Finding what plays well after {seed}…")
            for w in inner.winfo_children():
                w.destroy()

            def worker():
                try:
                    recos = get_now_playing_recommendations(
                        np, self.history, int(count_var.get() or 5), self.api_key
                    )
                    inner.after(0, lambda: render_reco_cards(inner, recos, wrap=640))
                    inner.after(0, lambda: status_var.set(
                        f"Showing {len(recos)} songs that go well after {seed}"))
                except Exception as e:
                    inner.after(0, lambda: status_var.set(f"Error: {e}"))
                finally:
                    inner.after(0, lambda: get_btn.configure(
                        state="normal",
                        text="Get recommendations for this song"))

            threading.Thread(target=worker, daemon=True).start()

        get_btn.configure(command=fetch)
        return f

    # ── Add tab ───────────────────────────────────────────────────────────────

    def _build_add(self, parent):
        f = tk.Frame(parent, bg=BG)

        song_var   = tk.StringVar()
        artist_var = tk.StringVar()
        genre_var  = tk.StringVar()
        mins_var   = tk.StringVar()
        mood_var   = tk.StringVar()

        def lbl(c, t):
            tk.Label(c, text=t, font=("Segoe UI", 9), fg=MUTED, bg=BG).pack(anchor="w")

        def ent(c, v):
            tk.Entry(c, textvariable=v, font=("Segoe UI", 11),
                     bg=SURFACE, fg=TEXT, relief="flat",
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT).pack(fill="x", ipady=6, pady=(2, 10))

        r1 = tk.Frame(f, bg=BG); r1.pack(fill="x")
        L  = tk.Frame(r1, bg=BG); L.pack(side="left", fill="x", expand=True, padx=(0, 8))
        R  = tk.Frame(r1, bg=BG); R.pack(side="left", fill="x", expand=True)
        lbl(L, "Song title"); ent(L, song_var)
        lbl(R, "Artist");     ent(R, artist_var)

        r2 = tk.Frame(f, bg=BG); r2.pack(fill="x")
        GL = tk.Frame(r2, bg=BG); GL.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ML = tk.Frame(r2, bg=BG); ML.pack(side="left", fill="x", expand=True)
        lbl(GL, "Genre")
        ttk.Combobox(GL, textvariable=genre_var, values=GENRES,
                     state="readonly", font=("Segoe UI", 11)
                     ).pack(fill="x", ipady=4, pady=(2, 10))
        lbl(ML, "Minutes listened"); ent(ML, mins_var)
        lbl(f, "Mood / vibe (optional)"); ent(f, mood_var)

        status_var = tk.StringVar()
        status_lbl = tk.Label(f, textvariable=status_var, font=("Segoe UI", 10),
                              bg=BG, fg=ACCENT)
        status_lbl.pack(anchor="w", pady=(0, 8))

        def log_song():
            song   = song_var.get().strip()
            artist = artist_var.get().strip()
            if not song or not artist:
                status_var.set("Please enter a song title and artist.")
                status_lbl.configure(fg=AMBER); return
            try:
                mins = float(mins_var.get()); assert mins > 0
            except Exception:
                status_var.set("Enter a valid number of minutes.")
                status_lbl.configure(fg=AMBER); return
            self.history.insert(0, {
                "id": int(time.time()*1000), "song": song, "artist": artist,
                "genre": genre_var.get().strip(), "mins": mins,
                "mood": mood_var.get().strip(), "ts": datetime.now().isoformat(),
            })
            save_history(self.history)
            for v in (song_var, artist_var, genre_var, mins_var, mood_var):
                v.set("")
            status_var.set(f'Logged {round(mins)} min of "{song}" by {artist}')
            status_lbl.configure(fg=ACCENT)

        tk.Button(f, text="Log listening session",
                  font=("Segoe UI", 11, "bold"),
                  bg=ACCENT, fg="white", relief="flat",
                  padx=20, pady=9, cursor="hand2",
                  activebackground=DARK, activeforeground="white",
                  command=log_song).pack(anchor="w")
        return f

    # ── History tab ───────────────────────────────────────────────────────────

    def _build_history(self, parent):
        f = tk.Frame(parent, bg=BG)

        stats_frame = tk.Frame(f, bg=BG)
        stats_frame.pack(fill="x", pady=(0, 12))

        self._stat_tracks = tk.StringVar()
        self._stat_mins   = tk.StringVar()
        self._stat_genre  = tk.StringVar()

        for var, label in [
            (self._stat_tracks, "songs logged"),
            (self._stat_mins,   "minutes total"),
            (self._stat_genre,  "top genre"),
        ]:
            card = tk.Frame(stats_frame, bg=SURFACE,
                            highlightthickness=1, highlightbackground=BORDER)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(card, textvariable=var, font=("Segoe UI", 20, "bold"),
                     bg=SURFACE, fg=TEXT).pack(padx=14, pady=(10, 2))
            tk.Label(card, text=label, font=("Segoe UI", 9),
                     bg=SURFACE, fg=MUTED).pack(padx=14, pady=(0, 10))

        tbl = tk.Frame(f, bg=BG)
        tbl.pack(fill="both", expand=True)

        cols = ("Song", "Artist", "Genre", "Mood", "Min", "Date")
        tree = ttk.Treeview(tbl, columns=cols, show="headings", height=10)
        for col, w in zip(cols, [180, 150, 120, 100, 50, 80]):
            tree.heading(col, text=col)
            tree.column(col, width=w, anchor="w")
        sb = ttk.Scrollbar(tbl, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))

        status_var = tk.StringVar()
        tk.Label(btn_row, textvariable=status_var, font=("Segoe UI", 10),
                 bg=BG, fg=RED).pack(side="right", padx=4)

        def delete_selected():
            sel = tree.selection()
            if not sel:
                status_var.set("Select a row first."); return
            idx     = tree.index(sel[0])
            removed = self.history.pop(idx)
            save_history(self.history)
            status_var.set(f'Deleted "{removed["song"]}"')
            refresh()

        tk.Button(btn_row, text="Delete selected entry",
                  font=("Segoe UI", 10), bg=SURFACE, fg=RED, relief="flat",
                  highlightthickness=1, highlightbackground="#F09595",
                  padx=12, pady=6, cursor="hand2",
                  activebackground=RED_BG,
                  command=delete_selected).pack(side="left")

        def refresh():
            for row in tree.get_children():
                tree.delete(row)
            total     = round(sum(e["mins"] for e in self.history))
            genre_map = {}
            for e in self.history:
                if e.get("genre"):
                    genre_map[e["genre"]] = genre_map.get(e["genre"], 0) + e["mins"]
            top = max(genre_map, key=genre_map.get) if genre_map else "—"
            self._stat_tracks.set(str(len(self.history)))
            self._stat_mins.set(str(total))
            self._stat_genre.set(top.split("/")[0].strip() if "/" in top else top)
            for e in self.history:
                tree.insert("", "end", values=(
                    e["song"], e["artist"],
                    e.get("genre", ""), e.get("mood", ""),
                    round(e["mins"]),
                    datetime.fromisoformat(e["ts"]).strftime("%b %d"),
                ))

        refresh()
        f._refresh = refresh
        return f

    # ── Recs tab (history-based) ──────────────────────────────────────────────

    def _build_reco(self, parent):
        f = tk.Frame(parent, bg=BG)

        ctrl = tk.Frame(f, bg=BG)
        ctrl.pack(fill="x", pady=(0, 12))

        mood_var  = tk.StringVar()
        count_var = tk.StringVar(value="5")

        tk.Label(ctrl, text="Mood filter:", font=("Segoe UI", 10),
                 bg=BG, fg=MUTED).pack(side="left")
        tk.Entry(ctrl, textvariable=mood_var, width=16,
                 font=("Segoe UI", 10), bg=SURFACE, fg=TEXT,
                 relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT
                 ).pack(side="left", ipady=5, padx=(4, 16))
        tk.Label(ctrl, text="Count:", font=("Segoe UI", 10),
                 bg=BG, fg=MUTED).pack(side="left")
        ttk.Spinbox(ctrl, from_=1, to=10, textvariable=count_var,
                    width=4, font=("Segoe UI", 10)).pack(side="left", padx=(4, 14))
        get_btn = tk.Button(ctrl, text="Get recommendations",
                            font=("Segoe UI", 10, "bold"),
                            bg=ACCENT, fg="white", relief="flat",
                            padx=14, pady=6, cursor="hand2",
                            activebackground=DARK, activeforeground="white")
        get_btn.pack(side="left")

        _, inner = make_scroll_canvas(f)

        status_var = tk.StringVar()
        tk.Label(f, textvariable=status_var, font=("Segoe UI", 10),
                 bg=BG, fg=MUTED, wraplength=660).pack(anchor="w", pady=(6, 0))

        def fetch():
            if not self.history:
                status_var.set("Log some songs first so the AI can learn your taste.")
                return
            get_btn.configure(state="disabled", text="Fetching…")
            status_var.set("Analyzing your taste…")
            for w in inner.winfo_children():
                w.destroy()

            def worker():
                try:
                    recos = get_recommendations(
                        self.history, mood_var.get().strip(),
                        int(count_var.get() or 5), self.api_key,
                    )
                    inner.after(0, lambda: render_reco_cards(inner, recos, wrap=640))
                    inner.after(0, lambda: status_var.set(
                        f"Showing {len(recos)} recommendations based on your history"))
                except Exception as e:
                    inner.after(0, lambda: status_var.set(f"Error: {e}"))
                finally:
                    inner.after(0, lambda: get_btn.configure(
                        state="normal", text="Get recommendations"))

            threading.Thread(target=worker, daemon=True).start()

        get_btn.configure(command=fetch)
        return f

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _debug_processes(self):
        """Print all visible window titles and their process names to help diagnose detection."""
        try:
            import win32gui, win32process, psutil
            results = []
            def cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    t = win32gui.GetWindowText(hwnd).strip()
                    if t:
                        try:
                            _, pid = win32process.GetWindowThreadProcessId(hwnd)
                            proc = psutil.Process(pid).name().lower()
                        except Exception:
                            proc = "unknown"
                        results.append((proc, t))
            win32gui.EnumWindows(cb, None)
            lines = [f"{p:<30} {t}" for p, t in sorted(results)]
            msg = "\n".join(lines[:40])
        except Exception as e:
            msg = str(e)

        win = tk.Toplevel()
        win.title("Process Debug")
        win.geometry("700x420")
        win.configure(bg=BG)
        tk.Label(win, text="Visible windows and their process names",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT).pack(anchor="w", padx=14, pady=(12,4))
        tk.Label(win, text="Find your Opera/browser row and tell Sonique its process name.",
                 font=("Segoe UI", 9), bg=BG, fg=MUTED).pack(anchor="w", padx=14, pady=(0,8))
        txt = tk.Text(win, font=("Courier New", 9), bg=SURFACE, fg=TEXT,
                      relief="flat", wrap="none")
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True, padx=(14,0), pady=(0,14))
        sb.pack(side="right", fill="y", pady=(0,14), padx=(0,14))
        txt.insert("end", msg)
        txt.configure(state="disabled")

    def _build_settings(self, parent):
        f = tk.Frame(parent, bg=BG)

        tk.Label(f, text="Anthropic API key", font=("Segoe UI", 10),
                 bg=BG, fg=MUTED).pack(anchor="w")
        key_var = tk.StringVar(value=self.api_key)
        key_entry = tk.Entry(f, textvariable=key_var, font=("Segoe UI", 11),
                             bg=SURFACE, fg=TEXT, show="*", width=52,
                             relief="flat", highlightthickness=1,
                             highlightbackground=BORDER, highlightcolor=ACCENT)
        key_entry.pack(anchor="w", ipady=6, pady=(2, 4), fill="x")

        def toggle_show():
            key_entry.configure(show="" if key_entry.cget("show") == "*" else "*")
            show_btn.configure(text="Hide" if key_entry.cget("show") == "" else "Show")

        show_btn = tk.Button(f, text="Show", font=("Segoe UI", 9),
                             bg=BG, fg=MUTED, relief="flat", cursor="hand2",
                             command=toggle_show)
        show_btn.pack(anchor="w", pady=(0, 12))

        status_var = tk.StringVar()
        tk.Label(f, textvariable=status_var, font=("Segoe UI", 10),
                 bg=BG, fg=ACCENT).pack(anchor="w", pady=(0, 8))

        def save_key():
            self.api_key = key_var.get().strip()
            self._save_settings()
            status_var.set("API key saved")

        tk.Button(f, text="Save API key",
                  font=("Segoe UI", 11, "bold"),
                  bg=ACCENT, fg="white", relief="flat",
                  padx=16, pady=8, cursor="hand2",
                  activebackground=DARK, activeforeground="white",
                  command=save_key).pack(anchor="w")

        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=20)

        tk.Label(f, text="Now Playing — supported sources",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(f,
                 text="Spotify desktop · YouTube · SoundCloud · Tidal · Apple Music · Amazon Music · Deezer",
                 font=("Segoe UI", 10), bg=BG, fg=MUTED,
                 wraplength=580, justify="left").pack(anchor="w", pady=(2, 10))

        win32_ok = "pywin32 installed — auto-detection active" if HAS_WIN32 \
            else "pywin32/psutil not found — run:  py -m pip install pywin32 psutil"
        tk.Label(f, text=win32_ok, font=("Segoe UI", 10),
                 bg=BG, fg=ACCENT if HAS_WIN32 else AMBER).pack(anchor="w", pady=(0, 14))

        tk.Label(f, text="Get your API key at  console.anthropic.com",
                 font=("Segoe UI", 10), bg=BG, fg=MUTED).pack(anchor="w")
        tk.Label(f, text=f"History file:  {DATA_FILE}",
                 font=("Segoe UI", 10), bg=BG, fg=MUTED).pack(anchor="w", pady=(4, 0))

        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=16)
        tk.Label(f, text="Detection not working?",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(f, text="Add your browser's process name (e.g. opera.exe) — find it using the debug button below.",
                 font=("Segoe UI", 9), bg=BG, fg=MUTED, wraplength=560, justify="left").pack(anchor="w", pady=(2, 6))

        extra_row = tk.Frame(f, bg=BG)
        extra_row.pack(fill="x", pady=(0, 8))
        extra_var = tk.StringVar()
        # Pre-fill with existing custom browsers from settings
        try:
            s = json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {}
            extra_var.set(", ".join(s.get("extra_browsers", [])))
        except Exception:
            pass
        tk.Label(extra_row, text="Extra browsers:", font=("Segoe UI", 9),
                 bg=BG, fg=MUTED).pack(side="left")
        tk.Entry(extra_row, textvariable=extra_var, font=("Segoe UI", 10),
                 bg=SURFACE, fg=TEXT, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT, width=30).pack(side="left", ipady=5, padx=(6, 8))

        extra_status = tk.StringVar()
        tk.Label(f, textvariable=extra_status, font=("Segoe UI", 9),
                 bg=BG, fg=ACCENT).pack(anchor="w", pady=(0, 6))

        def save_extra():
            raw = extra_var.get().strip()
            procs = [p.strip().lower() for p in raw.split(",") if p.strip()]
            for p in procs:
                BROWSER_PROCS.add(p)
            self._save_settings(extra_browsers=procs)
            extra_status.set(f"Saved — {len(procs)} custom browser(s) added")

        tk.Button(f, text="Save extra browsers",
                  font=("Segoe UI", 10), bg=SURFACE, fg=ACCENT,
                  relief="flat", highlightthickness=1, highlightbackground=BORDER,
                  padx=10, pady=5, cursor="hand2",
                  command=save_extra).pack(anchor="w", pady=(0, 10))

        tk.Button(f, text="Show process debug info",
                  font=("Segoe UI", 10), bg=SURFACE, fg=MUTED,
                  relief="flat", highlightthickness=1, highlightbackground=BORDER,
                  padx=12, pady=6, cursor="hand2",
                  command=self._debug_processes).pack(anchor="w")
        return f

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = SoniqueApp()
    if not app.api_key:
        threading.Thread(target=lambda: app._show_window("settings"), daemon=True).start()
        time.sleep(0.3)
    app.run()