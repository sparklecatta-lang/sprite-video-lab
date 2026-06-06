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
