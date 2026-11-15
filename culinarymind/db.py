import sqlite3
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS pantry(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, qty REAL NOT NULL,
  unit TEXT NOT NULL, category TEXT DEFAULT 'Other', purchase_date TEXT, expiry_date TEXT);
CREATE TABLE IF NOT EXISTS plan(day INTEGER, meal TEXT, recipe_id TEXT, PRIMARY KEY(day, meal));
CREATE TABLE IF NOT EXISTS preferences(id INTEGER PRIMARY KEY AUTOINCREMENT, rule TEXT, source TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id TEXT, rating INTEGER, effort TEXT, notes TEXT, created TEXT);
"""

def connect(path=None):
    con = sqlite3.connect(path or config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
