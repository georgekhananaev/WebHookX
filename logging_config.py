# logging_config.py

import logging
import sqlite3
from datetime import datetime
import os

LOG_DB_PATH = os.getenv("LOG_DB_PATH", "logs.db")
MAX_LOG_ENTRIES = 10000  # Maximum number of log entries to keep


class SQLiteHandler(logging.Handler):
    def __init__(self, db_path=LOG_DB_PATH, max_entries=MAX_LOG_ENTRIES):
        super().__init__()
        self.db_path = db_path
        self.max_entries = max_entries
        self.create_table()

    def create_table(self):
        """Creates the logs table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                module TEXT,
                exception TEXT
            )
        """)
        # Create an index on the id column to optimize deletion queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_id ON logs (id DESC)
        """)
        conn.commit()
        conn.close()

    def emit(self, record):
        """Inserts a log record into the SQLite database and enforces max log entries."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Prepare log data
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": record.levelname,
                "message": record.getMessage(),
                "module": record.module,
                "exception": record.exc_text,
            }

            # Insert log into database
            cursor.execute("""
                INSERT INTO logs (timestamp, level, message, module, exception)
                VALUES (:timestamp, :level, :message, :module, :exception)
            """, log_entry)

            # Enforce maximum number of log entries
            cursor.execute("SELECT COUNT(*) FROM logs")
            count = cursor.fetchone()[0]
            if count > self.max_entries:
                # Calculate number of logs to delete
                excess = count - self.max_entries
                # Delete the oldest 'excess' logs
                cursor.execute("""
                    DELETE FROM logs
                    WHERE id IN (
                        SELECT id FROM logs
                        ORDER BY id ASC
                        LIMIT ?
                    )
                """, (excess,))
                conn.commit()

            conn.commit()
        except Exception as e:
            # If logging fails, print to stderr as a last resort
            print(f"Failed to log to SQLite database: {e}")
        finally:
            conn.close()


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Set to DEBUG for detailed logs

    # Console handler for real-time logs
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")  # noqa
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # SQLite handler for persistent logs
    sqlite_handler = SQLiteHandler(db_path=LOG_DB_PATH, max_entries=MAX_LOG_ENTRIES)
    sqlite_handler.setLevel(logging.DEBUG)
    sqlite_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")  # noqa
    sqlite_handler.setFormatter(sqlite_formatter)
    logger.addHandler(sqlite_handler)
