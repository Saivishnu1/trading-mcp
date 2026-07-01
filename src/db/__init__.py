"""PostgreSQL async database layer — Oracle VM production only.

SQLite (src/journal/db.py) is still used on Windows dev and Railway.
This module is only imported when DATABASE_URL is set and points to PostgreSQL.
"""
