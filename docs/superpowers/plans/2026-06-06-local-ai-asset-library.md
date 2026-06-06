# Local AI Asset Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Sprite Video Lab into a general local AI asset library and generation workbench with ToioTo/OpenAI provider choice, SQLite-backed history, user-created project categories, and local-only asset storage.

**Architecture:** Keep the current single Python HTTP server and static frontend, but split new asset-library behavior into focused Python modules under `asset_lab/`. Images remain as files in a user-selected external workspace; SQLite stores searchable metadata, generation jobs, projects, styles, and provider parameters.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, Pillow, current `http.server` app, vanilla HTML/CSS/JavaScript, optional provider clients for ToioTo and OpenAI.

---

## Product Scope

Sprite Video Lab should become a general-purpose local asset library application. It must not hard-code any specific game, project, art style, or repository path. Users manually create project categories inside a single global library, then assign generated or imported assets to those categories.

The tool must store generated image files outside the code repository by default. The recommended default workspace is:

```text
%LOCALAPPDATA%\SpriteVideoLab\workspace
```

Users may change this path in Settings. The code repository keeps app source only; generated images, thumbnails, and the SQLite database live in the external workspace.

## User-Facing Requirements

- The app has one global local asset library.
- Users manually create project categories; the app does not auto-detect projects from the current directory.
- Each asset records project, type, component type, dimensions, background color, transparency state, local image path, prompt, provider/source, provider parameters, timestamps, and status.
- Providers include ToioTo and OpenAI, selectable per generation job.
- API keys are read from environment variables only:
  - `TOIOTO_API_KEY`
  - `OPENAI_API_KEY`
- Users can provide style context via:
  - a free-text style box
  - a saved style document in the local library
  - no style context
- The Library view loads previous generated/imported images on startup.
- The Library view shows thumbnails, prompt, project, type, provider, status, size, alpha/transparency, and creation time.
- Users can filter and search by project, asset type, component type, provider, status, transparency, size, background color, prompt text, tags, and date range.
- Selecting an asset moves or copies it into the library's `selected/` folder or a project category's optional default output folder.
- Rejecting an asset marks it rejected and optionally moves/copies it into `rejected/`.
- The app should preserve original generation metadata after selected/rejected state changes.

## Workspace Layout

The default external workspace should be:

```text
%LOCALAPPDATA%\SpriteVideoLab\workspace
  images\
    candidates\
    selected\
    rejected\
    imported\
  thumbnails\
  styles\
  tmp\
  asset_lab.sqlite
```

Files are referenced in SQLite using absolute paths plus a workspace-relative path. The absolute path makes serving files simple; the relative path makes future workspace migration possible.

## Database Schema

Use SQLite. Create schema with idempotent migrations stored in code. A fresh app startup must create the database and required tables automatically.

```sql
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
```

## File Structure

- Create: `asset_lab/__init__.py`
  - Package marker.
- Create: `asset_lab/config.py`
  - Resolve workspace path from environment/settings, create required directories, expose paths.
- Create: `asset_lab/db.py`
  - SQLite connection helper, row serialization, migration runner.
- Create: `asset_lab/models.py`
  - Dataclasses/constants for projects, styles, jobs, assets, valid statuses, and asset types.
- Create: `asset_lab/images.py`
  - Save images, create thumbnails, inspect dimensions/format/alpha/background color.
- Create: `asset_lab/providers/__init__.py`
  - Provider registry.
- Create: `asset_lab/providers/base.py`
  - Provider interface and request/result dataclasses.
- Create: `asset_lab/providers/toioto.py`
  - ToioTo provider adapter, reads `TOIOTO_API_KEY`.
- Create: `asset_lab/providers/openai_images.py`
  - OpenAI image provider adapter, reads `OPENAI_API_KEY`.
- Create: `asset_lab/repository.py`
  - CRUD operations for projects, styles, generation jobs, assets, tags, and search filters.
- Modify: `server.py`
  - Add Asset Lab API routes and static serving for workspace thumbnails/images. Keep existing sprite/video endpoints intact.
- Modify: `app/index.html`
  - Add tabs or sections for Generate, Library, Projects, Styles, Settings while keeping existing sprite processing workflow accessible.
- Modify: `app/app.js`
  - Add client state, API calls, generation form, library grid, filters, asset detail panel.
- Modify: `app/styles.css`
  - Add library grid, filter sidebar, detail drawer, settings form styles.
- Create: `tests/asset_lab/test_db.py`
  - Migration and repository tests.
- Create: `tests/asset_lab/test_images.py`
  - Image inspection and thumbnail tests.
- Create: `tests/asset_lab/test_api.py`
  - HTTP route smoke tests with a temporary workspace.
- Modify: `.gitignore`
  - Ignore local test workspaces and generated `asset_lab.sqlite` if created inside the repo during tests.

## API Routes

Add JSON endpoints under `/api/asset-lab`.

```text
GET    /api/asset-lab/status
GET    /api/asset-lab/projects
POST   /api/asset-lab/projects
PATCH  /api/asset-lab/projects/{id}
GET    /api/asset-lab/styles
POST   /api/asset-lab/styles
PATCH  /api/asset-lab/styles/{id}
GET    /api/asset-lab/assets
GET    /api/asset-lab/assets/{id}
PATCH  /api/asset-lab/assets/{id}
POST   /api/asset-lab/assets/{id}/select
POST   /api/asset-lab/assets/{id}/reject
POST   /api/asset-lab/generate
GET    /api/asset-lab/jobs/{id}
POST   /api/asset-lab/import
```

Serve workspace files through safe bounded routes:

```text
GET /asset-lab-files/thumbnails/{path}
GET /asset-lab-files/images/{path}
```

The server must verify requested paths resolve inside the configured workspace.

## Implementation Tasks

### Task 1: Workspace Config and SQLite Migrations

**Files:**
- Create: `asset_lab/__init__.py`
- Create: `asset_lab/config.py`
- Create: `asset_lab/db.py`
- Create: `tests/asset_lab/test_db.py`

- [ ] **Step 1: Add failing tests for workspace creation and migration**

Create `tests/asset_lab/test_db.py`:

```python
import sqlite3

from asset_lab.config import AssetLabConfig
from asset_lab.db import connect_db, migrate


def test_workspace_directories_are_created(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()

    assert config.workspace_root.exists()
    assert config.images_candidates_dir.exists()
    assert config.images_selected_dir.exists()
    assert config.images_rejected_dir.exists()
    assert config.images_imported_dir.exists()
    assert config.thumbnails_dir.exists()
    assert config.styles_dir.exists()
    assert config.tmp_dir.exists()


def test_migrate_creates_core_tables(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()

    with connect_db(config) as conn:
        migrate(conn)
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "projects" in table_names
    assert "styles" in table_names
    assert "generation_jobs" in table_names
    assert "assets" in table_names
    assert "tags" in table_names
    assert "asset_tags" in table_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_db.py -v
```

Expected: FAIL because `asset_lab` does not exist.

- [ ] **Step 3: Implement workspace config and DB migration**

Create `asset_lab/__init__.py`:

```python
"""Local asset library package for Sprite Video Lab."""
```

Create `asset_lab/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_ENV = "SPRITE_VIDEO_LAB_WORKSPACE"


def default_workspace_root() -> Path:
    configured = os.environ.get(WORKSPACE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "SpriteVideoLab" / "workspace"
    return Path.home() / ".sprite-video-lab" / "workspace"


@dataclass(frozen=True)
class AssetLabConfig:
    workspace_root: Path

    @property
    def db_path(self) -> Path:
        return self.workspace_root / "asset_lab.sqlite"

    @property
    def images_dir(self) -> Path:
        return self.workspace_root / "images"

    @property
    def images_candidates_dir(self) -> Path:
        return self.images_dir / "candidates"

    @property
    def images_selected_dir(self) -> Path:
        return self.images_dir / "selected"

    @property
    def images_rejected_dir(self) -> Path:
        return self.images_dir / "rejected"

    @property
    def images_imported_dir(self) -> Path:
        return self.images_dir / "imported"

    @property
    def thumbnails_dir(self) -> Path:
        return self.workspace_root / "thumbnails"

    @property
    def styles_dir(self) -> Path:
        return self.workspace_root / "styles"

    @property
    def tmp_dir(self) -> Path:
        return self.workspace_root / "tmp"

    def ensure(self) -> None:
        for directory in (
            self.workspace_root,
            self.images_candidates_dir,
            self.images_selected_dir,
            self.images_rejected_dir,
            self.images_imported_dir,
            self.thumbnails_dir,
            self.styles_dir,
            self.tmp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def load_config() -> AssetLabConfig:
    return AssetLabConfig(default_workspace_root())
```

Create `asset_lab/db.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_db.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add asset_lab tests/asset_lab/test_db.py
git commit -m "feat: add asset lab workspace and database schema"
```

### Task 2: Repository for Projects, Styles, Jobs, and Asset Search

**Files:**
- Create: `asset_lab/models.py`
- Create: `asset_lab/repository.py`
- Create: `tests/asset_lab/test_repository.py`

- [ ] **Step 1: Add failing repository tests**

Create `tests/asset_lab/test_repository.py`:

```python
from asset_lab.config import AssetLabConfig
from asset_lab.db import connect_db, migrate
from asset_lab.repository import AssetRepository


def make_repo(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()
    conn = connect_db(config)
    migrate(conn)
    return AssetRepository(conn)


def test_create_project_and_style(tmp_path):
    repo = make_repo(tmp_path)

    project = repo.create_project("Project A", "Local category")
    style = repo.create_style("Soft UI", "rounded bright interface")

    assert project["name"] == "Project A"
    assert project["description"] == "Local category"
    assert style["name"] == "Soft UI"
    assert style["body"] == "rounded bright interface"


def test_search_assets_by_project_status_and_prompt(tmp_path):
    repo = make_repo(tmp_path)
    project = repo.create_project("Project A", "")
    other = repo.create_project("Project B", "")

    repo.create_asset(
        project_id=project["id"],
        asset_type="icon",
        component_type="item_icon",
        provider="openai",
        file_path="D:/library/images/candidates/a.png",
        relative_file_path="images/candidates/a.png",
        width=1024,
        height=1024,
        has_alpha=True,
        is_transparent_bg=True,
        prompt="blue crystal bottle",
    )
    repo.create_asset(
        project_id=other["id"],
        asset_type="background",
        component_type="landscape",
        provider="toioto",
        file_path="D:/library/images/candidates/b.png",
        relative_file_path="images/candidates/b.png",
        width=1920,
        height=1080,
        has_alpha=False,
        is_transparent_bg=False,
        prompt="mountain sunset",
    )

    results = repo.search_assets(
        {
            "project_id": project["id"],
            "status": "candidate",
            "prompt": "crystal",
        }
    )

    assert len(results) == 1
    assert results[0]["prompt"] == "blue crystal bottle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_repository.py -v
```

Expected: FAIL because `repository.py` does not exist.

- [ ] **Step 3: Implement models and repository**

Create `asset_lab/models.py`:

```python
VALID_ASSET_STATUSES = {"candidate", "selected", "rejected", "archived"}
VALID_JOB_STATUSES = {"created", "running", "completed", "failed"}
VALID_PROVIDERS = {"manual", "toioto", "openai"}
```

Create `asset_lab/repository.py`:

```python
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import utc_now
from .models import VALID_ASSET_STATUSES


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


class AssetRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        now = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO projects(name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (name.strip(), description.strip(), now, now),
        )
        self.conn.commit()
        return self.get_project(cursor.lastrowid)

    def get_project(self, project_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"project not found: {project_id}")
        return row_to_dict(row)

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        if include_archived:
            rows = self.conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM projects WHERE is_archived = 0 ORDER BY name"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def create_style(self, name: str, body: str, description: str = "") -> dict[str, Any]:
        now = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO styles(name, description, body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name.strip(), description.strip(), body, now, now),
        )
        self.conn.commit()
        return self.get_style(cursor.lastrowid)

    def get_style(self, style_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM styles WHERE id = ?", (style_id,)).fetchone()
        if row is None:
            raise KeyError(f"style not found: {style_id}")
        return row_to_dict(row)

    def create_generation_job(
        self,
        *,
        project_id: int | None,
        provider: str,
        asset_type: str,
        component_type: str,
        prompt: str,
        negative_prompt: str = "",
        style_id: int | None = None,
        style_text_snapshot: str = "",
        request_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO generation_jobs(
              project_id, provider, asset_type, component_type, prompt,
              negative_prompt, style_id, style_text_snapshot, request_params_json,
              status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?)
            """,
            (
                project_id,
                provider,
                asset_type,
                component_type,
                prompt,
                negative_prompt,
                style_id,
                style_text_snapshot,
                json.dumps(request_params or {}, ensure_ascii=False),
                now,
            ),
        )
        self.conn.commit()
        return self.get_generation_job(cursor.lastrowid)

    def get_generation_job(self, job_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"generation job not found: {job_id}")
        return row_to_dict(row)

    def create_asset(
        self,
        *,
        project_id: int | None,
        asset_type: str,
        component_type: str,
        provider: str,
        file_path: str,
        relative_file_path: str,
        width: int,
        height: int,
        has_alpha: bool,
        is_transparent_bg: bool,
        prompt: str,
        source_job_id: int | None = None,
        thumbnail_path: str = "",
        relative_thumbnail_path: str = "",
        format: str = "png",
        background_color: str = "",
        negative_prompt: str = "",
        style_id: int | None = None,
        style_text_snapshot: str = "",
        provider_params: dict[str, Any] | None = None,
        seed: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO assets(
              project_id, source_job_id, asset_type, component_type, provider,
              file_path, relative_file_path, thumbnail_path, relative_thumbnail_path,
              width, height, format, has_alpha, is_transparent_bg, background_color,
              prompt, negative_prompt, style_id, style_text_snapshot,
              provider_params_json, seed, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                source_job_id,
                asset_type,
                component_type,
                provider,
                file_path,
                relative_file_path,
                thumbnail_path,
                relative_thumbnail_path,
                width,
                height,
                format,
                1 if has_alpha else 0,
                1 if is_transparent_bg else 0,
                background_color,
                prompt,
                negative_prompt,
                style_id,
                style_text_snapshot,
                json.dumps(provider_params or {}, ensure_ascii=False),
                seed,
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.get_asset(cursor.lastrowid)

    def get_asset(self, asset_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(f"asset not found: {asset_id}")
        return row_to_dict(row)

    def mark_asset_status(self, asset_id: int, status: str) -> dict[str, Any]:
        if status not in VALID_ASSET_STATUSES:
            raise ValueError(f"invalid asset status: {status}")
        now = utc_now()
        selected_at = now if status == "selected" else None
        rejected_at = now if status == "rejected" else None
        self.conn.execute(
            """
            UPDATE assets
            SET status = ?,
                updated_at = ?,
                selected_at = COALESCE(?, selected_at),
                rejected_at = COALESCE(?, rejected_at)
            WHERE id = ?
            """,
            (status, now, selected_at, rejected_at, asset_id),
        )
        self.conn.commit()
        return self.get_asset(asset_id)

    def search_assets(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if filters.get("project_id") is not None:
            clauses.append("project_id = ?")
            params.append(filters["project_id"])
        if filters.get("status"):
            clauses.append("status = ?")
            params.append(filters["status"])
        if filters.get("asset_type"):
            clauses.append("asset_type = ?")
            params.append(filters["asset_type"])
        if filters.get("component_type"):
            clauses.append("component_type = ?")
            params.append(filters["component_type"])
        if filters.get("provider"):
            clauses.append("provider = ?")
            params.append(filters["provider"])
        if filters.get("has_alpha") is not None:
            clauses.append("has_alpha = ?")
            params.append(1 if filters["has_alpha"] else 0)
        if filters.get("prompt"):
            clauses.append("prompt LIKE ?")
            params.append(f"%{filters['prompt']}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM assets {where} ORDER BY created_at DESC, id DESC",
            params,
        ).fetchall()
        return [row_to_dict(row) for row in rows]
```

- [ ] **Step 4: Run repository tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_repository.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add asset_lab/models.py asset_lab/repository.py tests/asset_lab/test_repository.py
git commit -m "feat: add asset lab repository"
```

### Task 3: Image Storage, Inspection, and Thumbnails

**Files:**
- Create: `asset_lab/images.py`
- Create: `tests/asset_lab/test_images.py`

- [ ] **Step 1: Add failing image tests**

Create `tests/asset_lab/test_images.py`:

```python
from PIL import Image

from asset_lab.config import AssetLabConfig
from asset_lab.images import inspect_image, save_candidate_image


def test_inspect_transparent_png(tmp_path):
    image_path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (32, 24), (0, 0, 0, 0))
    image.save(image_path)

    info = inspect_image(image_path)

    assert info.width == 32
    assert info.height == 24
    assert info.format == "png"
    assert info.has_alpha is True
    assert info.is_transparent_bg is True


def test_save_candidate_image_creates_file_and_thumbnail(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()
    source = tmp_path / "source.png"
    Image.new("RGBA", (128, 128), (255, 0, 0, 255)).save(source)

    saved = save_candidate_image(config, source, "openai", "icon")

    assert saved.file_path.exists()
    assert saved.thumbnail_path.exists()
    assert saved.relative_file_path.startswith("images/candidates/")
    assert saved.relative_thumbnail_path.startswith("thumbnails/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_images.py -v
```

Expected: FAIL because `images.py` does not exist.

- [ ] **Step 3: Implement image helpers**

Create `asset_lab/images.py`:

```python
from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .config import AssetLabConfig


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    format: str
    has_alpha: bool
    is_transparent_bg: bool
    background_color: str


@dataclass(frozen=True)
class SavedImage:
    file_path: Path
    relative_file_path: str
    thumbnail_path: Path
    relative_thumbnail_path: str
    info: ImageInfo


def _hex_rgb(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def inspect_image(path: Path) -> ImageInfo:
    with Image.open(path) as image:
        width, height = image.size
        fmt = (image.format or path.suffix.lstrip(".") or "").lower()
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        has_alpha = alpha.getextrema() != (255, 255)
        corner_pixels = [
            rgba.getpixel((0, 0)),
            rgba.getpixel((width - 1, 0)),
            rgba.getpixel((0, height - 1)),
            rgba.getpixel((width - 1, height - 1)),
        ]
        transparent_corners = all(pixel[3] == 0 for pixel in corner_pixels)
        background_color = ""
        opaque_corners = [pixel for pixel in corner_pixels if pixel[3] > 0]
        if opaque_corners:
            background_color = _hex_rgb(opaque_corners[0][:3])
        return ImageInfo(
            width=width,
            height=height,
            format=fmt,
            has_alpha=has_alpha,
            is_transparent_bg=transparent_corners,
            background_color=background_color,
        )


def _workspace_relative(config: AssetLabConfig, path: Path) -> str:
    return path.relative_to(config.workspace_root).as_posix()


def create_thumbnail(source: Path, target: Path, size: int = 256) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        thumb = image.convert("RGBA")
        thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        offset = ((size - thumb.width) // 2, (size - thumb.height) // 2)
        canvas.alpha_composite(thumb, offset)
        canvas.save(target)


def save_candidate_image(config: AssetLabConfig, source: Path, provider: str, asset_type: str) -> SavedImage:
    config.ensure()
    suffix = source.suffix.lower() or ".png"
    stem = f"{provider}_{asset_type}_{uuid.uuid4().hex[:12]}"
    target = config.images_candidates_dir / f"{stem}{suffix}"
    shutil.copy2(source, target)
    thumbnail = config.thumbnails_dir / f"{stem}.png"
    create_thumbnail(target, thumbnail)
    info = inspect_image(target)
    return SavedImage(
        file_path=target,
        relative_file_path=_workspace_relative(config, target),
        thumbnail_path=thumbnail,
        relative_thumbnail_path=_workspace_relative(config, thumbnail),
        info=info,
    )
```

- [ ] **Step 4: Run image tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_images.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add asset_lab/images.py tests/asset_lab/test_images.py
git commit -m "feat: add asset image storage helpers"
```

### Task 4: Provider Interface and Mockable Generation Flow

**Files:**
- Create: `asset_lab/providers/__init__.py`
- Create: `asset_lab/providers/base.py`
- Create: `asset_lab/providers/toioto.py`
- Create: `asset_lab/providers/openai_images.py`
- Create: `tests/asset_lab/test_providers.py`

- [ ] **Step 1: Add failing provider tests**

Create `tests/asset_lab/test_providers.py`:

```python
import os

from asset_lab.providers import get_provider, list_providers


def test_list_providers_includes_toioto_and_openai():
    providers = list_providers()

    assert "toioto" in providers
    assert "openai" in providers


def test_provider_reports_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = get_provider("openai")

    assert provider.is_configured() is False
    assert "OPENAI_API_KEY" in provider.configuration_message()


def test_unknown_provider_raises_key_error():
    try:
        get_provider("unknown")
    except KeyError as exc:
        assert "unknown provider" in str(exc)
    else:
        raise AssertionError("expected KeyError")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_providers.py -v
```

Expected: FAIL because provider modules do not exist.

- [ ] **Step 3: Implement provider registry and stubs**

Create `asset_lab/providers/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class GenerationRequest:
    project_id: int | None
    asset_type: str
    component_type: str
    prompt: str
    negative_prompt: str = ""
    style_text: str = ""
    width: int = 1024
    height: int = 1024
    count: int = 1
    transparent_background: bool = False
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationResult:
    image_paths: list[Path]
    provider_params: dict[str, Any]
    seeds: list[str] = field(default_factory=list)


class ImageProvider(Protocol):
    name: str

    def is_configured(self) -> bool:
        ...

    def configuration_message(self) -> str:
        ...

    def generate(self, request: GenerationRequest, output_dir: Path) -> GenerationResult:
        ...
```

Create `asset_lab/providers/openai_images.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

from .base import GenerationRequest, GenerationResult


class OpenAIImagesProvider:
    name = "openai"
    api_key_env = "OPENAI_API_KEY"

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.api_key_env, "").strip())

    def configuration_message(self) -> str:
        if self.is_configured():
            return "OpenAI image generation is configured."
        return f"Set {self.api_key_env} to enable OpenAI image generation."

    def generate(self, request: GenerationRequest, output_dir: Path) -> GenerationResult:
        if not self.is_configured():
            raise RuntimeError(self.configuration_message())
        raise NotImplementedError("OpenAI image generation API call is implemented in the next provider task.")
```

Create `asset_lab/providers/toioto.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

from .base import GenerationRequest, GenerationResult


class ToioToProvider:
    name = "toioto"
    api_key_env = "TOIOTO_API_KEY"

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.api_key_env, "").strip())

    def configuration_message(self) -> str:
        if self.is_configured():
            return "ToioTo image generation is configured."
        return f"Set {self.api_key_env} to enable ToioTo image generation."

    def generate(self, request: GenerationRequest, output_dir: Path) -> GenerationResult:
        if not self.is_configured():
            raise RuntimeError(self.configuration_message())
        raise NotImplementedError("ToioTo image generation API call is implemented in the next provider task.")
```

Create `asset_lab/providers/__init__.py`:

```python
from __future__ import annotations

from .openai_images import OpenAIImagesProvider
from .toioto import ToioToProvider


def _providers():
    return {
        "openai": OpenAIImagesProvider(),
        "toioto": ToioToProvider(),
    }


def list_providers() -> list[str]:
    return sorted(_providers().keys())


def get_provider(name: str):
    providers = _providers()
    if name not in providers:
        raise KeyError(f"unknown provider: {name}")
    return providers[name]
```

- [ ] **Step 4: Run provider tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_providers.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add asset_lab/providers tests/asset_lab/test_providers.py
git commit -m "feat: add image provider interface"
```

### Task 5: Asset Lab API Routes

**Files:**
- Modify: `server.py`
- Create: `tests/asset_lab/test_api.py`

- [ ] **Step 1: Add API smoke tests**

Create `tests/asset_lab/test_api.py`:

```python
import json
import os

from asset_lab.config import AssetLabConfig
from asset_lab.db import connect_db, migrate
from asset_lab.repository import AssetRepository


def test_status_payload_uses_configured_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_VIDEO_LAB_WORKSPACE", str(tmp_path / "workspace"))

    from server import asset_lab_status_payload

    payload = asset_lab_status_payload()

    assert payload["workspace_root"] == str(tmp_path / "workspace")
    assert "openai" in payload["providers"]
    assert "toioto" in payload["providers"]


def test_create_project_api_handler_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_VIDEO_LAB_WORKSPACE", str(tmp_path / "workspace"))

    from server import create_asset_lab_project_payload

    payload = create_asset_lab_project_payload({"name": "Project A", "description": "manual"})

    assert payload["name"] == "Project A"
    assert payload["description"] == "manual"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_api.py -v
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 3: Add API helper functions to `server.py`**

Add imports near the existing imports:

```python
from asset_lab.config import load_config
from asset_lab.db import connect_db, migrate
from asset_lab.providers import get_provider, list_providers
from asset_lab.repository import AssetRepository
```

Add these helper functions near other top-level helpers:

```python
def asset_lab_repo() -> tuple[AssetLabConfig, sqlite3.Connection, AssetRepository]:
    config = load_config()
    config.ensure()
    conn = connect_db(config)
    migrate(conn)
    return config, conn, AssetRepository(conn)


def asset_lab_status_payload() -> dict:
    config = load_config()
    config.ensure()
    providers = {}
    for provider_name in list_providers():
        provider = get_provider(provider_name)
        providers[provider_name] = {
            "configured": provider.is_configured(),
            "message": provider.configuration_message(),
        }
    return {
        "workspace_root": str(config.workspace_root),
        "providers": providers,
    }


def create_asset_lab_project_payload(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("project name is required")
    description = str(payload.get("description", "")).strip()
    config, conn, repo = asset_lab_repo()
    try:
        return repo.create_project(name, description)
    finally:
        conn.close()
```

If `server.py` does not already import `sqlite3`, add:

```python
import sqlite3
```

- [ ] **Step 4: Wire HTTP routes**

Inside `AppHandler.do_GET`, before the existing fallback routes, add handling for:

```python
if parsed.path == "/api/asset-lab/status":
    self.send_json(asset_lab_status_payload())
    return
if parsed.path == "/api/asset-lab/projects":
    config, conn, repo = asset_lab_repo()
    try:
        self.send_json({"projects": repo.list_projects()})
    finally:
        conn.close()
    return
if parsed.path == "/api/asset-lab/assets":
    query = parse_qs(parsed.query)
    filters = {
        "project_id": int(query["project_id"][0]) if query.get("project_id") else None,
        "status": query.get("status", [""])[0],
        "asset_type": query.get("asset_type", [""])[0],
        "component_type": query.get("component_type", [""])[0],
        "provider": query.get("provider", [""])[0],
        "prompt": query.get("prompt", [""])[0],
    }
    config, conn, repo = asset_lab_repo()
    try:
        self.send_json({"assets": repo.search_assets(filters)})
    finally:
        conn.close()
    return
```

Inside `AppHandler.do_POST`, add handling for:

```python
if parsed.path == "/api/asset-lab/projects":
    payload = self.read_json()
    self.send_json(create_asset_lab_project_payload(payload), status=201)
    return
```

Use existing JSON helper conventions in `server.py`. If helper names differ, implement wrappers without changing existing endpoint behavior.

- [ ] **Step 5: Run API tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Run server syntax check**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile server.py
```

Expected: no output and exit code 0.

- [ ] **Step 7: Commit**

```powershell
git add server.py tests/asset_lab/test_api.py
git commit -m "feat: add asset lab api routes"
```

### Task 6: Generate Page and Provider Status UI

**Files:**
- Modify: `app/index.html`
- Modify: `app/app.js`
- Modify: `app/styles.css`

- [ ] **Step 1: Add Generate and Library shell markup**

In `app/index.html`, add a new navigation row near the top of the main layout:

```html
<nav class="asset-lab-tabs" aria-label="Asset Lab">
  <button class="asset-lab-tab is-active" type="button" data-asset-lab-tab="generate">Generate</button>
  <button class="asset-lab-tab" type="button" data-asset-lab-tab="library">Library</button>
  <button class="asset-lab-tab" type="button" data-asset-lab-tab="projects">Projects</button>
  <button class="asset-lab-tab" type="button" data-asset-lab-tab="styles">Styles</button>
  <button class="asset-lab-tab" type="button" data-asset-lab-tab="settings">Settings</button>
</nav>
```

Add a Generate section:

```html
<section id="assetLabGenerate" class="asset-lab-panel">
  <div class="panel-head">
    <div>
      <h2>Asset Generation</h2>
      <p>Create local candidate assets with a selected provider and optional style context.</p>
    </div>
  </div>
  <div id="providerStatus" class="provider-status-grid"></div>
  <div class="asset-lab-form-grid">
    <label class="field">
      <span>Project</span>
      <select id="assetProjectSelect"></select>
    </label>
    <label class="field">
      <span>Provider</span>
      <select id="assetProviderSelect">
        <option value="openai">OpenAI</option>
        <option value="toioto">ToioTo</option>
      </select>
    </label>
    <label class="field">
      <span>Asset Type</span>
      <input id="assetTypeInput" type="text" value="icon">
    </label>
    <label class="field">
      <span>Component Type</span>
      <input id="componentTypeInput" type="text" placeholder="item_icon, button, portrait">
    </label>
  </div>
  <label class="field">
    <span>Style Context</span>
    <textarea id="styleContextInput" rows="5" placeholder="Optional style description for this generation."></textarea>
  </label>
  <label class="field">
    <span>Prompt</span>
    <textarea id="assetPromptInput" rows="6" placeholder="Describe the asset to generate."></textarea>
  </label>
  <div class="asset-lab-form-grid">
    <label class="field">
      <span>Width</span>
      <input id="assetWidthInput" type="number" value="1024" min="64">
    </label>
    <label class="field">
      <span>Height</span>
      <input id="assetHeightInput" type="number" value="1024" min="64">
    </label>
    <label class="field checkbox-field">
      <input id="transparentBackgroundInput" type="checkbox">
      <span>Transparent background</span>
    </label>
  </div>
  <button id="generateAssetButton" class="primary-button" type="button">Generate Candidate</button>
</section>
```

- [ ] **Step 2: Add frontend API calls**

In `app/app.js`, add:

```javascript
const assetLabState = {
  status: null,
  projects: [],
  assets: [],
};

async function assetLabFetch(path, options = {}) {
  const response = await fetch(`/api/asset-lab${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

async function loadAssetLabStatus() {
  assetLabState.status = await assetLabFetch("/status");
  renderProviderStatus();
}

async function loadAssetLabProjects() {
  const payload = await assetLabFetch("/projects");
  assetLabState.projects = payload.projects || [];
  renderProjectOptions();
}

function renderProviderStatus() {
  const root = document.getElementById("providerStatus");
  if (!root || !assetLabState.status) return;
  root.innerHTML = Object.entries(assetLabState.status.providers)
    .map(([name, info]) => `
      <div class="provider-status ${info.configured ? "is-ready" : "is-missing"}">
        <strong>${escapeHtml(name)}</strong>
        <span>${escapeHtml(info.message)}</span>
      </div>
    `)
    .join("");
}

function renderProjectOptions() {
  const select = document.getElementById("assetProjectSelect");
  if (!select) return;
  const options = ['<option value="">Inbox / Unassigned</option>'];
  for (const project of assetLabState.projects) {
    options.push(`<option value="${project.id}">${escapeHtml(project.name)}</option>`);
  }
  select.innerHTML = options.join("");
}

function initAssetLabUi() {
  loadAssetLabStatus().catch(showError);
  loadAssetLabProjects().catch(showError);
}
```

Call `initAssetLabUi()` from the existing startup/init function.

- [ ] **Step 3: Add CSS**

In `app/styles.css`, add:

```css
.asset-lab-tabs {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 16px 0;
  overflow-x: auto;
}

.asset-lab-tab {
  border: 1px solid var(--border-color, #d7dbe3);
  background: #fff;
  color: #243044;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
}

.asset-lab-tab.is-active {
  background: #243044;
  color: #fff;
}

.asset-lab-panel {
  margin: 16px 0;
}

.asset-lab-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.provider-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 12px 0;
}

.provider-status {
  border: 1px solid #d7dbe3;
  border-radius: 6px;
  padding: 10px;
  background: #fff;
}

.provider-status.is-ready {
  border-color: #4f9d69;
}

.provider-status.is-missing {
  border-color: #c98239;
}

.provider-status strong,
.provider-status span {
  display: block;
}
```

- [ ] **Step 4: Verify UI loads**

Run:

```powershell
.\.venv\Scripts\python.exe server.py --serve --host 127.0.0.1 --port 8894
```

Open:

```text
http://127.0.0.1:8894/
```

Expected:
- Asset Lab tabs are visible.
- Provider status shows OpenAI and ToioTo.
- Project dropdown includes Inbox / Unassigned.
- Existing sprite processing UI still appears and remains usable.

- [ ] **Step 5: Commit**

```powershell
git add app/index.html app/app.js app/styles.css
git commit -m "feat: add asset lab generation UI shell"
```

### Task 7: Library View, Filters, and Asset Detail

**Files:**
- Modify: `app/index.html`
- Modify: `app/app.js`
- Modify: `app/styles.css`
- Modify: `server.py`

- [ ] **Step 1: Add Library markup**

In `app/index.html`, add:

```html
<section id="assetLabLibrary" class="asset-lab-panel" hidden>
  <div class="panel-head">
    <div>
      <h2>Library</h2>
      <p>Browse local assets from the global library.</p>
    </div>
  </div>
  <div class="library-layout">
    <aside class="library-filters">
      <label class="field">
        <span>Project</span>
        <select id="libraryProjectFilter"></select>
      </label>
      <label class="field">
        <span>Status</span>
        <select id="libraryStatusFilter">
          <option value="">All</option>
          <option value="candidate">Candidate</option>
          <option value="selected">Selected</option>
          <option value="rejected">Rejected</option>
          <option value="archived">Archived</option>
        </select>
      </label>
      <label class="field">
        <span>Prompt</span>
        <input id="libraryPromptFilter" type="search" placeholder="Search prompt">
      </label>
      <button id="libraryRefreshButton" type="button">Refresh</button>
    </aside>
    <div id="assetGrid" class="asset-grid"></div>
  </div>
</section>
```

- [ ] **Step 2: Add Library JavaScript**

In `app/app.js`, add:

```javascript
async function loadAssetLibrary() {
  const params = new URLSearchParams();
  const projectId = document.getElementById("libraryProjectFilter")?.value || "";
  const status = document.getElementById("libraryStatusFilter")?.value || "";
  const prompt = document.getElementById("libraryPromptFilter")?.value || "";
  if (projectId) params.set("project_id", projectId);
  if (status) params.set("status", status);
  if (prompt) params.set("prompt", prompt);
  const suffix = params.toString() ? `?${params}` : "";
  const payload = await assetLabFetch(`/assets${suffix}`);
  assetLabState.assets = payload.assets || [];
  renderAssetGrid();
}

function assetImageUrl(asset) {
  if (asset.relative_thumbnail_path) {
    return `/asset-lab-files/${asset.relative_thumbnail_path}`;
  }
  return `/asset-lab-files/${asset.relative_file_path}`;
}

function renderAssetGrid() {
  const grid = document.getElementById("assetGrid");
  if (!grid) return;
  if (!assetLabState.assets.length) {
    grid.innerHTML = '<p class="subtle">No assets match the current filters.</p>';
    return;
  }
  grid.innerHTML = assetLabState.assets.map((asset) => `
    <article class="asset-card" data-asset-id="${asset.id}">
      <img src="${assetImageUrl(asset)}" alt="">
      <div class="asset-card-body">
        <strong>${escapeHtml(asset.asset_type)} / ${escapeHtml(asset.component_type || "asset")}</strong>
        <span>${asset.width} x ${asset.height} · ${escapeHtml(asset.provider)}</span>
        <span>${escapeHtml(asset.status)}</span>
        <p>${escapeHtml(asset.prompt || "")}</p>
      </div>
    </article>
  `).join("");
}
```

Wire `libraryRefreshButton` to `loadAssetLibrary`.

- [ ] **Step 3: Add safe file serving to `server.py`**

Add a helper:

```python
def resolve_asset_lab_file(relative_path: str) -> Path:
    config = load_config()
    root = config.workspace_root.resolve()
    target = (root / relative_path).resolve()
    if not is_within_root(target, root):
        raise ValueError("asset file path is outside workspace")
    return target
```

Inside `AppHandler.do_GET`, add:

```python
if parsed.path.startswith("/asset-lab-files/"):
    relative = parsed.path.removeprefix("/asset-lab-files/")
    path = resolve_asset_lab_file(unquote(relative))
    self.serve_work_file(path)
    return
```

If `serve_work_file` enforces `WORK_DIR`, create a separate `serve_static_file(path)` helper that verifies existence and sends image content.

- [ ] **Step 4: Add CSS for grid**

In `app/styles.css`, add:

```css
.library-layout {
  display: grid;
  grid-template-columns: minmax(180px, 240px) 1fr;
  gap: 16px;
}

.library-filters {
  display: grid;
  gap: 12px;
  align-content: start;
}

.asset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.asset-card {
  border: 1px solid #d7dbe3;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
}

.asset-card img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: contain;
  background-color: #f5f6f8;
}

.asset-card-body {
  display: grid;
  gap: 4px;
  padding: 10px;
}

.asset-card-body p {
  margin: 0;
  color: #5a667a;
  font-size: 12px;
}
```

- [ ] **Step 5: Verify filters**

Run server and open Library tab. Create at least one asset row through tests or manual DB insertion. Expected:
- Library displays prior assets from SQLite.
- Prompt filter narrows results.
- Status filter narrows results.

- [ ] **Step 6: Commit**

```powershell
git add server.py app/index.html app/app.js app/styles.css
git commit -m "feat: add asset library browser"
```

### Task 8: Selection and Rejection Actions

**Files:**
- Modify: `asset_lab/repository.py`
- Modify: `server.py`
- Modify: `app/app.js`
- Modify: `app/index.html`
- Create: `tests/asset_lab/test_asset_status.py`

- [ ] **Step 1: Add failing status tests**

Create `tests/asset_lab/test_asset_status.py`:

```python
from asset_lab.config import AssetLabConfig
from asset_lab.db import connect_db, migrate
from asset_lab.repository import AssetRepository


def test_mark_asset_selected_sets_timestamp(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()
    conn = connect_db(config)
    migrate(conn)
    repo = AssetRepository(conn)

    asset = repo.create_asset(
        project_id=None,
        asset_type="icon",
        component_type="item_icon",
        provider="manual",
        file_path="D:/library/images/candidates/a.png",
        relative_file_path="images/candidates/a.png",
        width=64,
        height=64,
        has_alpha=True,
        is_transparent_bg=True,
        prompt="test",
    )

    selected = repo.mark_asset_status(asset["id"], "selected")

    assert selected["status"] == "selected"
    assert selected["selected_at"]
```

- [ ] **Step 2: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_asset_status.py -v
```

Expected: PASS if Task 2 implementation is complete.

- [ ] **Step 3: Add select/reject HTTP helpers**

In `server.py`, add:

```python
def mark_asset_payload(asset_id: int, status: str) -> dict:
    config, conn, repo = asset_lab_repo()
    try:
        return repo.mark_asset_status(asset_id, status)
    finally:
        conn.close()
```

Inside `AppHandler.do_POST`, add route matching for:

```python
match = re.fullmatch(r"/api/asset-lab/assets/(\d+)/(select|reject)", parsed.path)
if match:
    asset_id = int(match.group(1))
    action = match.group(2)
    self.send_json(mark_asset_payload(asset_id, "selected" if action == "select" else "rejected"))
    return
```

- [ ] **Step 4: Add UI buttons**

In `renderAssetGrid`, add buttons:

```javascript
<div class="asset-card-actions">
  <button type="button" data-asset-select="${asset.id}">Select</button>
  <button type="button" data-asset-reject="${asset.id}">Reject</button>
</div>
```

Add delegated click handler:

```javascript
document.addEventListener("click", async (event) => {
  const selectButton = event.target.closest("[data-asset-select]");
  const rejectButton = event.target.closest("[data-asset-reject]");
  if (selectButton) {
    await assetLabFetch(`/assets/${selectButton.dataset.assetSelect}/select`, { method: "POST", body: "{}" });
    await loadAssetLibrary();
  }
  if (rejectButton) {
    await assetLabFetch(`/assets/${rejectButton.dataset.assetReject}/reject`, { method: "POST", body: "{}" });
    await loadAssetLibrary();
  }
});
```

- [ ] **Step 5: Verify selection**

Run server. In Library, click Select on a candidate asset.
Expected:
- Card status changes to selected after refresh.
- SQLite row has `status='selected'` and non-empty `selected_at`.

- [ ] **Step 6: Commit**

```powershell
git add asset_lab/repository.py server.py app/app.js app/index.html tests/asset_lab/test_asset_status.py
git commit -m "feat: add asset selection and rejection"
```

### Task 9: Real Provider Calls

**Files:**
- Modify: `asset_lab/providers/openai_images.py`
- Modify: `asset_lab/providers/toioto.py`
- Modify: `asset_lab/providers/base.py`
- Modify: `server.py`
- Create: `tests/asset_lab/test_generate_flow.py`

- [ ] **Step 1: Add generation flow test with fake provider**

Create `tests/asset_lab/test_generate_flow.py`:

```python
from pathlib import Path

from PIL import Image

from asset_lab.config import AssetLabConfig
from asset_lab.db import connect_db, migrate
from asset_lab.images import save_candidate_image
from asset_lab.repository import AssetRepository


def test_generation_result_is_saved_as_candidate(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()
    conn = connect_db(config)
    migrate(conn)
    repo = AssetRepository(conn)

    generated = tmp_path / "generated.png"
    Image.new("RGBA", (32, 32), (0, 0, 255, 0)).save(generated)
    saved = save_candidate_image(config, generated, "openai", "icon")
    asset = repo.create_asset(
        project_id=None,
        asset_type="icon",
        component_type="item_icon",
        provider="openai",
        file_path=str(saved.file_path),
        relative_file_path=saved.relative_file_path,
        thumbnail_path=str(saved.thumbnail_path),
        relative_thumbnail_path=saved.relative_thumbnail_path,
        width=saved.info.width,
        height=saved.info.height,
        has_alpha=saved.info.has_alpha,
        is_transparent_bg=saved.info.is_transparent_bg,
        background_color=saved.info.background_color,
        prompt="blue icon",
    )

    assert asset["status"] == "candidate"
    assert asset["provider"] == "openai"
    assert asset["width"] == 32
```

- [ ] **Step 2: Run test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab\test_generate_flow.py -v
```

Expected: PASS after prior tasks.

- [ ] **Step 3: Implement OpenAI provider**

Use the official OpenAI Python package if available; otherwise add it to a new optional requirements file. The provider should:
- Read `OPENAI_API_KEY`.
- Combine `style_text` and `prompt` into one prompt string.
- Request image output.
- Decode returned image bytes/base64 into files under the provided output directory.
- Return `GenerationResult`.

Minimum implementation signature:

```python
def generate(self, request: GenerationRequest, output_dir: Path) -> GenerationResult:
    ...
```

The implementation must never log API keys.

- [ ] **Step 4: Implement ToioTo provider**

Implement based on current ToioTo API documentation available to the project owner. The provider should:
- Read `TOIOTO_API_KEY`.
- Combine style context and prompt.
- Respect width, height, count, and transparent background where the API supports it.
- Save generated images into the provided output directory.
- Return `GenerationResult`.

The implementation must never log API keys.

- [ ] **Step 5: Wire `/api/asset-lab/generate`**

In `server.py`, implement:
- Read request JSON.
- Create a `generation_jobs` row with status `running`.
- Call selected provider.
- Save each provider output as a candidate image.
- Create one `assets` row per image.
- Mark job `completed` or `failed`.
- Return job and asset records.

Expected response shape:

```json
{
  "job": { "id": 1, "status": "completed" },
  "assets": [
    { "id": 1, "status": "candidate", "provider": "openai" }
  ]
}
```

- [ ] **Step 6: Manual provider verification**

With `OPENAI_API_KEY` set, run:

```powershell
.\.venv\Scripts\python.exe server.py --serve --host 127.0.0.1 --port 8894
```

Use the Generate form to create one 1024x1024 transparent candidate icon.
Expected:
- A new image appears in the Library.
- SQLite records provider as `openai`.
- Prompt and style snapshot are stored.
- Image file is under the configured external workspace, not inside the repository.

With `TOIOTO_API_KEY` set, repeat for ToioTo.

- [ ] **Step 7: Commit**

```powershell
git add asset_lab/providers server.py tests/asset_lab/test_generate_flow.py requirements.txt
git commit -m "feat: add image generation providers"
```

### Task 10: Settings, Workspace Path, and Documentation

**Files:**
- Modify: `README.md`
- Modify: `USAGE.zh-CN.md`
- Modify: `USAGE.md`
- Modify: `app/index.html`
- Modify: `app/app.js`
- Modify: `app/styles.css`

- [ ] **Step 1: Add Settings UI requirements**

In `app/index.html`, add a Settings section:

```html
<section id="assetLabSettings" class="asset-lab-panel" hidden>
  <div class="panel-head">
    <div>
      <h2>Settings</h2>
      <p>Review local workspace and provider configuration.</p>
    </div>
  </div>
  <dl class="settings-list">
    <dt>Workspace</dt>
    <dd id="settingsWorkspacePath"></dd>
    <dt>OpenAI</dt>
    <dd id="settingsOpenAiStatus"></dd>
    <dt>ToioTo</dt>
    <dd id="settingsToioToStatus"></dd>
  </dl>
</section>
```

- [ ] **Step 2: Render settings**

In `app/app.js`, add:

```javascript
function renderAssetLabSettings() {
  if (!assetLabState.status) return;
  const workspace = document.getElementById("settingsWorkspacePath");
  const openai = document.getElementById("settingsOpenAiStatus");
  const toioto = document.getElementById("settingsToioToStatus");
  if (workspace) workspace.textContent = assetLabState.status.workspace_root;
  if (openai) openai.textContent = assetLabState.status.providers.openai?.message || "";
  if (toioto) toioto.textContent = assetLabState.status.providers.toioto?.message || "";
}
```

Call `renderAssetLabSettings()` after `renderProviderStatus()`.

- [ ] **Step 3: Document local-only storage**

Update `README.md`, `USAGE.md`, and `USAGE.zh-CN.md` with:

```text
Asset Lab stores generated images, thumbnails, and asset_lab.sqlite in the configured local workspace. By default this is %LOCALAPPDATA%\SpriteVideoLab\workspace on Windows. These files are not stored in this source repository unless you explicitly set the workspace path inside the repository.

API keys are read from environment variables only:
- OPENAI_API_KEY
- TOIOTO_API_KEY

The app has one global library. Users create project categories manually from the Projects view.
```

- [ ] **Step 4: Verify documentation matches behavior**

Run:

```powershell
Select-String -Path README.md,USAGE.md,USAGE.zh-CN.md -Pattern "asset_lab.sqlite|OPENAI_API_KEY|TOIOTO_API_KEY|workspace"
```

Expected: each file mentions workspace, keys, and SQLite history.

- [ ] **Step 5: Commit**

```powershell
git add README.md USAGE.md USAGE.zh-CN.md app/index.html app/app.js app/styles.css
git commit -m "docs: document local asset lab workflow"
```

## Testing Strategy

Run focused tests after each task:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\asset_lab -v
```

Run syntax checks before manual UI verification:

```powershell
.\.venv\Scripts\python.exe -m py_compile server.py
```

Run manual server smoke test:

```powershell
.\.venv\Scripts\python.exe server.py --serve --host 127.0.0.1 --port 8894
```

Open:

```text
http://127.0.0.1:8894/
```

Manual acceptance checklist:

- Status endpoint creates the external workspace.
- Provider status shows OpenAI and ToioTo configuration state without exposing keys.
- Users can create project categories manually.
- Generated/imported candidates show up after app reload.
- Library filters work by project, status, prompt, type, and provider.
- Asset detail shows dimensions, background color, alpha/transparency, prompt, provider, and local paths.
- Selecting/rejecting assets updates SQLite without losing prompt metadata.
- Generated files are not written into the source repository unless the user explicitly configures the workspace there.

## Risks and Guardrails

- Do not store image bytes in SQLite. Store image files locally and keep paths plus metadata in the database.
- Do not log or persist API keys.
- Do not hard-code any game/project/style preset.
- Do not auto-detect projects from the current working directory.
- Keep generated images outside the repository by default.
- Keep existing video-to-sprite functionality working while adding Asset Lab features.
- Keep provider calls behind a small interface so ToioTo/OpenAI can evolve independently.

## Self-Review

Spec coverage:

- Global one-library model: covered by workspace layout and schema.
- Manual project categories: covered by `projects` table and project UI/API tasks.
- SQLite metadata: covered by Tasks 1 and 2.
- Local external asset storage: covered by workspace layout, `AssetLabConfig`, image helpers, and docs.
- ToioTo/OpenAI provider choice: covered by provider interface and Generate UI.
- Prompt/style/provider/size/background/transparency records: covered by schema and image inspection.
- Reloadable history: covered by Library API and UI.
- Generic tool with no fixed style/project: covered by product scope and guardrails.

Placeholder scan:

- Provider implementation requires real API details for ToioTo and OpenAI model choices. Task 9 intentionally names exact interface, storage behavior, response shape, and manual verification, but provider HTTP payload details must be filled from official provider documentation at implementation time.

Type consistency:

- `AssetLabConfig`, `AssetRepository`, `GenerationRequest`, and `GenerationResult` names are consistent across tasks.

---

Plan complete and saved to `docs/superpowers/plans/2026-06-06-local-ai-asset-library.md`. Two execution options:

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
