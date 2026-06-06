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
        row = self.conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"project not found: {project_id}")
        return row_to_dict(row)

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        archive_clause = "" if include_archived else "WHERE p.is_archived = 0"
        rows = self.conn.execute(
            f"""
            SELECT
              p.*,
              COUNT(a.id) AS asset_count,
              MAX(a.created_at) AS latest_asset_at
            FROM projects p
            LEFT JOIN assets a ON a.project_id = p.id
            {archive_clause}
            GROUP BY p.id
            ORDER BY p.name
            """
        ).fetchall()
        projects = [row_to_dict(row) for row in rows]
        activity_by_project = self.project_activity_counts([project["id"] for project in projects])
        for project in projects:
            project["activity"] = activity_by_project.get(project["id"], [])
        return projects

    def project_activity_counts(self, project_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        if not project_ids:
            return {}
        placeholders = ",".join("?" for _ in project_ids)
        rows = self.conn.execute(
            f"""
            SELECT
              project_id,
              substr(created_at, 1, 10) AS day,
              COUNT(*) AS count,
              MIN(created_at) AS first_asset_at,
              MAX(created_at) AS latest_asset_at
            FROM assets
            WHERE project_id IN ({placeholders})
            GROUP BY project_id, day
            ORDER BY day
            """,
            project_ids,
        ).fetchall()
        activity: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            project_id = int(row["project_id"])
            activity.setdefault(project_id, []).append(
                {
                    "date": row["day"],
                    "count": int(row["count"]),
                    "first_asset_at": row["first_asset_at"],
                    "latest_asset_at": row["latest_asset_at"],
                }
            )
        return activity

    def create_style(
        self,
        name: str,
        body: str,
        description: str = "",
    ) -> dict[str, Any]:
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
        row = self.conn.execute(
            "SELECT * FROM styles WHERE id = ?",
            (style_id,),
        ).fetchone()
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
        row = self.conn.execute(
            "SELECT * FROM generation_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"generation job not found: {job_id}")
        return row_to_dict(row)

    def update_generation_job_status(
        self,
        job_id: int,
        status: str,
        error_message: str = "",
    ) -> dict[str, Any]:
        completed_at = utc_now() if status in {"completed", "failed"} else None
        self.conn.execute(
            """
            UPDATE generation_jobs
            SET status = ?,
                error_message = ?,
                completed_at = COALESCE(?, completed_at)
            WHERE id = ?
            """,
            (status, error_message, completed_at, job_id),
        )
        self.conn.commit()
        return self.get_generation_job(job_id)

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
        row = self.conn.execute(
            "SELECT * FROM assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
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
