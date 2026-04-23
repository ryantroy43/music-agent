import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import anthropic
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, FloatPrompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box
    from rich.text import Text
    from rich.columns import Columns
    from rich.align import Align
except ImportError:
    print("Missing dependencies. Run:  pip install anthropic rich")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

DATA_FILE = Path.home() / ".sonique_history.json"
MODEL     = "claude-opus-4-5"

GENRES = [
    "Pop", "Hip-Hop / Rap", "R&B / Soul", "Rock", "Indie / Alternative",
    "Electronic / EDM", "Jazz", "Classical", "Country", "Metal",
    "Folk / Acoustic", "Latin", "K-Pop", "Afrobeats", "Reggae", "Other",
]

console = Console()

# ── Data layer ────────────────────────────────────────────────────────────────

def load_history() -> list[dict]:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except json.JSONDecodeError:
            return []
    return []


def save_history(history: list[dict]) -> None:
    DATA_FILE.write_text(json.dumps(history, indent=2))


def add_entry(history: list[dict], entry: dict) -> None:
    history.insert(0, entry)
    save_history(history)


def delete_entry(history: list[dict], idx: int) -> dict:
    removed = history.pop(idx)
    save_history(history)
    return removed

# ── Stats helpers ─────────────────────────────────────────────────────────────

def top_genre(history: list[dict]) -> str:
    genre_mins: dict[str, float] = {}
    for e in history:
        if e.get("genre"):
            genre_mins[e["genre"]] = genre_mins.get(e["genre"], 0) + e["mins"]
    if not genre_mins:
        return "—"
    return max(genre_mins, key=genre_mins.__getitem__)


def total_mins(history: list[dict]) -> float:
    return sum(e["mins"] for e in history)


def taste_summary(history: list[dict]) -> str:
    """Build a compact taste profile for the AI prompt."""
    genre_map: dict[str, float] = {}
    artist_map: dict[str, float] = {}
    moods: list[str] = []

    for e in history:
        if e.get("genre"):
            genre_map[e["genre"]] = genre_map.get(e["genre"], 0) + e["mins"]
        artist_map[e["artist"]] = artist_map.get(e["artist"], 0) + e["mins"]
        if e.get("mood"):
            moods.append(e["mood"].lower())

    top_genres  = sorted(genre_map.items(),  key=lambda x: -x[1])[:5]
    top_artists = sorted(artist_map.items(), key=lambda x: -x[1])[:6]
    unique_moods = list(dict.fromkeys(moods))[:6]
    recent_songs = [
        f'"{e["song"]}" by {e["artist"]} ({round(e["mins"])} min)'
        for e in history[:15]
    ]

    lines = [
        f"Total listening time: {round(total_mins(history))} minutes",
        f"Top genres: {', '.join(f'{g} ({round(m)} min)' for g, m in top_genres) or 'mixed'}",
        f"Top artists: {', '.join(f'{a} ({round(m)} min)' for a, m in top_artists) or 'various'}",
        f"Preferred moods/vibes: {', '.join(unique_moods) or 'not specified'}",
        f"Recent songs: {', '.join(recent_songs)}",
    ]
    return "\n".join(lines)

# ── AI layer ──────────────────────────────────────────────────────────────────

def get_recommendations(
    history: list[dict],
    mood_filter: str = "",
    count: int = 5,
) -> list[dict]:
    """Call the Anthropic API and return a list of recommendation dicts."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set.\n"
            "Export it: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    client = anthropic.Anthropic(api_key=api_key)
    profile = taste_summary(history)
    mood_line = f"\nUser's current mood/context: {mood_filter}" if mood_filter else ""

    prompt = f"""You are an expert music recommendation AI.
Based on this listener's detailed profile, recommend {count} songs they would genuinely love.

LISTENER PROFILE:
{profile}{mood_line}

Respond ONLY with a valid JSON array — no markdown fences, no extra text.
Each element must have exactly these keys:
  "song"   – song title
  "artist" – artist name
  "genre"  – genre
  "match"  – match percentage, e.g. "94%"
  "why"    – 2-3 sentences explaining why this fits their taste, referencing specific patterns
  "tags"   – array of 3-4 short descriptive tags
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = "".join(
        block.text for block in message.content if hasattr(block, "text")
    )
    # Strip accidental markdown fences
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(clean)

# ── Display helpers ───────────────────────────────────────────────────────────

def print_header() -> None:
    console.print()
    title = Text("♪  Sonique", style="bold green")
    sub   = Text("  AI Music Taste Engine", style="dim")
    console.print(Align.center(title + sub))
    console.print(Align.center(Text("─" * 38, style="dim green")))
    console.print()


def print_history(history: list[dict]) -> None:
    if not history:
        console.print("[dim]No sessions logged yet.[/dim]")
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold green")
    table.add_column("#",       style="dim",       width=4,  justify="right")
    table.add_column("Song",    style="bold",      min_width=20)
    table.add_column("Artist",                     min_width=16)
    table.add_column("Genre",   style="dim",       min_width=14)
    table.add_column("Mood",    style="italic dim", min_width=10)
    table.add_column("Min",     justify="right",   width=6)
    table.add_column("Date",    style="dim",       width=10)

    for i, e in enumerate(history):
        date_str = datetime.fromisoformat(e["ts"]).strftime("%b %d")
        table.add_row(
            str(i + 1),
            e["song"],
            e["artist"],
            e.get("genre", ""),
            e.get("mood", ""),
            str(round(e["mins"])),
            date_str,
        )

    console.print(table)

    # Stats bar
    t_mins  = total_mins(history)
    t_genre = top_genre(history)
    stats_text = (
        f"[bold]{len(history)}[/bold] songs  ·  "
        f"[bold]{round(t_mins)}[/bold] minutes  ·  "
        f"Top genre: [bold green]{t_genre}[/bold green]"
    )
    console.print(f"  {stats_text}\n")


def print_recommendations(recos: list[dict]) -> None:
    for i, r in enumerate(recos):
        is_top = (i == 0)
        border_style = "green" if is_top else "dim"
        tags_str = "  ".join(f"[dim]#{t}[/dim]" for t in r.get("tags", []))
        match_str = f"[bold green]{r.get('match', '')}[/bold green]"

        content = Text()
        content.append(f"{r['song']}", style="bold")
        content.append(f"  by {r['artist']}", style="")
        content.append(f"  ·  {r.get('genre', '')}\n", style="dim")
        content.append(f"Match: {r.get('match', '')}   ", style="")
        content.append(tags_str + "\n\n")
        content.append(r.get("why", ""), style="dim italic")

        title_str = "✦ Top Pick" if is_top else f"#{i + 1}"
        console.print(
            Panel(content, title=title_str, border_style=border_style, padding=(0, 1))
        )

# ── Menu actions ──────────────────────────────────────────────────────────────

def menu_add(history: list[dict]) -> None:
    console.print("\n[bold]Log a listening session[/bold]")
    console.print("[dim]Press Ctrl+C to cancel.[/dim]\n")
    try:
        song   = Prompt.ask("Song title").strip()
        artist = Prompt.ask("Artist").strip()

        console.print("\nGenres:")
        for i, g in enumerate(GENRES, 1):
            console.print(f"  [dim]{i:2}.[/dim] {g}")
        genre_idx = Prompt.ask("\nGenre number [dim](or leave blank)[/dim]", default="").strip()
        genre = GENRES[int(genre_idx) - 1] if genre_idx.isdigit() and 1 <= int(genre_idx) <= len(GENRES) else ""

        mins  = float(Prompt.ask("Minutes listened", default="3"))
        mood  = Prompt.ask("Mood / vibe [dim](optional)[/dim]", default="").strip()

        entry = {
            "id":     int(time.time() * 1000),
            "song":   song,
            "artist": artist,
            "genre":  genre,
            "mins":   mins,
            "mood":   mood,
            "ts":     datetime.now().isoformat(),
        }
        add_entry(history, entry)
        console.print(f'\n[green]✓[/green] Logged [bold]{round(mins)} min[/bold] of \u201c[bold]{song}[/bold]\u201d by {artist}')
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")


def menu_delete(history: list[dict]) -> None:
    if not history:
        console.print("[dim]Nothing to delete.[/dim]")
        return
    print_history(history)
    idx_str = Prompt.ask("Entry # to delete [dim](or blank to cancel)[/dim]", default="").strip()
    if idx_str.isdigit():
        idx = int(idx_str) - 1
        if 0 <= idx < len(history):
            removed = delete_entry(history, idx)
            console.print(f"[green]\u2713[/green] Removed \u201c{removed['song']}\u201d")
        else:
            console.print("[red]Invalid number.[/red]")


def menu_recommend(history: list[dict]) -> None:
    if not history:
        console.print("[yellow]Log some songs first so the AI can learn your taste.[/yellow]")
        return

    mood_filter = Prompt.ask(
        "\nFilter by mood/vibe [dim](optional, e.g. chill / hype / focus)[/dim]",
        default=""
    ).strip()

    count_str = Prompt.ask("How many recommendations?", default="5")
    count = int(count_str) if count_str.isdigit() else 5
    count = max(1, min(count, 10))

    console.print()
    try:
        with Progress(
            SpinnerColumn(style="green"),
            TextColumn("[dim]{task.description}[/dim]"),
            transient=True,
        ) as progress:
            task = progress.add_task("Analyzing your taste…", total=None)
            messages = [
                "Analyzing your taste…",
                "Finding patterns in your listening…",
                "Building your sound profile…",
                "Consulting the music oracle…",
            ]
            start = time.time()
            # Run in thread to keep spinner alive
            import threading
            result: dict = {"recos": None, "error": None}

            def fetch():
                try:
                    result["recos"] = get_recommendations(history, mood_filter, count)
                except Exception as exc:
                    result["error"] = exc

            t = threading.Thread(target=fetch, daemon=True)
            t.start()
            mi = 0
            while t.is_alive():
                elapsed = time.time() - start
                progress.update(task, description=messages[int(elapsed / 2) % len(messages)])
                time.sleep(0.1)
            t.join()

        if result["error"]:
            raise result["error"]

        recos = result["recos"]
        console.print(f"[bold green]✦ {len(recos)} recommendations based on your taste[/bold green]\n")
        print_recommendations(recos)

    except RuntimeError as e:
        console.print(f"\n[red]Error:[/red] {e}")
    except json.JSONDecodeError:
        console.print("\n[red]Error:[/red] The AI returned an unexpected response. Try again.")
    except Exception as e:
        console.print(f"\n[red]Unexpected error:[/red] {e}")

# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    history = load_history()

    while True:
        print_header()
        console.print("  [bold]1.[/bold]  Add listening session")
        console.print("  [bold]2.[/bold]  View history")
        console.print("  [bold]3.[/bold]  Get AI recommendations")
        console.print("  [bold]4.[/bold]  Delete an entry")
        console.print("  [bold]Q.[/bold]  Quit\n")

        choice = Prompt.ask("Choice", default="").strip().lower()

        if choice == "1":
            menu_add(history)
        elif choice == "2":
            console.print()
            print_history(history)
            Prompt.ask("[dim]Press Enter to continue[/dim]", default="")
        elif choice == "3":
            menu_recommend(history)
            Prompt.ask("\n[dim]Press Enter to continue[/dim]", default="")
        elif choice == "4":
            menu_delete(history)
        elif choice in ("q", "quit", "exit"):
            console.print("\n[dim]Goodbye! Keep listening. 🎵[/dim]\n")
            break
        else:
            console.print("[dim]Please enter 1, 2, 3, 4, or Q.[/dim]")

        console.print()


if __name__ == "__main__":
    main()