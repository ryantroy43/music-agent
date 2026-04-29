"""
SONIQUE PRO DATABASE
Advanced local recommendation engine for Sonique
"""

import sqlite3
import math
import random
from pathlib import Path

DB_FILE = Path.home() / ".sonique_pro.db"


class SoniqueProDB:
    def __init__(self):
        # check_same_thread=False allows Tkinter background threads to query the DB
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        
        # Auto-seed the database if it's empty on first launch
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM songs")
        if c.fetchone()[0] == 0:
            self.seed_demo()

    
    # DATABASE
    
    def create_tables(self):
        c = self.conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS songs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song TEXT,
            artist TEXT,
            genre TEXT,
            mood TEXT,
            bpm INTEGER,
            energy INTEGER,
            year INTEGER,
            popularity INTEGER
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song TEXT,
            artist TEXT,
            mins REAL,
            ts TEXT
        )
        """)

        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_song
        ON songs(song,artist)
        """)

        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_genre
        ON songs(genre)
        """)

        self.conn.commit()

    
    # ADD SONG
    
    def add_song(self, song, artist, genre, mood, bpm, energy, year, popularity):
        self.conn.execute("""
        INSERT INTO songs(
            song,artist,genre,mood,bpm,energy,year,popularity
        )
        VALUES(?,?,?,?,?,?,?,?)
        """, (
            song, artist, genre, mood,
            bpm, energy, year, popularity
        ))
        self.conn.commit()

    
    # DEMO DATA aka (PLAYLIST)
   
    def seed_demo(self):
        demo = [
            # Playlist of 45 iconic tracks across genres and eras with metadata for testing
            ("Blinding Lights", "The Weeknd", "Pop", "night", 171, 9, 2020, 98),
            ("Starboy", "The Weeknd", "Pop", "dark", 186, 8, 2016, 95),
            ("Save Your Tears", "The Weeknd", "Pop", "sad", 118, 7, 2021, 95),
            ("Levitating", "Dua Lipa", "Pop", "party", 103, 8, 2020, 96),
            ("Don't Start Now", "Dua Lipa", "Pop", "dance", 124, 9, 2019, 94),
            ("As It Was", "Harry Styles", "Pop", "nostalgic", 174, 6, 2022, 95),
            ("Stay", "Kid Laroi", "Pop", "youthful", 170, 8, 2021, 93),
            ("Heat Waves", "Glass Animals", "Indie", "dreamy", 81, 5, 2021, 93),
            ("Sunflower", "Post Malone", "HipHop", "happy", 90, 6, 2019, 96),
            ("Passionfruit", "Drake", "R&B", "late night", 112, 5, 2017, 92),
            ("One Dance", "Drake", "HipHop", "summer", 104, 7, 2016, 96),

            ("Bad Habit", "Steve Lacy", "R&B", "cool", 84, 5, 2022, 92),
            ("Redbone", "Childish Gambino", "Soul", "funky", 160, 6, 2016, 91),
            ("Midnight City", "M83", "Electronic", "night", 105, 7, 2011, 90),
            ("Electric Feel", "MGMT", "Indie", "party", 98, 7, 2007, 90),
            ("Cruel Summer", "Taylor Swift", "Pop", "upbeat", 170, 8, 2019, 97),
            ("Anti-Hero", "Taylor Swift", "Pop", "introspective", 97, 6, 2022, 96),
            ("Die For You", "The Weeknd", "Pop", "romantic", 133, 6, 2016, 95),
            ("Watermelon Sugar", "Harry Styles", "Pop", "summer", 95, 8, 2019, 94),
            ("About Damn Time", "Lizzo", "Pop", "party", 109, 8, 2022, 92),

            ("Peaches", "Justin Bieber", "Pop", "chill", 90, 7, 2021, 91),
            ("Bad Guy", "Billie Eilish", "Pop", "dark", 135, 6, 2019, 95),
            ("Happier Than Ever", "Billie Eilish", "Pop", "angry", 81, 5, 2021, 93),
            ("Good Days", "SZA", "R&B", "chill", 121, 5, 2020, 93),
            ("Kill Bill", "SZA", "R&B", "angry", 89, 7, 2022, 95),
            ("Pink + White", "Frank Ocean", "R&B", "dreamy", 160, 5, 2016, 92),
            ("Nights", "Frank Ocean", "R&B", "late night", 90, 6, 2016, 93),
            ("Creepin'", "Metro Boomin", "HipHop", "dark", 98, 6, 2022, 94),
            ("rockstar", "Post Malone", "HipHop", "dark", 90, 6, 2017, 95),

            ("Circles", "Post Malone", "Pop", "nostalgic", 120, 7, 2019, 96),
            ("Lucid Dreams", "Juice WRLD", "HipHop", "sad", 84, 6, 2018, 94),
            ("Industry Baby", "Lil Nas X", "HipHop", "energetic", 150, 9, 2021, 94),
            ("Montero", "Lil Nas X", "Pop", "dark", 136, 7, 2021, 93),
            ("The Less I Know The Better", "Tame Impala", "Indie", "funky", 117, 7, 2015, 96),
            ("Do I Wanna Know?", "Arctic Monkeys", "Rock", "cool", 85, 6, 2013, 94),
            ("Take Me To Church", "Hozier", "Indie", "dark", 129, 6, 2013, 91),
            ("Somebody That I Used To Know", "Gotye", "Indie", "sad", 129, 5, 2011, 90),
            ("Smells Like Teen Spirit", "Nirvana", "Rock", "energetic", 117, 9, 1991, 92),

            ("Mr. Brightside", "The Killers", "Rock", "party", 148, 9, 2003, 95),
            ("Dreams", "Fleetwood Mac", "Rock", "chill", 120, 5, 1977, 92),
            ("Bohemian Rhapsody", "Queen", "Rock", "epic", 72, 6, 1975, 96),
            ("Get Lucky", "Daft Punk", "Electronic", "dance", 116, 8, 2013, 93),
            ("Closer", "The Chainsmokers", "Electronic", "party", 95, 7, 2016, 94),
            ("Wake Me Up", "Avicii", "Electronic", "upbeat", 124, 9, 2013, 95),
            ("Titanium", "David Guetta", "Electronic", "energetic", 126, 9, 2011, 91),
        ]

        for d in demo:
            self.add_song(*d)

    
    # HELPERS
   
    def clamp(self, n, low, high):
        return max(low, min(high, n))

    def score_distance(self, a, b, max_diff):
        diff = abs(a - b)
        return max(0, 1 - (diff / max_diff))

    
    # FIND TRACK
    
    def get_track(self, song, artist=""):
        c = self.conn.cursor()

        if artist:
            c.execute("""
            SELECT * FROM songs
            WHERE lower(song)=lower(?)
            AND lower(artist)=lower(?)
            LIMIT 1
            """, (song, artist))
        else:
            c.execute("""
            SELECT * FROM songs
            WHERE lower(song)=lower(?)
            LIMIT 1
            """, (song,))

        return c.fetchone()

    
    # MAIN RECOMMENDER (Now Playing)
   
    def recommend_next(self, song, artist="", limit=5):
        seed = self.get_track(song, artist)

        if not seed:
            return self.popular(limit)

        c = self.conn.cursor()
        c.execute("SELECT * FROM songs")
        rows = c.fetchall()

        scored = []

        for row in rows:
            if row["song"] == seed["song"] and row["artist"] == seed["artist"]:
                continue

            score = 0

            # same genre
            if row["genre"] == seed["genre"]:
                score += 25

            # same mood
            if row["mood"] == seed["mood"]:
                score += 18

            # BPM closeness
            score += self.score_distance(
                row["bpm"], seed["bpm"], 80
            ) * 20

            # energy closeness
            score += self.score_distance(
                row["energy"], seed["energy"], 10
            ) * 15

            # era closeness
            score += self.score_distance(
                row["year"], seed["year"], 20
            ) * 10

            # same artist boost
            if row["artist"] == seed["artist"]:
                score += 22

            # popularity
            score += row["popularity"] / 10

            scored.append((score, row))

        scored.sort(reverse=True, key=lambda x: x[0])

        results = []
        for score, row in scored[:limit]:
            results.append({
                "song": row["song"],
                "artist": row["artist"],
                "genre": row["genre"],
                "match": f"{int(self.clamp(score,70,99))}%",
                "why": (
                    f"Matches {seed['song']} in "
                    f"{row['genre']} vibe, BPM, energy and mood."
                ),
                "tags": [
                    row["genre"].lower(),
                    row["mood"].lower(),
                    f"{row['bpm']} BPM"
                ]
            })

        return results

    
    # HISTORY AI (Recs Tab)

    def recommend_from_history(self, history, mood_filter="", limit=5):
        if not history:
            return self.popular(limit)

        # Rank preferences by frequency to create "weights"
        artist_counts = {}
        genre_counts = {}
        for h in history:
            a, g = h.get("artist"), h.get("genre")
            if a: artist_counts[a] = artist_counts.get(a, 0) + 1
            if g: genre_counts[g] = genre_counts.get(g, 0) + 1

        # Get unique lists for the SQL query
        artists = list(artist_counts.keys())
        genres = list(genre_counts.keys())
        total_logs = len(history)

        c = self.conn.cursor()
        artist_marks = ",".join("?" * len(artists)) if artists else "''"
        genre_marks = ",".join("?" * len(genres)) if genres else "''"
        
        query = f"SELECT * FROM songs WHERE (artist IN ({artist_marks}) OR genre IN ({genre_marks}))"
        params = artists + genres
        
        if mood_filter:
            query += " AND lower(mood)=lower(?)"
            params.append(mood_filter.strip())
            
        c.execute(query, params)
        rows = c.fetchall()

        # ALGORITHM: Calculate real match percentage based on history weights
        scored_results = []
        for r in rows:
            # Base confidence
            score = 70.0 
            
            # Boost based on Artist familiarity (Weight: 25%)
            if r["artist"] in artist_counts:
                score += (artist_counts[r["artist"]] / total_logs) * 25
                
            # Boost based on Genre preference (Weight: 10%)
            if r["genre"] in genre_counts:
                score += (genre_counts[r["genre"]] / total_logs) * 10
            
            # Small boost for high popularity (Weight: 5%)
            score += (r["popularity"] / 100) * 5

            scored_results.append((score, r))

        # Sort by the calculated scores
        scored_results.sort(key=lambda x: x[0], reverse=True)

        # Format with the calculated percentage
        results = [
            {
                "song": r["song"],
                "artist": r["artist"],
                "genre": r["genre"],
                "match": f"{int(self.clamp(score, 75, 99))}%", # Use the real score!
                "why": f"Matches your preference for {r['genre']} and {r['artist']}.",
                "tags": [r["genre"].lower(), r["mood"].lower(), "history"]
            }
            for score, r in scored_results[:limit]
        ]

        # Ultimate Fallback (Randomized Popular)
        if len(results) < limit:
            current_songs = [res["song"] for res in results]
            pop_pool = self.popular(limit + 5)
            for p in pop_pool:
                if p["song"] not in current_songs:
                    results.append(p)
                if len(results) == limit: break

        return results

    
    # FALLBACK
    
    def popular(self, limit=5):
        c = self.conn.cursor()
        
        c.execute("""
        SELECT * FROM songs
        ORDER BY popularity DESC
        LIMIT 20
        """)
        rows = c.fetchall()
        
        # Shuffle and select the requested amount
        chosen = random.sample(rows, min(limit, len(rows)))

        return [
            {
                "song": r["song"],
                "artist": r["artist"],
                "genre": r["genre"],
                "match": "90%",
                "why": "A popular favorite across all listeners.",
                "tags": [r["genre"].lower(), r["mood"].lower(), "popular"]
            }
            for r in chosen
        ]