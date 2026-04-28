# sonique_database.py
"""
SONIQUE PRO DATABASE
Advanced local recommendation engine for Sonique

Features:
- mood matching
- BPM matching
- energy matching
- era matching
- artist similarity
- learning from user history
- weighted recommendations

Use:
from sonique_pro_database import SoniqueProDB
db = SoniqueProDB()
db.seed_demo()
db.recommend_next("Blinding Lights","The Weeknd")
"""

import sqlite3
import math
import random
from pathlib import Path

DB_FILE = Path.home() / ".sonique_pro.db"


class SoniqueProDB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    
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
    
    def add_song(
        self,
        song,
        artist,
        genre,
        mood,
        bpm,
        energy,
        year,
        popularity
    ):
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

    
    # DEMO DATA
   
    def seed_demo(self):
        demo = [
            ("Blinding Lights","The Weeknd","Pop","night",171,9,2020,98),
            ("Starboy","The Weeknd","Pop","dark",186,8,2016,95),
            ("Save Your Tears","The Weeknd","Pop","sad",118,7,2021,95),
            ("Levitating","Dua Lipa","Pop","party",103,8,2020,96),
            ("Don't Start Now","Dua Lipa","Pop","dance",124,9,2019,94),
            ("As It Was","Harry Styles","Pop","nostalgic",174,6,2022,95),
            ("Stay","Kid Laroi","Pop","youthful",170,8,2021,93),
            ("Heat Waves","Glass Animals","Indie","dreamy",81,5,2021,93),
            ("Sunflower","Post Malone","HipHop","happy",90,6,2019,96),
            ("Passionfruit","Drake","R&B","late night",112,5,2017,92),
            ("One Dance","Drake","HipHop","summer",104,7,2016,96),
            ("Bad Habit","Steve Lacy","R&B","cool",84,5,2022,92),
            ("Redbone","Childish Gambino","Soul","funky",160,6,2016,91),
            ("Midnight City","M83","Electronic","night",105,7,2011,90),
            ("Electric Feel","MGMT","Indie","party",98,7,2007,90),
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

    
    # MAIN RECOMMENDER
   
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
                    row["genre"],
                    row["mood"],
                    f"{row['bpm']} BPM"
                ]
            })

        return results

    
    # HISTORY AI

    def recommend_from_history(self, history, limit=5):
        if not history:
            return self.popular(limit)

        artists = {}
        genres = {}

        for h in history:
            a = h.get("artist","")
            g = h.get("genre","")

            artists[a] = artists.get(a,0)+1
            genres[g] = genres.get(g,0)+1

        fav_artist = max(artists, key=artists.get)
        fav_genre = max(genres, key=genres.get)

        c = self.conn.cursor()
        c.execute("""
        SELECT * FROM songs
        WHERE artist=? OR genre=?
        ORDER BY popularity DESC
        LIMIT ?
        """, (fav_artist, fav_genre, limit))

        rows = c.fetchall()

        return [
            {
                "song": r["song"],
                "artist": r["artist"],
                "genre": r["genre"],
                "match": "95%",
                "why": f"Based on your love for {fav_artist} and {fav_genre}.",
                "tags": [r["genre"], r["mood"], "history"]
            }
            for r in rows
        ]

    
    # FALLBACK
    
    def popular(self, limit=5):
        c = self.conn.cursor()
        c.execute("""
        SELECT * FROM songs
        ORDER BY popularity DESC
        LIMIT ?
        """, (limit,))
        rows = c.fetchall()

        return [
            {
                "song": r["song"],
                "artist": r["artist"],
                "genre": r["genre"],
                "match": "90%",
                "why": "Popular listener favorite.",
                "tags": [r["genre"], r["mood"], "popular"]
            }
            for r in rows
        ]


c = conn.cursor()
