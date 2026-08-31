"""
config/database.py
Re-export database helpers for Laravel-style config access.
Preserves original database/db.py functionality via app.Models.db
"""
from app.Models.db import get_db_connection, using_postgres

__all__ = ["get_db_connection", "using_postgres"]
