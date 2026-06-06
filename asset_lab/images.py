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


def save_candidate_image(
    config: AssetLabConfig,
    source: Path,
    provider: str,
    asset_type: str,
) -> SavedImage:
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
