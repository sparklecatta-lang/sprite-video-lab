from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .config import AssetLabConfig


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db(config: AssetLabConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          description TEXT NOT NULL DEFAULT '',
          default_output_dir TEXT NOT NULL DEFAULT '',
          default_style_id INTEGER,
          is_archived INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS styles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          description TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL,
          file_path TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS generation_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER,
          provider TEXT NOT NULL,
          asset_type TEXT NOT NULL,
          component_type TEXT NOT NULL DEFAULT '',
          prompt TEXT NOT NULL,
          negative_prompt TEXT NOT NULL DEFAULT '',
          style_id INTEGER,
          style_text_snapshot TEXT NOT NULL DEFAULT '',
          request_params_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'created',
          error_message TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          completed_at TEXT,
          FOREIGN KEY(project_id) REFERENCES projects(id),
          FOREIGN KEY(style_id) REFERENCES styles(id)
        );

        CREATE TABLE IF NOT EXISTS assets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER,
          source_job_id INTEGER,
          status TEXT NOT NULL DEFAULT 'candidate',
          asset_type TEXT NOT NULL,
          component_type TEXT NOT NULL DEFAULT '',
          provider TEXT NOT NULL DEFAULT 'manual',
          file_path TEXT NOT NULL,
          relative_file_path TEXT NOT NULL,
          thumbnail_path TEXT NOT NULL DEFAULT '',
          relative_thumbnail_path TEXT NOT NULL DEFAULT '',
          width INTEGER NOT NULL DEFAULT 0,
          height INTEGER NOT NULL DEFAULT 0,
          format TEXT NOT NULL DEFAULT '',
          has_alpha INTEGER NOT NULL DEFAULT 0,
          is_transparent_bg INTEGER NOT NULL DEFAULT 0,
          background_color TEXT NOT NULL DEFAULT '',
          prompt TEXT NOT NULL DEFAULT '',
          negative_prompt TEXT NOT NULL DEFAULT '',
          style_id INTEGER,
          style_text_snapshot TEXT NOT NULL DEFAULT '',
          provider_params_json TEXT NOT NULL DEFAULT '{}',
          seed TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          selected_at TEXT,
          rejected_at TEXT,
          notes TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(project_id) REFERENCES projects(id),
          FOREIGN KEY(source_job_id) REFERENCES generation_jobs(id),
          FOREIGN KEY(style_id) REFERENCES styles(id)
        );

        CREATE TABLE IF NOT EXISTS tags (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS asset_tags (
          asset_id INTEGER NOT NULL,
          tag_id INTEGER NOT NULL,
          PRIMARY KEY(asset_id, tag_id),
          FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE,
          FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_assets_project_id ON assets(project_id);
        CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);
        CREATE INDEX IF NOT EXISTS idx_assets_asset_type ON assets(asset_type);
        CREATE INDEX IF NOT EXISTS idx_assets_provider ON assets(provider);
        CREATE INDEX IF NOT EXISTS idx_assets_created_at ON assets(created_at);
        CREATE INDEX IF NOT EXISTS idx_assets_prompt ON assets(prompt);
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, utc_now()),
    )
    conn.commit()
