import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "recipes.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    
    # Seed sample family members if empty
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM family_members")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO family_members (name) VALUES (?)", [("Dad",), ("Mom",), ("Tom",)])
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
