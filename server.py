from __future__ import annotations

import argparse
import cgi
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime
from fractions import Fraction
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image, ImageChops, ImageFilter

from asset_lab.config import AssetLabConfig, load_config
from asset_lab.db import connect_db, migrate
from asset_lab.images import save_candidate_image
from asset_lab.providers import get_provider, list_providers
from asset_lab.providers.base import GenerationRequest
from asset_lab.repository import AssetRepository


ROOT_DIR = Path(__file__).resolve().parent
APP_DIR = ROOT_DIR / "app"
TOOL_ENV_PATH = ROOT_DIR / ".env"
WORK_DIR = ROOT_DIR / "work"
UPLOADS_DIR = WORK_DIR / "uploads"
JOBS_DIR = WORK_DIR / "jobs"
EXPORTS_DIR = WORK_DIR / "exports"
PREVIEWS_DIR = WORK_DIR / "previews"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8894
DEFAULT_FFMPEG_FALLBACK_ROOT = Path(r"I:\FF\Flowframes\FlowframesData\pkgs\av")
HOST_ENV = "SPRITE_VIDEO_LAB_HOST"
PORT_ENV = "SPRITE_VIDEO_LAB_PORT"
FFMPEG_DIR_ENV = "SPRITE_VIDEO_LAB_FFMPEG_DIR"
AI_MODEL_CACHE_ENV = "SPRITE_VIDEO_LAB_AI_MODEL_CACHE"
CORRIDORKEY_ROOT_ENV = "SPRITE_VIDEO_LAB_CORRIDORKEY_ROOT"
LANCZOS = Image.Resampling.LANCZOS
APP_VERSION_POLL_MS = 1200
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ANIMATION_FRAME_EXTENSIONS = IMAGE_EXTENSIONS
CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}
MOJIBAKE_REPLACEMENTS = {
    "\u677b\ufe40\u75c2": "\u8f66\u5b9d",
}
FFMPEG_ACCEL_ENV = "SPRITE_VIDEO_LAB_FFMPEG_ACCEL"
FFMPEG_ACCEL_PRIORITY = ("cuda", "qsv", "d3d11va", "dxva2")
FFMPEG_ACCEL_ALIASES = {
    "": "auto",
    "auto": "auto",
    "default": "auto",
    "gpu": "auto",
    "cpu": "cpu",
    "off": "cpu",
    "none": "cpu",
    "disabled": "cpu",
    "cuda": "cuda",
    "nvdec": "cuda",
    "qsv": "qsv",
    "d3d11va": "d3d11va",
    "dxva2": "dxva2",
}
AI_MATTE_MODEL_REPOS = {
    "birefnet-hr-matting": "ZhengPeng7/BiRefNet_HR-matting",
    "birefnet-lite-2k": "ZhengPeng7/BiRefNet_lite-2K",
    "birefnet-general": "ZhengPeng7/BiRefNet",
}
AI_MATTE_MODEL_LABELS = {
    "birefnet-hr-matting": "BiRefNet HR-matting",
    "birefnet-lite-2k": "BiRefNet lite-2K",
    "birefnet-general": "BiRefNet general",
}
AI_MATTE_MODES = {
    "none",
    "chroma",
    "birefnet",
    "corridorkey",
    "luma",
    "birefnet_corridorkey",
    "birefnet_corridorkey_key",
    "birefnet_luma",
    "birefnet_luma_key",
    "birefnet_luma_corridorkey",
}
AI_MATTE_DEVICE_ALIASES = {
    "": "auto",
    "auto": "auto",
    "gpu": "cuda",
    "cuda": "cuda",
    "cuda:0": "cuda",
    "cpu": "cpu",
}
DEFAULT_AI_MATTE_MODEL = "birefnet-hr-matting"
DEFAULT_AI_MATTE_RESOLUTION = 1024
AI_MATTE_MIN_RESOLUTION = 256
AI_MATTE_MAX_RESOLUTION = 2560
AI_MATTE_RESOLUTION_MULTIPLE = 32
CORRIDORKEY_REPO_URL = "https://github.com/nikopueringer/CorridorKey"
CORRIDORKEY_IMG_SIZE = 2048
CORRIDORKEY_GPU_DESPECKLE_PIXEL_LIMIT = 2**24
CORRIDORKEY_SCREEN_COLORS = {"auto", "green", "blue"}
CANVAS_MODES = {"auto", "square_bottom", "square_center"}

_FFMPEG_HWACCELS_CACHE: set[str] | None = None
_BIREFNET_MODEL_CACHE: dict[tuple[str, str], object] = {}
_CORRIDORKEY_ENGINE_CACHE: dict[tuple[str, str], object] = {}


def ensure_runtime_dirs() -> None:
    for directory in (APP_DIR, WORK_DIR, UPLOADS_DIR, JOBS_DIR, EXPORTS_DIR, PREVIEWS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def configured_host(cli_host: str | None = None) -> str:
    value = str(cli_host or os.environ.get(HOST_ENV, DEFAULT_HOST)).strip()
    return value or DEFAULT_HOST


def configured_port(cli_port: int | None = None) -> int:
    if cli_port is not None:
        return cli_port
    raw = str(os.environ.get(PORT_ENV, DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def ffmpeg_fallback_root() -> Path | None:
    configured = str(os.environ.get(FFMPEG_DIR_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser()
    if DEFAULT_FFMPEG_FALLBACK_ROOT.exists():
        return DEFAULT_FFMPEG_FALLBACK_ROOT
    return None


def default_ai_model_cache_dir() -> Path:
    configured = str(os.environ.get(AI_MODEL_CACHE_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser()
    e_drive = Path("E:/")
    if e_drive.exists():
        return e_drive / "sprite-video-lab-models" / "huggingface"
    return WORK_DIR / "models" / "huggingface"


def default_corridorkey_root() -> Path:
    configured = str(os.environ.get(CORRIDORKEY_ROOT_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser()
    e_drive = Path("E:/")
    if e_drive.exists():
        return e_drive / "sprite-video-lab-models" / "CorridorKey"
    return WORK_DIR / "models" / "CorridorKey"


def configure_ai_model_cache() -> Path:
    cache_dir = default_ai_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    hub_cache = cache_dir / "hub"
    hub_cache.mkdir(parents=True, exist_ok=True)
    modules_cache = cache_dir / "modules"
    modules_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hub_cache))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(cache_dir / "transformers"))
    os.environ.setdefault("HF_MODULES_CACHE", str(modules_cache))
    os.environ.setdefault("HF_XET_CACHE", str(cache_dir / "xet"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return cache_dir


def clean_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(name).name).strip(".-")
    return cleaned or "video"


def repair_mojibake_text(value: str) -> str:
    repaired = value
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(bad, good)
    return repaired


def repair_mojibake_path(path: Path) -> Path:
    return Path(repair_mojibake_text(str(path)))


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return cleaned or "item"


def json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def timestamped_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def parse_hex_color(raw: str) -> tuple[int, int, int]:
    value = raw.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid color: {raw}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def safe_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_ai_resolution(value) -> int:
    resolution = safe_int(value, DEFAULT_AI_MATTE_RESOLUTION)
    resolution = max(AI_MATTE_MIN_RESOLUTION, min(AI_MATTE_MAX_RESOLUTION, resolution))
    half_step = AI_MATTE_RESOLUTION_MULTIPLE // 2
    aligned = ((resolution + half_step) // AI_MATTE_RESOLUTION_MULTIPLE) * AI_MATTE_RESOLUTION_MULTIPLE
    return max(AI_MATTE_MIN_RESOLUTION, min(AI_MATTE_MAX_RESOLUTION, aligned))


def clamp_float(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))


def normalize_matte_mode(raw: str, chroma_enabled: bool) -> str:
    raw_value = str(raw or "").strip().lower()
    compact_value = re.sub(r"\s+", "", raw_value)
    dash_aliases = {
        "birefnet-luma": "birefnet_luma_key",
        "birefnet-luma-key": "birefnet_luma_key",
        "birefnet-corridor": "birefnet_corridorkey_key",
        "birefnet-corridor-key": "birefnet_corridorkey_key",
        "birefnet-corridorkey": "birefnet_corridorkey_key",
        "birefnet-corridorkey-key": "birefnet_corridorkey_key",
    }
    if raw_value in dash_aliases or compact_value in dash_aliases:
        return dash_aliases.get(raw_value, dash_aliases[compact_value])
    value = raw_value.replace("-", "_")
    aliases = {
        "": "chroma" if chroma_enabled else "none",
        "off": "none",
        "disabled": "none",
        "no": "none",
        "key": "chroma",
        "color": "chroma",
        "green": "chroma",
        "green_screen": "chroma",
        "greenscreen": "chroma",
        "green_key": "chroma",
        "chroma_key": "chroma",
        "ai": "birefnet",
        "birefnet": "birefnet",
        "corridor": "corridorkey",
        "corridor_key": "corridorkey",
        "corridorkey": "corridorkey",
        "luma": "luma",
        "luma_key": "luma",
        "luminance": "luma",
        "birefnet_corridor": "birefnet_corridorkey",
        "birefnet_corridor_key": "birefnet_corridorkey",
        "birefnet_corridorkey": "birefnet_corridorkey",
        "birefnet+corridor": "birefnet_corridorkey",
        "birefnet+corridorkey": "birefnet_corridorkey",
        "birefnet_corridorkey_key": "birefnet_corridorkey_key",
        "birefnet_corridor_keyer": "birefnet_corridorkey_key",
        "birefnet_corridorkey_keyer": "birefnet_corridorkey_key",
        "birefnet_luma": "birefnet_luma",
        "birefnet+luma": "birefnet_luma",
        "birefnet_luma_key": "birefnet_luma_key",
        "birefnet_luma_keyer": "birefnet_luma_key",
        "birefnet_luma_corridorkey": "birefnet_luma_corridorkey",
        "birefnet_luma_corridor": "birefnet_luma_corridorkey",
        "birefnet_luma_corridor_key": "birefnet_luma_corridorkey",
        "birefnet_corridorkey_luma": "birefnet_luma_corridorkey",
        "birefnet_corridor_luma": "birefnet_luma_corridorkey",
        "birefnet+luma+corridor": "birefnet_luma_corridorkey",
        "birefnet+luma+corridorkey": "birefnet_luma_corridorkey",
        "birefnet+corridor+luma": "birefnet_luma_corridorkey",
        "birefnet+corridorkey+luma": "birefnet_luma_corridorkey",
        "ai_luma": "birefnet_luma",
        "ai_glow": "birefnet_luma",
    }
    mode = aliases.get(value, value)
    return mode if mode in AI_MATTE_MODES else ("chroma" if chroma_enabled else "none")


def normalize_ai_model_key(raw: str) -> str:
    value = str(raw or DEFAULT_AI_MATTE_MODEL).strip().lower()
    aliases = {
        "hr": "birefnet-hr-matting",
        "hr-matting": "birefnet-hr-matting",
        "matting": "birefnet-hr-matting",
        "lite": "birefnet-lite-2k",
        "lite-2k": "birefnet-lite-2k",
        "2k": "birefnet-lite-2k",
        "general": "birefnet-general",
        "default": "birefnet-general",
    }
    value = aliases.get(value, value)
    return value if value in AI_MATTE_MODEL_REPOS else DEFAULT_AI_MATTE_MODEL


def normalize_ai_device(raw: str) -> str:
    value = str(raw or "auto").strip().lower()
    return AI_MATTE_DEVICE_ALIASES.get(value, "auto")


def normalize_corridorkey_screen(raw: str) -> str:
    value = str(raw or "auto").strip().lower()
    return value if value in CORRIDORKEY_SCREEN_COLORS else "auto"


def normalize_canvas_mode(raw: str) -> str:
    value = str(raw or "auto").strip().lower().replace("-", "_")
    aliases = {
        "": "auto",
        "auto_width": "auto",
        "auto_center": "auto",
        "rect": "auto",
        "rectangle": "auto",
        "center": "square_center",
        "square": "square_bottom",
        "bottom": "square_bottom",
    }
    value = aliases.get(value, value)
    return value if value in CANVAS_MODES else "auto"


def resolve_corridorkey_screen(raw: str, key_rgb: tuple[int, int, int]) -> str:
    normalized = normalize_corridorkey_screen(raw)
    if normalized != "auto":
        return normalized
    return "blue" if key_rgb[2] > key_rgb[1] and key_rgb[2] >= key_rgb[0] else "green"


def resolve_ffmpeg_binary(name: str) -> str:
    direct = shutil.which(name)
    if direct:
        return direct
    fallback_root = ffmpeg_fallback_root()
    if fallback_root is not None:
        candidate = fallback_root / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(f"could not resolve {name}")


def run_process(args: list[str]) -> str:
    completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"command failed: {' '.join(args)}")
    return completed.stdout


def configured_ffmpeg_accel_mode() -> str:
    raw = str(os.environ.get(FFMPEG_ACCEL_ENV, "auto") or "auto").strip().lower()
    return FFMPEG_ACCEL_ALIASES.get(raw, "auto")


def available_ffmpeg_hwaccels() -> set[str]:
    global _FFMPEG_HWACCELS_CACHE
    if _FFMPEG_HWACCELS_CACHE is not None:
        return _FFMPEG_HWACCELS_CACHE

    ffmpeg = resolve_ffmpeg_binary("ffmpeg")
    try:
        output = run_process([ffmpeg, "-hide_banner", "-hwaccels"])
    except Exception:
        _FFMPEG_HWACCELS_CACHE = set()
        return _FFMPEG_HWACCELS_CACHE

    available: set[str] = set()
    for line in output.splitlines():
        value = line.strip().lower()
        if not value or value.endswith(":"):
            continue
        if re.fullmatch(r"[a-z0-9_]+", value):
            available.add(value)
    _FFMPEG_HWACCELS_CACHE = available
    return _FFMPEG_HWACCELS_CACHE


def preferred_ffmpeg_hwaccel() -> tuple[str, str | None]:
    requested = configured_ffmpeg_accel_mode()
    if requested == "cpu":
        return requested, None

    available = available_ffmpeg_hwaccels()
    if requested == "auto":
        for candidate in FFMPEG_ACCEL_PRIORITY:
            if candidate in available:
                return requested, candidate
        return requested, None

    if requested in available:
        return requested, requested
    return requested, None


def ffmpeg_accel_label(mode: str) -> str:
    return "CPU" if mode == "cpu" else f"GPU ({mode})"


def ffmpeg_accel_payload(
    requested_mode: str,
    selected_mode: str | None,
    used_mode: str,
    fallback_reason: str | None = None,
) -> dict:
    return {
        "requested_mode": requested_mode,
        "selected_mode": selected_mode,
        "used_mode": used_mode,
        "used_label": ffmpeg_accel_label(used_mode),
        "fallback_to_cpu": bool(selected_mode and used_mode == "cpu"),
        "fallback_reason": fallback_reason or "",
    }


def static_image_payload() -> dict:
    return {
        "requested_mode": "image",
        "selected_mode": "",
        "used_mode": "image",
        "used_label": "Static image",
        "fallback_to_cpu": False,
        "fallback_reason": "",
    }


def custom_animation_payload() -> dict:
    return {
        "requested_mode": "animation",
        "selected_mode": "",
        "used_mode": "animation",
        "used_label": "Custom animation frames",
        "fallback_to_cpu": False,
        "fallback_reason": "",
    }


def run_ffmpeg_with_auto_accel(args_builder) -> dict:
    requested_mode, selected_mode = preferred_ffmpeg_hwaccel()
    if selected_mode:
        try:
            run_process(args_builder(selected_mode))
            return ffmpeg_accel_payload(requested_mode, selected_mode, selected_mode)
        except RuntimeError as exc:
            detail = str(exc).strip()
            print(
                f"[ffmpeg] {selected_mode} decode failed, falling back to CPU: {detail}",
                file=sys.stderr,
            )
            run_process(args_builder(None))
            return ffmpeg_accel_payload(
                requested_mode,
                selected_mode,
                "cpu",
                fallback_reason=detail,
            )

    run_process(args_builder(None))
    return ffmpeg_accel_payload(requested_mode, None, "cpu")


def extract_image_frame(source_path: Path, output_path: Path) -> tuple[Path, dict]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = open_rgba_image(source_path)
    image.save(output_path)
    image.close()
    return output_path, static_image_payload()


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def open_rgba_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def watch_targets() -> list[Path]:
    targets = [ROOT_DIR / "server.py"]
    if APP_DIR.exists():
        targets.extend(path for path in APP_DIR.rglob("*") if path.is_file())
    return sorted(set(path.resolve() for path in targets))


def current_app_version() -> str:
    mtimes = [str(path.stat().st_mtime_ns) for path in watch_targets() if path.exists()]
    if not mtimes:
        return "0"
    return max(mtimes)


def watch_snapshot() -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for path in watch_targets():
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def open_path_in_file_browser(target: Path) -> None:
    resolved = target.resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(resolved))
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(resolved)], check=True)
        return
    subprocess.run(["xdg-open", str(resolved)], check=True)


def enforce_hard_alpha(image: Image.Image, cutoff: int = 128) -> Image.Image:
    rgba = image.convert("RGBA")
    hardened_pixels: list[tuple[int, int, int, int]] = []
    for r_value, g_value, b_value, alpha in rgba.getdata():
        if alpha >= cutoff:
            hardened_pixels.append((r_value, g_value, b_value, 255))
        else:
            hardened_pixels.append((0, 0, 0, 0))
    hardened = Image.new("RGBA", rgba.size)
    hardened.putdata(hardened_pixels)
    return hardened


def resize_rgba_with_premultiplied_alpha(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    red, green, blue, alpha = rgba.split()
    premultiplied_red = ImageChops.multiply(red, alpha)
    premultiplied_green = ImageChops.multiply(green, alpha)
    premultiplied_blue = ImageChops.multiply(blue, alpha)

    resized_alpha = alpha.resize(size, LANCZOS)
    resized_red = premultiplied_red.resize(size, LANCZOS)
    resized_green = premultiplied_green.resize(size, LANCZOS)
    resized_blue = premultiplied_blue.resize(size, LANCZOS)

    pixels: list[tuple[int, int, int, int]] = []
    for r_value, g_value, b_value, alpha_value in zip(
        resized_red.getdata(),
        resized_green.getdata(),
        resized_blue.getdata(),
        resized_alpha.getdata(),
    ):
        if alpha_value <= 0:
            pixels.append((0, 0, 0, 0))
            continue
        pixels.append(
            (
                min(255, int((r_value * 255 + (alpha_value // 2)) / alpha_value)),
                min(255, int((g_value * 255 + (alpha_value // 2)) / alpha_value)),
                min(255, int((b_value * 255 + (alpha_value // 2)) / alpha_value)),
                alpha_value,
            )
        )

    resized = Image.new("RGBA", size)
    resized.putdata(pixels)
    return resized


def ffprobe_json(path: Path) -> dict:
    ffprobe = resolve_ffmpeg_binary("ffprobe")
    output = run_process(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    return json.loads(output)


def ffmpeg_probe_text(path: Path) -> str:
    ffmpeg = resolve_ffmpeg_binary("ffmpeg")
    completed = subprocess.run(
        [ffmpeg, "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    output = "\n".join(part for part in (completed.stderr, completed.stdout) if part)
    if not output.strip():
        raise RuntimeError(f"ffmpeg could not read media info: {path}")
    return output


def parse_duration_text(raw: str) -> float:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", raw)
    if not match:
        return 0.0
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def parse_ffmpeg_video_info(raw: str) -> dict:
    video_line = next((line for line in raw.splitlines() if " Video: " in line), "")
    width = 0
    height = 0
    fps = 0.0
    codec = ""
    codec_match = re.search(r"Video:\s*([^,\s]+)", video_line)
    size_match = re.search(r"(?<![A-Za-z0-9])(\d{2,5})x(\d{2,5})(?![A-Za-z0-9])", video_line)
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", video_line)
    if codec_match:
        codec = codec_match.group(1)
    if size_match:
        width = safe_int(size_match.group(1), 0)
        height = safe_int(size_match.group(2), 0)
    if fps_match:
        fps = safe_float(fps_match.group(1), 0.0)
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "duration": parse_duration_text(raw),
        "codec": codec,
    }


def video_info_from_ffmpeg(path: Path) -> dict:
    return parse_ffmpeg_video_info(ffmpeg_probe_text(path))


def parse_frame_rate(raw: str) -> float:
    if not raw or raw == "0/0":
        return 0.0
    try:
        return float(Fraction(raw))
    except Exception:
        return 0.0


def video_info(path: Path) -> dict:
    try:
        payload = ffprobe_json(path)
        streams = payload.get("streams") or []
        video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
        width = safe_int(video_stream.get("width"), 0)
        height = safe_int(video_stream.get("height"), 0)
        fps = parse_frame_rate(str(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/0"))
        duration = safe_float((payload.get("format") or {}).get("duration"), 0.0)
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
            "codec": str(video_stream.get("codec_name") or ""),
        }
    except Exception:
        return video_info_from_ffmpeg(path)


def image_info(path: Path) -> dict:
    with Image.open(path) as image:
        width, height = image.size
        codec = str((image.format or path.suffix.removeprefix(".") or "image")).lower()
    return {
        "width": width,
        "height": height,
        "fps": 0.0,
        "duration": 0.0,
        "codec": codec,
    }


def content_type_extension(content_type: str | None) -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_EXTENSIONS.get(normalized, "")


def sniff_media_extension(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    with path.open("rb") as handle:
        head = handle.read(64)
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return ".mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"BM"):
        return ".bmp"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return ".webp"
    return ""


def detect_media_type(path: Path, content_type: str | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"

    content_extension = content_type_extension(content_type)
    if content_extension in VIDEO_EXTENSIONS:
        return "video"
    if content_extension in IMAGE_EXTENSIONS:
        return "image"

    sniffed_extension = sniff_media_extension(path)
    if sniffed_extension in VIDEO_EXTENSIONS:
        return "video"
    if sniffed_extension in IMAGE_EXTENSIONS:
        return "image"

    if path.exists() and path.is_file():
        try:
            with Image.open(path):
                return "image"
        except Exception:
            pass
        try:
            ffprobe_json(path)
            return "video"
        except Exception:
            pass

    detail = path.suffix or content_type or path.name
    raise ValueError(f"unsupported media type: {detail}")


def preferred_media_extension(path: Path, media_type: str, content_type: str | None = None) -> str:
    suffix = path.suffix.lower()
    allowed = VIDEO_EXTENSIONS if media_type == "video" else IMAGE_EXTENSIONS
    if suffix in allowed:
        return suffix
    content_extension = content_type_extension(content_type)
    if content_extension in allowed:
        return content_extension
    sniffed_extension = sniff_media_extension(path)
    if sniffed_extension in allowed:
        return sniffed_extension
    return ".mp4" if media_type == "video" else ".png"


def media_info(path: Path, media_type: str | None = None) -> dict:
    resolved_type = media_type or detect_media_type(path)
    payload = video_info(path) if resolved_type == "video" else image_info(path)
    payload["media_type"] = resolved_type
    return payload


def upload_dir(upload_id: str) -> Path:
    return UPLOADS_DIR / upload_id


def upload_manifest_path(upload_id: str) -> Path:
    return upload_dir(upload_id) / "manifest.json"


def load_upload_manifest(upload_id: str) -> dict:
    path = upload_manifest_path(upload_id)
    if not path.exists():
        raise FileNotFoundError(f"upload not found: {upload_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_upload_manifest(upload_id: str, payload: dict) -> None:
    path = upload_manifest_path(upload_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def source_media_entry(upload_id: str) -> tuple[Path, str]:
    manifest = load_upload_manifest(upload_id)
    path = repair_mojibake_path(Path(manifest["source_path"]))
    if not path.exists():
        raise FileNotFoundError(f"source missing: {path}")
    media_type = str(manifest.get("media_type") or detect_media_type(path))
    return path, media_type


def source_video_path(upload_id: str) -> Path:
    path, _ = source_media_entry(upload_id)
    return path


def build_upload_payload(upload_id: str, source_path: Path, display_name: str, media_type: str) -> dict:
    info = media_info(source_path, media_type)
    return {
        "upload_id": upload_id,
        "display_name": display_name,
        "media_url": f"/media/upload/{upload_id}",
        "video_url": f"/media/upload/{upload_id}",
        "source_path": str(source_path),
        "media_type": media_type,
        "video_info": info,
        "media_info": info,
    }


def register_video_from_path(source_path: Path) -> dict:
    source_path = repair_mojibake_path(source_path).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"file not found: {source_path}")
    media_type = detect_media_type(source_path)

    upload_id = timestamped_id()
    manifest = {
        "upload_id": upload_id,
        "source_path": str(source_path),
        "display_name": source_path.name,
        "media_type": media_type,
        "created_at": iso_now(),
    }
    save_upload_manifest(upload_id, manifest)
    return build_upload_payload(upload_id, source_path, source_path.name, media_type)


def register_uploaded_file(file_item) -> dict:
    filename = clean_filename(file_item.filename or "media")
    content_type = str(getattr(file_item, "type", "") or "")
    upload_id = timestamped_id()
    target_dir = upload_dir(upload_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    with target_path.open("wb") as handle:
        shutil.copyfileobj(file_item.file, handle)
    media_type = detect_media_type(target_path, content_type)
    preferred_extension = preferred_media_extension(target_path, media_type, content_type)
    if target_path.suffix.lower() not in (VIDEO_EXTENSIONS | IMAGE_EXTENSIONS):
        renamed_path = target_path.with_name(f"{target_path.name}{preferred_extension}")
        target_path.rename(renamed_path)
        target_path = renamed_path
        filename = target_path.name
    manifest = {
        "upload_id": upload_id,
        "source_path": str(target_path),
        "display_name": filename,
        "media_type": media_type,
        "created_at": iso_now(),
    }
    save_upload_manifest(upload_id, manifest)
    return build_upload_payload(upload_id, target_path, filename, media_type)


def auto_key_color(image: Image.Image) -> tuple[int, int, int]:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    sample_size = max(4, min(width, height) // 16)
    boxes = [
        (0, 0, sample_size, sample_size),
        (width - sample_size, 0, width, sample_size),
        (0, height - sample_size, sample_size, height),
        (width - sample_size, height - sample_size, width, height),
    ]
    totals = [0, 0, 0]
    count = 0
    for left, top, right, bottom in boxes:
        for y in range(top, bottom):
            for x in range(left, right):
                r_value, g_value, b_value, _ = rgba.getpixel((x, y))
                totals[0] += r_value
                totals[1] += g_value
                totals[2] += b_value
                count += 1
    if count <= 0:
        return (0, 255, 0)
    return tuple(int(value / count) for value in totals)


def chroma_key_frame(
    image: Image.Image,
    key_rgb: tuple[int, int, int],
    threshold: int,
    softness: int,
    despill_strength: float,
    halo_pixels: int,
) -> Image.Image:
    rgba = image.convert("RGBA")
    output_pixels: list[tuple[int, int, int, int]] = []
    k_r, k_g, k_b = key_rgb
    if softness <= 0:
        max_distance = max(threshold, 1)
    else:
        max_distance = threshold + softness

    for r_value, g_value, b_value, _ in rgba.getdata():
        dist = math.sqrt(
            (r_value - k_r) ** 2
            + (g_value - k_g) ** 2
            + (b_value - k_b) ** 2
        )
        if dist <= threshold:
            alpha = 0
        elif softness <= 0 or dist >= max_distance:
            alpha = 255
        else:
            alpha = int(((dist - threshold) / softness) * 255)

        max_rb = max(r_value, b_value)
        spill = max(0, g_value - max_rb)
        closeness = max(0.0, 1.0 - min(dist / max_distance, 1.0))
        reduction = int(spill * despill_strength * max(closeness, 1.0 - (alpha / 255.0)))
        output_pixels.append(
            (
                r_value,
                max(0, g_value - reduction),
                b_value,
                alpha,
            )
        )

    keyed = Image.new("RGBA", rgba.size)
    keyed.putdata(output_pixels)

    if halo_pixels > 0:
        alpha_channel = keyed.getchannel("A")
        filter_size = (halo_pixels * 2) + 1
        eroded = alpha_channel.filter(ImageFilter.MinFilter(filter_size))
        keyed.putalpha(eroded)

    return keyed


def import_ai_matte_dependencies():
    configure_ai_model_cache()
    try:
        import torch
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "AI matting dependency")
        raise RuntimeError(
            f"{missing_name} is not installed. Run: python -m pip install -r requirements-ai.txt"
        ) from exc
    return torch, transforms, AutoModelForImageSegmentation


def resolve_ai_runtime_device(torch_module, requested_device: str) -> str:
    requested = normalize_ai_device(requested_device)
    cuda_available = bool(torch_module.cuda.is_available())
    if requested == "cuda" and not cuda_available:
        raise RuntimeError("CUDA was requested for BiRefNet, but torch cannot see an NVIDIA GPU.")
    if requested == "cuda":
        return "cuda"
    if requested == "cpu":
        return "cpu"
    return "cuda" if cuda_available else "cpu"


def load_birefnet_model(model_key: str, requested_device: str):
    torch_module, _transforms, auto_model = import_ai_matte_dependencies()
    normalized_model_key = normalize_ai_model_key(model_key)
    repo_id = AI_MATTE_MODEL_REPOS[normalized_model_key]
    device = resolve_ai_runtime_device(torch_module, requested_device)
    cache_key = (repo_id, device)
    if cache_key in _BIREFNET_MODEL_CACHE:
        return _BIREFNET_MODEL_CACHE[cache_key], device, normalized_model_key, repo_id

    if hasattr(torch_module, "set_float32_matmul_precision"):
        try:
            torch_module.set_float32_matmul_precision("high")
        except Exception:
            pass

    cache_dir = configure_ai_model_cache()
    model = auto_model.from_pretrained(repo_id, trust_remote_code=True, cache_dir=str(cache_dir))
    model.to(device)
    model.eval()
    _BIREFNET_MODEL_CACHE[cache_key] = model
    return model, device, normalized_model_key, repo_id


def import_corridorkey_dependencies():
    configure_ai_model_cache()
    root = default_corridorkey_root()
    module_dir = root / "CorridorKeyModule"
    if not module_dir.exists():
        raise RuntimeError(
            f"CorridorKey is not installed at {root}. Run setup_ai_runtime.bat or clone {CORRIDORKEY_REPO_URL}."
        )

    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    os.environ.setdefault("CORRIDORKEY_SKIP_COMPILE", "1")

    try:
        import importlib
        import numpy as np
        import torch
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "CorridorKey dependency")
        raise RuntimeError(
            f"{missing_name} is not installed. Run: python -m pip install -r requirements-ai.txt"
        ) from exc

    try:
        corridor_backend = importlib.import_module("CorridorKeyModule.backend")
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"CorridorKey could not be imported from {root}.") from exc

    try:
        corridor_inference = importlib.import_module("CorridorKeyModule.inference_engine")
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"CorridorKey inference engine could not be imported from {root}.") from exc

    patch_corridorkey_gpu_despeckle(corridor_inference, torch)

    checkpoint_dir = module_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    corridor_backend.CHECKPOINT_DIR = str(checkpoint_dir)
    return np, torch, corridor_backend, root


def patch_corridorkey_gpu_despeckle(corridor_inference, torch_module) -> None:
    try:
        color_utils = corridor_inference.cu
        transforms_functional = corridor_inference.TF
    except Exception:
        return
    if getattr(color_utils.clean_matte_torch, "_sprite_video_lab_safe", False):
        return

    original_clean_matte_torch = color_utils.clean_matte_torch
    functional = torch_module.nn.functional

    def safe_clean_matte_torch(alpha, area_threshold: int, dilation: int = 15, blur_size: int = 5):
        _batch, _channels, height, width = alpha.shape
        if (height * width) <= CORRIDORKEY_GPU_DESPECKLE_PIXEL_LIMIT:
            return original_clean_matte_torch(alpha, area_threshold, dilation=dilation, blur_size=blur_size)

        mask = (alpha > 0.25).to(dtype=alpha.dtype)
        if area_threshold > 0:
            opening_radius = max(1, min(4, area_threshold // 100))
            kernel_size = (opening_radius * 2) + 1
            for _ in range(2):
                mask = -functional.max_pool2d(-mask, kernel_size, stride=1, padding=opening_radius)
                mask = functional.max_pool2d(mask, kernel_size, stride=1, padding=opening_radius)
        if dilation > 0:
            repeats = max(1, dilation // 2)
            for _ in range(repeats):
                mask = functional.max_pool2d(mask, 5, stride=1, padding=2)
        if blur_size > 0:
            kernel_size = int(blur_size * 2 + 1)
            mask = transforms_functional.gaussian_blur(mask, [kernel_size, kernel_size])
        return alpha * mask

    safe_clean_matte_torch._sprite_video_lab_safe = True
    color_utils.clean_matte_torch = safe_clean_matte_torch


def load_corridorkey_engine(requested_device: str, screen_color: str):
    _np, torch_module, corridor_backend, root = import_corridorkey_dependencies()
    device = resolve_ai_runtime_device(torch_module, requested_device)
    cache_key = (device, screen_color)
    if cache_key in _CORRIDORKEY_ENGINE_CACHE:
        return _CORRIDORKEY_ENGINE_CACHE[cache_key], device, root

    engine = corridor_backend.create_engine(
        backend="torch",
        device=device,
        img_size=CORRIDORKEY_IMG_SIZE,
        screen_color=screen_color,
    )
    _CORRIDORKEY_ENGINE_CACHE[cache_key] = engine
    return engine, device, root


def linear_to_srgb_array(values):
    import numpy as np

    clipped = np.clip(values, 0.0, None)
    return np.where(clipped <= 0.0031308, clipped * 12.92, 1.055 * np.power(clipped, 1.0 / 2.4) - 0.055)


def corridorkey_processed_to_image(processed) -> Image.Image:
    import numpy as np

    alpha = np.clip(processed[..., 3:4], 0.0, 1.0)
    premul_rgb = np.clip(processed[..., :3], 0.0, None)
    straight_linear = np.zeros_like(premul_rgb)
    np.divide(premul_rgb, np.maximum(alpha, 1e-6), out=straight_linear, where=alpha > 1e-6)
    straight_srgb = linear_to_srgb_array(straight_linear)
    rgba = np.concatenate([straight_srgb, alpha], axis=-1)
    rgba_u8 = (np.clip(rgba, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return Image.fromarray(rgba_u8, "RGBA")


def corridorkey_auto_despeckle_on_gpu(image: Image.Image) -> bool:
    return True


def corridorkey_postprocess_on_gpu(device: str) -> bool:
    return str(device).startswith("cuda")


def corridorkey_process_arrays(
    engine,
    rgb,
    mask,
    screen_channel: int,
    despill_strength: float,
    post_process_on_gpu: bool,
    auto_despeckle: bool,
):
    result = engine.process_frame(
        rgb,
        mask,
        input_is_linear=False,
        fg_is_straight=True,
        despill_strength=max(0.0, min(1.0, float(despill_strength or 0.0))),
        auto_despeckle=auto_despeckle,
        despeckle_size=400,
        generate_comp=False,
        post_process_on_gpu=post_process_on_gpu,
        screen_channel=screen_channel,
    )
    return result


def corridorkey_alpha_to_image(alpha) -> Image.Image:
    import numpy as np

    alpha_array = np.asarray(alpha)
    if alpha_array.ndim == 3:
        alpha_array = alpha_array[..., 0]
    alpha_u8 = (np.clip(alpha_array, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return Image.fromarray(alpha_u8, "L")


def corridorkey_refine_frame(
    image: Image.Image,
    alpha_mask: Image.Image,
    requested_device: str,
    screen_color: str,
    despill_strength: float,
) -> tuple[Image.Image, dict]:
    import numpy as np

    engine, device, root = load_corridorkey_engine(requested_device, screen_color)
    screen_channel = 2 if screen_color == "blue" else 1
    post_process_on_gpu = corridorkey_postprocess_on_gpu(device)
    auto_despeckle = not post_process_on_gpu or corridorkey_auto_despeckle_on_gpu(image)
    uses_safe_despeckle = post_process_on_gpu and (image.size[0] * image.size[1]) > CORRIDORKEY_GPU_DESPECKLE_PIXEL_LIMIT
    rgb = np.array(image.convert("RGB"), dtype=np.uint8, copy=True)
    mask = np.array(alpha_mask.convert("L"), dtype=np.uint8, copy=True)
    result = corridorkey_process_arrays(
        engine,
        rgb,
        mask,
        screen_channel,
        despill_strength,
        post_process_on_gpu,
        auto_despeckle,
    )
    alpha = corridorkey_alpha_to_image(result["processed"][..., 3:4])
    refined = apply_alpha_mask(image, alpha)
    refined = despill_alpha_edges(refined, auto_key_color(image), despill_strength)

    info = {
        "corridorkey_enabled": True,
        "corridorkey_color_source": "original",
        "corridorkey_screen_color": screen_color,
        "corridorkey_device": device,
        "corridorkey_resolution": CORRIDORKEY_IMG_SIZE,
        "corridorkey_post_process": "gpu" if post_process_on_gpu else "cpu",
        "corridorkey_auto_despeckle": auto_despeckle,
        "corridorkey_safe_despeckle": uses_safe_despeckle,
        "corridorkey_tiled": False,
        "corridorkey_root": str(root),
    }
    return refined, info


def fit_image_to_square(image: Image.Image, size: int) -> tuple[Image.Image, tuple[int, int, int, int]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width <= 0 or height <= 0:
        raise ValueError("invalid image size for BiRefNet inference")

    scale = min(size / width, size / height)
    resized_size = (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )
    resized = rgb.resize(resized_size, LANCZOS)
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    left = (size - resized_size[0]) // 2
    top = (size - resized_size[1]) // 2
    canvas.paste(resized, (left, top))
    return canvas, (left, top, left + resized_size[0], top + resized_size[1])


def birefnet_alpha_mask(
    image: Image.Image,
    model_key: str,
    requested_device: str,
    inference_resolution: int,
) -> tuple[Image.Image, dict]:
    torch_module, transforms, _auto_model = import_ai_matte_dependencies()
    model, device, normalized_model_key, repo_id = load_birefnet_model(model_key, requested_device)
    resolution = normalize_ai_resolution(inference_resolution)
    fitted_image, fitted_box = fit_image_to_square(image, resolution)
    transform = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    input_tensor = transform(fitted_image).unsqueeze(0).to(device)
    try:
        model_dtype = next(model.parameters()).dtype
    except StopIteration:
        model_dtype = input_tensor.dtype
    if str(device).startswith("cuda") and model_dtype in {torch_module.float16, torch_module.bfloat16}:
        input_tensor = input_tensor.to(dtype=model_dtype)
    with torch_module.no_grad():
        prediction = model(input_tensor)[-1].sigmoid().to("cpu")
    mask = transforms.ToPILImage()(prediction[0].squeeze()).convert("L")
    mask = mask.crop(fitted_box).resize(image.size, LANCZOS)
    return mask, {
        "model_key": normalized_model_key,
        "model_label": AI_MATTE_MODEL_LABELS[normalized_model_key],
        "repo_id": repo_id,
        "device": device,
        "resolution": resolution,
    }


def luminance_alpha_mask(
    image: Image.Image,
    black_point: int,
    white_point: int,
    gamma: float,
    strength: float,
    key_rgb: tuple[int, int, int] | None = None,
    key_suppression: float = 0.95,
) -> Image.Image:
    black = max(0, min(254, int(black_point)))
    white = max(black + 1, min(255, int(white_point)))
    curve_gamma = max(0.05, float(gamma or 1.0))
    curve_strength = max(0.0, min(2.0, float(strength or 1.0)))
    key_strength = max(0.0, min(1.0, float(key_suppression)))
    rgb = image.convert("RGB")
    scale = white - black
    output = Image.new("L", rgb.size)
    output_pixels: list[int] = []
    for r_value, g_value, b_value in rgb.getdata():
        luma = int((0.2126 * r_value) + (0.7152 * g_value) + (0.0722 * b_value))
        normalized = clamp_float((luma - black) / scale, 0.0, 1.0)
        adjusted = normalized ** curve_gamma
        alpha = clamp_float(adjusted * curve_strength, 0.0, 1.0)
        if key_rgb is not None and key_strength > 0:
            k_r, k_g, k_b = key_rgb
            dist = math.sqrt((r_value - k_r) ** 2 + (g_value - k_g) ** 2 + (b_value - k_b) ** 2)
            closeness = 1.0 - min(dist / 180.0, 1.0)
            alpha *= 1.0 - ((closeness ** 2) * key_strength)
        output_pixels.append(round(alpha * 255))
    output.putdata(output_pixels)
    return output


def apply_alpha_mask(image: Image.Image, alpha_mask: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    mask = alpha_mask.convert("L")
    if mask.size != rgba.size:
        mask = mask.resize(rgba.size, LANCZOS)
    rgba.putalpha(mask)
    return rgba


def despill_alpha_edges(
    image: Image.Image,
    key_rgb: tuple[int, int, int],
    strength: float,
) -> Image.Image:
    normalized_strength = max(0.0, min(2.5, float(strength or 0.0)))
    if normalized_strength <= 0:
        return image

    rgba = image.convert("RGBA")
    k_r, k_g, k_b = key_rgb
    key_channels = (k_r, k_g, k_b)
    spill_channel = max(range(3), key=lambda index: key_channels[index])
    output_pixels: list[tuple[int, int, int, int]] = []
    for r_value, g_value, b_value, alpha in rgba.getdata():
        channels = [r_value, g_value, b_value]
        spill_value = channels[spill_channel]
        other_values = [value for index, value in enumerate(channels) if index != spill_channel]
        spill = max(0, spill_value - max(other_values))
        if spill <= 0:
            output_pixels.append((r_value, g_value, b_value, alpha))
            continue

        dist = math.sqrt((r_value - k_r) ** 2 + (g_value - k_g) ** 2 + (b_value - k_b) ** 2)
        key_closeness = 1.0 - min(dist / 220.0, 1.0)
        edge_factor = 1.0 - (alpha / 255.0)
        cleanup_factor = max(edge_factor, key_closeness * 0.7)
        reduction = int(spill * normalized_strength * cleanup_factor)
        channels[spill_channel] = max(0, spill_value - reduction)
        output_pixels.append((channels[0], channels[1], channels[2], alpha))

    cleaned = Image.new("RGBA", rgba.size)
    cleaned.putdata(output_pixels)
    return cleaned


def apply_matte_pipeline(
    raw_images: list[Image.Image],
    chroma_enabled: bool,
    matte_mode: str,
    key_mode: str,
    manual_key_hex: str,
    threshold: int,
    softness: int,
    despill_strength: float,
    halo_pixels: int,
    ai_model: str,
    ai_device: str,
    ai_resolution: int,
    luma_black: int,
    luma_white: int,
    luma_gamma: float,
    luma_strength: float,
    corridorkey_enabled: bool,
    corridorkey_screen: str,
) -> tuple[list[Image.Image], tuple[int, int, int], dict]:
    if not raw_images:
        raise ValueError("no frames to matte")

    mode = normalize_matte_mode(matte_mode, chroma_enabled)
    key_rgb = auto_key_color(raw_images[0])
    if key_mode == "manual":
        key_rgb = parse_hex_color(manual_key_hex)
    normalized_luma_black = max(0, min(254, int(luma_black)))
    normalized_luma_white = max(normalized_luma_black + 1, min(255, int(luma_white)))
    matte_info = {
        "mode": mode,
        "model_key": "",
        "model_label": "",
        "repo_id": "",
        "device": "",
        "resolution": 0,
        "luma_enabled": mode in {"luma", "birefnet_luma", "birefnet_luma_key", "birefnet_luma_corridorkey"},
        "luma_black": normalized_luma_black,
        "luma_white": normalized_luma_white,
        "luma_gamma": max(0.05, float(luma_gamma or 1.0)),
        "luma_strength": max(0.0, min(2.0, float(luma_strength or 1.0))),
        "despill_strength": max(0.0, min(2.5, float(despill_strength or 0.0))),
        "halo_pixels": max(0, int(halo_pixels)),
        "corridorkey_enabled": False,
        "corridorkey_screen_color": "",
        "corridorkey_device": "",
        "corridorkey_resolution": 0,
    }
    mode_uses_corridorkey = mode in {
        "corridorkey",
        "birefnet_corridorkey",
        "birefnet_corridorkey_key",
        "birefnet_luma_corridorkey",
    }
    use_corridorkey = bool((corridorkey_enabled or mode_uses_corridorkey) and mode != "none")
    resolved_corridorkey_screen = resolve_corridorkey_screen(corridorkey_screen, key_rgb)

    if mode == "none":
        return raw_images, key_rgb, matte_info

    if mode in {"chroma", "corridorkey"}:
        keyed_frames = []
        corridor_info: dict | None = None
        for raw_image in raw_images:
            chroma_frame = chroma_key_frame(
                image=raw_image,
                key_rgb=key_rgb,
                threshold=threshold,
                softness=softness,
                despill_strength=despill_strength,
                halo_pixels=halo_pixels,
            )
            if use_corridorkey:
                refined_frame, corridor_info = corridorkey_refine_frame(
                    raw_image,
                    chroma_frame.getchannel("A"),
                    ai_device,
                    resolved_corridorkey_screen,
                    matte_info["despill_strength"],
                )
                keyed_frames.append(refined_frame)
            else:
                keyed_frames.append(chroma_frame)
        if corridor_info:
            matte_info.update(corridor_info)
        return keyed_frames, key_rgb, matte_info

    if mode == "luma":
        keyed_frames: list[Image.Image] = []
        for raw_image in raw_images:
            alpha = luminance_alpha_mask(
                raw_image,
                matte_info["luma_black"],
                max(matte_info["luma_black"] + 1, matte_info["luma_white"]),
                matte_info["luma_gamma"],
                matte_info["luma_strength"],
                key_rgb=key_rgb,
            )
            if matte_info["halo_pixels"] > 0:
                filter_size = (matte_info["halo_pixels"] * 2) + 1
                alpha = alpha.filter(ImageFilter.MinFilter(filter_size))
            keyed_frame = apply_alpha_mask(raw_image, alpha)
            keyed_frame = despill_alpha_edges(keyed_frame, key_rgb, matte_info["despill_strength"])
            keyed_frames.append(keyed_frame)
        return keyed_frames, key_rgb, matte_info

    keyed_frames: list[Image.Image] = []
    ai_info: dict | None = None
    corridor_info: dict | None = None
    for raw_image in raw_images:
        ai_alpha, ai_info = birefnet_alpha_mask(raw_image, ai_model, ai_device, ai_resolution)
        if matte_info["halo_pixels"] > 0:
            filter_size = (matte_info["halo_pixels"] * 2) + 1
            ai_alpha = ai_alpha.filter(ImageFilter.MinFilter(filter_size))
        if mode in {"birefnet_luma", "birefnet_luma_key", "birefnet_luma_corridorkey"}:
            luma_alpha = luminance_alpha_mask(
                raw_image,
                matte_info["luma_black"],
                max(matte_info["luma_black"] + 1, matte_info["luma_white"]),
                matte_info["luma_gamma"],
                matte_info["luma_strength"],
                key_rgb=key_rgb,
            )
            if mode == "birefnet_luma_key":
                alpha = ImageChops.darker(ai_alpha, luma_alpha)
            else:
                alpha = ImageChops.lighter(ai_alpha, luma_alpha)
        else:
            alpha = ai_alpha
        if use_corridorkey:
            keyed_frame, corridor_info = corridorkey_refine_frame(
                raw_image,
                alpha,
                ai_device,
                resolved_corridorkey_screen,
                matte_info["despill_strength"],
            )
            if mode == "birefnet_corridorkey_key":
                refined_alpha = ImageChops.darker(ai_alpha, keyed_frame.getchannel("A"))
                keyed_frame.putalpha(refined_alpha)
        else:
            keyed_frame = apply_alpha_mask(raw_image, alpha)
            keyed_frame = despill_alpha_edges(keyed_frame, key_rgb, matte_info["despill_strength"])
        keyed_frames.append(keyed_frame)

    if ai_info:
        matte_info.update(ai_info)
    if corridor_info:
        matte_info.update(corridor_info)
    return keyed_frames, key_rgb, matte_info


def stable_resize_frames(
    keyed_frames: list[Image.Image],
    target_size: int,
    reduce_px: int,
    canvas_mode: str = "auto",
    hard_alpha: bool = False,
) -> tuple[list[Image.Image], list[tuple[int, int, int, int] | None], float, tuple[int, int]]:
    bboxes = [frame.getchannel("A").getbbox() for frame in keyed_frames]
    valid_boxes = [box for box in bboxes if box is not None]
    if not valid_boxes:
        raise RuntimeError("all frames became transparent after chroma key")

    stable_box = (
        min(box[0] for box in valid_boxes),
        min(box[1] for box in valid_boxes),
        max(box[2] for box in valid_boxes),
        max(box[3] for box in valid_boxes),
    )
    stable_width = stable_box[2] - stable_box[0]
    stable_height = stable_box[3] - stable_box[1]
    canvas_mode = normalize_canvas_mode(canvas_mode)
    canvas_height = max(8, target_size)
    margin = max(0, min(reduce_px, max(0, (canvas_height - 8) // 2)))

    if canvas_mode == "auto":
        inner_height = max(8, canvas_height - (margin * 2))
        scale = inner_height / max(stable_height, 1)
        resized_stable_size = (
            max(1, round(stable_width * scale)),
            max(1, round(stable_height * scale)),
        )
        canvas_width = max(8, resized_stable_size[0] + (margin * 2))
        paste_x = (canvas_width - resized_stable_size[0]) // 2
        paste_y = (canvas_height - resized_stable_size[1]) // 2
    else:
        inner_size = max(8, canvas_height - (margin * 2))
        scale = min(inner_size / max(stable_width, 1), inner_size / max(stable_height, 1))
        resized_stable_size = (
            max(1, round(stable_width * scale)),
            max(1, round(stable_height * scale)),
        )
        canvas_width = canvas_height
        paste_x = (canvas_width - resized_stable_size[0]) // 2
        if canvas_mode == "square_center":
            paste_y = (canvas_height - resized_stable_size[1]) // 2
        else:
            paste_y = canvas_height - margin - resized_stable_size[1]

    canvas_size = (canvas_width, canvas_height)

    rendered: list[Image.Image] = []
    for frame in keyed_frames:
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        cropped = frame.crop(stable_box)
        resized = resize_rgba_with_premultiplied_alpha(
            cropped,
            resized_stable_size,
        )
        if hard_alpha:
            resized = enforce_hard_alpha(resized)
        canvas.paste(resized, (paste_x, paste_y), resized)
        if hard_alpha:
            canvas = enforce_hard_alpha(canvas)
        rendered.append(canvas)

    return rendered, bboxes, scale, canvas_size


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def job_manifest_path(job_id: str) -> Path:
    return job_dir(job_id) / "manifest.json"


def save_job_manifest(job_id: str, payload: dict) -> None:
    path = job_manifest_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job_manifest(job_id: str) -> dict:
    path = job_manifest_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"job not found: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def extract_raw_frames(
    source_path: Path,
    raw_dir: Path,
    start_time: float,
    end_time: float,
    keep_every: int,
) -> tuple[list[Path], dict]:
    ffmpeg = resolve_ffmpeg_binary("ffmpeg")
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    def build_args(hwaccel: str | None) -> list[str]:
        args = [ffmpeg, "-y"]
        if hwaccel:
            args += ["-hwaccel", hwaccel]
        args += [
            "-ss",
            f"{start_time:.3f}",
            "-to",
            f"{end_time:.3f}",
            "-i",
            str(source_path),
        ]
        if keep_every > 1:
            args += ["-vf", f"select=not(mod(n\\,{keep_every}))"]
        args += ["-vsync", "0", str(raw_dir / "frame_%05d.png")]
        return args

    accel = run_ffmpeg_with_auto_accel(build_args)
    frames = sorted(raw_dir.glob("frame_*.png"))
    if not frames:
        raise RuntimeError("no frames extracted from the selected segment")
    return frames, accel


def extract_single_frame(source_path: Path, output_path: Path, sample_time: float) -> tuple[Path, dict]:
    ffmpeg = resolve_ffmpeg_binary("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def build_args(hwaccel: str | None) -> list[str]:
        args = [ffmpeg, "-y"]
        if hwaccel:
            args += ["-hwaccel", hwaccel]
        args += [
            "-ss",
            f"{sample_time:.3f}",
            "-i",
            str(source_path),
            "-frames:v",
            "1",
            str(output_path),
        ]
        return args

    accel = run_ffmpeg_with_auto_accel(build_args)
    if not output_path.exists():
        raise RuntimeError("failed to extract preview frame")
    return output_path, accel


def process_video_to_job(
    upload_id: str,
    start_time: float,
    end_time: float,
    keep_every: int,
    target_size: int,
    reduce_px: int,
    canvas_mode: str,
    chroma_enabled: bool,
    matte_mode: str,
    key_mode: str,
    manual_key_hex: str,
    threshold: int,
    softness: int,
    despill_strength: float,
    halo_pixels: int,
    ai_model: str,
    ai_device: str,
    ai_resolution: int,
    luma_black: int,
    luma_white: int,
    luma_gamma: float,
    luma_strength: float,
    corridorkey_enabled: bool,
    corridorkey_screen: str,
    batch_green_to_black: bool = False,
    batch_semitransparent_to_black: bool = False,
    batch_semitransparent_to_opaque: bool = False,
) -> dict:
    source_path, media_type = source_media_entry(upload_id)
    info = media_info(source_path, media_type)
    start_time = max(0.0, start_time)
    duration = safe_float(info.get("duration"), 0.0)
    if media_type == "video" and duration > 0:
        end_time = min(end_time, duration)
    elif media_type == "image":
        start_time = 0.0
        end_time = 0.0
    if media_type == "video" and end_time <= start_time:
        raise ValueError("end time must be greater than start time")

    job_id = timestamped_id()
    root = job_dir(job_id)
    raw_dir = root / "raw"
    processed_dir = root / "processed"
    thumbs_dir = root / "thumbs"
    for directory in (processed_dir, thumbs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if media_type == "image":
        raw_path = raw_dir / "frame_00001.png"
        _, ffmpeg_accel = extract_image_frame(source_path, raw_path)
        raw_paths = [raw_path]
    else:
        raw_paths, ffmpeg_accel = extract_raw_frames(source_path, raw_dir, start_time, end_time, max(1, keep_every))
    raw_images = [open_rgba_image(path) for path in raw_paths]

    keyed_frames, key_rgb, matte_info = apply_matte_pipeline(
        raw_images=raw_images,
        chroma_enabled=chroma_enabled,
        matte_mode=matte_mode,
        key_mode=key_mode,
        manual_key_hex=manual_key_hex,
        threshold=threshold,
        softness=softness,
        despill_strength=despill_strength,
        halo_pixels=halo_pixels,
        ai_model=ai_model,
        ai_device=ai_device,
        ai_resolution=ai_resolution,
        luma_black=luma_black,
        luma_white=luma_white,
        luma_gamma=luma_gamma,
        luma_strength=luma_strength,
        corridorkey_enabled=corridorkey_enabled,
        corridorkey_screen=corridorkey_screen,
    )

    rendered_frames, bboxes, scale, canvas_size = stable_resize_frames(
        keyed_frames,
        target_size,
        reduce_px,
        canvas_mode,
        hard_alpha=matte_info["mode"] == "chroma" and softness == 0 and not matte_info["corridorkey_enabled"],
    )
    frame_entries: list[dict] = []
    postprocess_changed = {
        "green_to_black": 0,
        "semitransparent_to_black": 0,
        "semitransparent_to_opaque": 0,
    }
    for index, frame in enumerate(rendered_frames):
        frame_name = f"frame_{index + 1:03d}.png"
        thumb_name = f"thumb_{index + 1:03d}.png"
        frame_path = processed_dir / frame_name
        thumb_path = thumbs_dir / thumb_name
        if batch_green_to_black:
            frame, changed = green_to_black_image(frame)
            postprocess_changed["green_to_black"] += changed
        if batch_semitransparent_to_black:
            frame, changed = semitransparent_to_black_image(frame)
            postprocess_changed["semitransparent_to_black"] += changed
        if batch_semitransparent_to_opaque:
            frame, changed = semitransparent_to_opaque_image(frame)
            postprocess_changed["semitransparent_to_opaque"] += changed
        frame.save(frame_path)
        thumb = frame.copy()
        thumb.thumbnail((128, 128))
        thumb.save(thumb_path)
        frame_entries.append(
            {
                "index": index,
                "name": frame_name,
                "url": f"/work/jobs/{job_id}/processed/{frame_name}",
                "thumb_url": f"/work/jobs/{job_id}/thumbs/{thumb_name}",
                "bbox": list(bboxes[index]) if bboxes[index] else None,
                "width": frame.size[0],
                "height": frame.size[1],
            }
        )

    manifest = {
        "job_id": job_id,
        "upload_id": upload_id,
        "job_dir": str(root),
        "processed_dir": str(processed_dir),
        "raw_dir": str(raw_dir),
        "source_path": str(source_path),
        "source_media_type": media_type,
        "ffmpeg_accel": ffmpeg_accel,
        "video_info": info,
        "options": {
            "start_time": start_time,
            "end_time": end_time,
            "keep_every": keep_every,
            "target_size": target_size,
            "reduce_px": reduce_px,
            "canvas_mode": normalize_canvas_mode(canvas_mode),
            "output_width": canvas_size[0],
            "output_height": canvas_size[1],
            "chroma_enabled": chroma_enabled,
            "matte_mode": matte_info["mode"],
            "matte": matte_info,
            "key_mode": key_mode,
            "key_color": rgb_to_hex(key_rgb),
            "threshold": threshold,
            "softness": softness,
            "despill_strength": despill_strength,
            "halo_pixels": halo_pixels,
            "corridorkey_enabled": matte_info["corridorkey_enabled"],
            "corridorkey_screen": matte_info["corridorkey_screen_color"],
            "batch_green_to_black": bool(batch_green_to_black),
            "batch_semitransparent_to_black": bool(batch_semitransparent_to_black),
            "batch_semitransparent_to_opaque": bool(batch_semitransparent_to_opaque),
            "postprocess_changed_pixels": postprocess_changed,
            "scale": scale,
        },
        "frame_count": len(frame_entries),
        "frames": frame_entries,
    }
    save_job_manifest(job_id, manifest)
    return manifest


def preview_dir(preview_id: str) -> Path:
    return PREVIEWS_DIR / preview_id


def load_preview_manifest(preview_id: str) -> dict:
    preview_id = str(preview_id or "").strip()
    if not preview_id or Path(preview_id).name != preview_id:
        raise ValueError("invalid preview id")
    path = preview_dir(preview_id) / "preview.json"
    if not path.exists():
        raise FileNotFoundError(f"preview not found: {preview_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_preview_manifest(preview_id: str, manifest: dict) -> None:
    root = preview_dir(preview_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "preview.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def green_to_black_image(
    image: Image.Image,
    threshold: int = 42,
    dominance: int = 24,
    alpha_floor: int = 1,
) -> tuple[Image.Image, int]:
    rgba = image.convert("RGBA")
    output_pixels: list[tuple[int, int, int, int]] = []
    changed = 0
    threshold = max(0, min(255, int(threshold)))
    dominance = max(0, min(255, int(dominance)))
    alpha_floor = max(0, min(255, int(alpha_floor)))

    for r_value, g_value, b_value, alpha in rgba.getdata():
        raw_green_excess = g_value - max(r_value, b_value)
        is_raw_green = g_value >= threshold and raw_green_excess >= dominance
        is_alpha_scaled_green = False
        if alpha > 0:
            alpha_scale = 255.0 / alpha
            scaled_r = min(255, round(r_value * alpha_scale))
            scaled_g = min(255, round(g_value * alpha_scale))
            scaled_b = min(255, round(b_value * alpha_scale))
            scaled_green_excess = scaled_g - max(scaled_r, scaled_b)
            is_alpha_scaled_green = scaled_g >= threshold and scaled_green_excess >= dominance
        is_green = alpha >= alpha_floor and (is_raw_green or is_alpha_scaled_green)
        if is_green:
            output_pixels.append((0, 0, 0, alpha))
            changed += 1
        else:
            output_pixels.append((r_value, g_value, b_value, alpha))

    cleaned = Image.new("RGBA", rgba.size)
    cleaned.putdata(output_pixels)
    return cleaned, changed


def green_to_black_preview(preview_id: str, threshold: int = 42, dominance: int = 24) -> dict:
    preview = load_preview_manifest(preview_id)
    root = preview_dir(preview["preview_id"])
    processed_path = root / "processed.png"
    if not processed_path.exists():
        raise FileNotFoundError(f"processed preview missing: {processed_path}")

    image = open_rgba_image(processed_path)
    cleaned, changed = green_to_black_image(image, threshold=threshold, dominance=dominance)
    image.close()
    cleaned.save(processed_path)
    cleaned.close()

    postprocess = preview.setdefault("postprocess", {})
    green_black = postprocess.setdefault("green_to_black", {})
    green_black["enabled"] = True
    green_black["threshold"] = max(0, min(255, int(threshold)))
    green_black["dominance"] = max(0, min(255, int(dominance)))
    green_black["changed_pixels"] = changed
    green_black["updated_at"] = iso_now()
    preview["processed_url"] = f"/work/previews/{preview['preview_id']}/processed.png?ts={int(time.time() * 1000)}"
    save_preview_manifest(preview["preview_id"], preview)
    return preview


def semitransparent_to_black_image(
    image: Image.Image,
    alpha_min: int = 1,
    alpha_max: int = 254,
) -> tuple[Image.Image, int]:
    rgba = image.convert("RGBA")
    output_pixels: list[tuple[int, int, int, int]] = []
    changed = 0
    alpha_min = max(0, min(255, int(alpha_min)))
    alpha_max = max(alpha_min, min(255, int(alpha_max)))

    for r_value, g_value, b_value, alpha in rgba.getdata():
        if alpha_min <= alpha <= alpha_max:
            output_pixels.append((0, 0, 0, alpha))
            changed += 1
        else:
            output_pixels.append((r_value, g_value, b_value, alpha))

    cleaned = Image.new("RGBA", rgba.size)
    cleaned.putdata(output_pixels)
    return cleaned, changed


def semitransparent_to_black_preview(preview_id: str, alpha_min: int = 1, alpha_max: int = 254) -> dict:
    preview = load_preview_manifest(preview_id)
    root = preview_dir(preview["preview_id"])
    processed_path = root / "processed.png"
    if not processed_path.exists():
        raise FileNotFoundError(f"processed preview missing: {processed_path}")

    image = open_rgba_image(processed_path)
    cleaned, changed = semitransparent_to_black_image(image, alpha_min=alpha_min, alpha_max=alpha_max)
    image.close()
    cleaned.save(processed_path)
    cleaned.close()

    postprocess = preview.setdefault("postprocess", {})
    semitransparent_black = postprocess.setdefault("semitransparent_to_black", {})
    semitransparent_black["enabled"] = True
    semitransparent_black["alpha_min"] = max(0, min(255, int(alpha_min)))
    semitransparent_black["alpha_max"] = max(0, min(255, int(alpha_max)))
    semitransparent_black["changed_pixels"] = changed
    semitransparent_black["updated_at"] = iso_now()
    preview["processed_url"] = f"/work/previews/{preview['preview_id']}/processed.png?ts={int(time.time() * 1000)}"
    save_preview_manifest(preview["preview_id"], preview)
    return preview


def semitransparent_to_opaque_image(
    image: Image.Image,
    alpha_min: int = 1,
    alpha_max: int = 254,
) -> tuple[Image.Image, int]:
    rgba = image.convert("RGBA")
    output_pixels: list[tuple[int, int, int, int]] = []
    changed = 0
    alpha_min = max(0, min(255, int(alpha_min)))
    alpha_max = max(alpha_min, min(255, int(alpha_max)))

    for r_value, g_value, b_value, alpha in rgba.getdata():
        if alpha_min <= alpha <= alpha_max:
            output_pixels.append((r_value, g_value, b_value, 255))
            changed += 1
        else:
            output_pixels.append((r_value, g_value, b_value, alpha))

    cleaned = Image.new("RGBA", rgba.size)
    cleaned.putdata(output_pixels)
    return cleaned, changed


def semitransparent_to_opaque_preview(preview_id: str, alpha_min: int = 1, alpha_max: int = 254) -> dict:
    preview = load_preview_manifest(preview_id)
    root = preview_dir(preview["preview_id"])
    processed_path = root / "processed.png"
    if not processed_path.exists():
        raise FileNotFoundError(f"processed preview missing: {processed_path}")

    image = open_rgba_image(processed_path)
    cleaned, changed = semitransparent_to_opaque_image(image, alpha_min=alpha_min, alpha_max=alpha_max)
    image.close()
    cleaned.save(processed_path)
    cleaned.close()

    postprocess = preview.setdefault("postprocess", {})
    semitransparent_opaque = postprocess.setdefault("semitransparent_to_opaque", {})
    semitransparent_opaque["enabled"] = True
    semitransparent_opaque["alpha_min"] = max(0, min(255, int(alpha_min)))
    semitransparent_opaque["alpha_max"] = max(0, min(255, int(alpha_max)))
    semitransparent_opaque["changed_pixels"] = changed
    semitransparent_opaque["updated_at"] = iso_now()
    preview["processed_url"] = f"/work/previews/{preview['preview_id']}/processed.png?ts={int(time.time() * 1000)}"
    save_preview_manifest(preview["preview_id"], preview)
    return preview


def preview_frame(
    upload_id: str,
    sample_time: float,
    target_size: int,
    reduce_px: int,
    canvas_mode: str,
    chroma_enabled: bool,
    matte_mode: str,
    key_mode: str,
    manual_key_hex: str,
    threshold: int,
    softness: int,
    despill_strength: float,
    halo_pixels: int,
    ai_model: str,
    ai_device: str,
    ai_resolution: int,
    luma_black: int,
    luma_white: int,
    luma_gamma: float,
    luma_strength: float,
    corridorkey_enabled: bool,
    corridorkey_screen: str,
    batch_green_to_black: bool = False,
    batch_semitransparent_to_black: bool = False,
    batch_semitransparent_to_opaque: bool = False,
) -> dict:
    source_path, media_type = source_media_entry(upload_id)
    info = media_info(source_path, media_type)
    duration = safe_float(info.get("duration"), 0.0)
    if media_type == "video" and duration > 0:
        sample_time = clamp_float(sample_time, 0.0, duration)
    else:
        sample_time = 0.0

    preview_id = timestamped_id()
    root = preview_dir(preview_id)
    raw_path = root / "raw.png"
    source_preview_path = root / "source.png"
    processed_path = root / "processed.png"

    if media_type == "image":
        _, ffmpeg_accel = extract_image_frame(source_path, raw_path)
    else:
        _, ffmpeg_accel = extract_single_frame(source_path, raw_path, sample_time)
    raw_image = open_rgba_image(raw_path)

    raw_image.save(source_preview_path)

    keyed_frames, key_rgb, matte_info = apply_matte_pipeline(
        raw_images=[raw_image],
        chroma_enabled=chroma_enabled,
        matte_mode=matte_mode,
        key_mode=key_mode,
        manual_key_hex=manual_key_hex,
        threshold=threshold,
        softness=softness,
        despill_strength=despill_strength,
        halo_pixels=halo_pixels,
        ai_model=ai_model,
        ai_device=ai_device,
        ai_resolution=ai_resolution,
        luma_black=luma_black,
        luma_white=luma_white,
        luma_gamma=luma_gamma,
        luma_strength=luma_strength,
        corridorkey_enabled=corridorkey_enabled,
        corridorkey_screen=corridorkey_screen,
    )
    keyed_image = keyed_frames[0]

    rendered_frames, _, scale, canvas_size = stable_resize_frames(
        [keyed_image],
        target_size,
        reduce_px,
        canvas_mode,
        hard_alpha=matte_info["mode"] == "chroma" and softness == 0 and not matte_info["corridorkey_enabled"],
    )
    rendered_frame = rendered_frames[0]
    postprocess_changed = {
        "green_to_black": 0,
        "semitransparent_to_black": 0,
        "semitransparent_to_opaque": 0,
    }
    if batch_green_to_black:
        rendered_frame, changed = green_to_black_image(rendered_frame)
        postprocess_changed["green_to_black"] += changed
    if batch_semitransparent_to_black:
        rendered_frame, changed = semitransparent_to_black_image(rendered_frame)
        postprocess_changed["semitransparent_to_black"] += changed
    if batch_semitransparent_to_opaque:
        rendered_frame, changed = semitransparent_to_opaque_image(rendered_frame)
        postprocess_changed["semitransparent_to_opaque"] += changed
    rendered_frame.save(processed_path)

    manifest = {
        "preview_id": preview_id,
        "upload_id": upload_id,
        "sample_time": sample_time,
        "source_path": str(source_path),
        "source_media_type": media_type,
        "source_url": f"/work/previews/{preview_id}/source.png",
        "processed_url": f"/work/previews/{preview_id}/processed.png",
        "key_color": rgb_to_hex(key_rgb),
        "matte": matte_info,
        "ffmpeg_accel": ffmpeg_accel,
        "scale": scale,
        "postprocess_changed": postprocess_changed,
        "options": {
            "target_size": target_size,
            "reduce_px": reduce_px,
            "canvas_mode": normalize_canvas_mode(canvas_mode),
            "output_width": canvas_size[0],
            "output_height": canvas_size[1],
            "chroma_enabled": chroma_enabled,
            "matte_mode": matte_info["mode"],
            "key_mode": key_mode,
            "threshold": threshold,
            "softness": softness,
            "despill_strength": despill_strength,
            "halo_pixels": halo_pixels,
            "corridorkey_enabled": matte_info["corridorkey_enabled"],
            "corridorkey_screen": matte_info["corridorkey_screen_color"],
            "batch_green_to_black": bool(batch_green_to_black),
            "batch_semitransparent_to_black": bool(batch_semitransparent_to_black),
            "batch_semitransparent_to_opaque": bool(batch_semitransparent_to_opaque),
            "postprocess_changed_pixels": postprocess_changed,
        },
    }
    (root / "preview.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def save_preview_as_job(preview_id: str) -> dict:
    preview = load_preview_manifest(preview_id)
    if str(preview.get("source_media_type") or "").lower() != "image":
        raise ValueError("direct preview save is only available for image uploads")

    source_preview_path = preview_dir(preview["preview_id"]) / "source.png"
    raw_preview_path = preview_dir(preview["preview_id"]) / "raw.png"
    processed_preview_path = preview_dir(preview["preview_id"]) / "processed.png"
    if not processed_preview_path.exists():
        raise FileNotFoundError(f"processed preview missing: {processed_preview_path}")

    source_path = repair_mojibake_path(Path(preview["source_path"]))
    media_type = str(preview.get("source_media_type") or "image").lower()
    info = media_info(source_path, media_type)
    options = preview.get("options") or {}
    matte_info = preview.get("matte") or {"mode": options.get("matte_mode") or "chroma"}

    job_id = timestamped_id()
    root = job_dir(job_id)
    raw_dir = root / "raw"
    processed_dir = root / "processed"
    thumbs_dir = root / "thumbs"
    for directory in (raw_dir, processed_dir, thumbs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if raw_preview_path.exists():
        shutil.copy2(raw_preview_path, raw_dir / "frame_00001.png")
    elif source_preview_path.exists():
        shutil.copy2(source_preview_path, raw_dir / "frame_00001.png")

    frame_name = "frame_001.png"
    thumb_name = "thumb_001.png"
    frame_path = processed_dir / frame_name
    thumb_path = thumbs_dir / thumb_name
    shutil.copy2(processed_preview_path, frame_path)

    frame = open_rgba_image(frame_path)
    thumb = frame.copy()
    thumb.thumbnail((128, 128))
    thumb.save(thumb_path)
    bbox = frame.getchannel("A").getbbox()
    canvas_size = frame.size

    manifest = {
        "job_id": job_id,
        "upload_id": preview.get("upload_id") or "",
        "job_dir": str(root),
        "processed_dir": str(processed_dir),
        "raw_dir": str(raw_dir),
        "source_path": str(source_path),
        "source_media_type": media_type,
        "ffmpeg_accel": preview.get("ffmpeg_accel") or {},
        "video_info": info,
        "options": {
            "start_time": 0,
            "end_time": 0,
            "keep_every": 1,
            "target_size": options.get("target_size") or canvas_size[1],
            "reduce_px": options.get("reduce_px") or 0,
            "canvas_mode": normalize_canvas_mode(str(options.get("canvas_mode") or "auto")),
            "output_width": options.get("output_width") or canvas_size[0],
            "output_height": options.get("output_height") or canvas_size[1],
            "chroma_enabled": bool(options.get("chroma_enabled", True)),
            "matte_mode": matte_info.get("mode") or options.get("matte_mode") or "chroma",
            "matte": matte_info,
            "key_mode": options.get("key_mode") or "auto",
            "key_color": preview.get("key_color") or "#000000",
            "threshold": options.get("threshold") or 0,
            "softness": options.get("softness") or 0,
            "despill_strength": options.get("despill_strength") or 0,
            "halo_pixels": options.get("halo_pixels") or 0,
            "corridorkey_enabled": bool(options.get("corridorkey_enabled", False)),
            "corridorkey_screen": options.get("corridorkey_screen") or "auto",
            "scale": preview.get("scale") or 1,
        },
        "frame_count": 1,
        "frames": [
            {
                "index": 0,
                "name": frame_name,
                "url": f"/work/jobs/{job_id}/processed/{frame_name}",
                "thumb_url": f"/work/jobs/{job_id}/thumbs/{thumb_name}",
                "bbox": list(bbox) if bbox else None,
                "width": canvas_size[0],
                "height": canvas_size[1],
            }
        ],
    }
    save_job_manifest(job_id, manifest)
    return manifest


def natural_sort_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def field_storage_items(form: cgi.FieldStorage, key: str) -> list:
    if key not in form:
        return []
    value = form[key]
    return value if isinstance(value, list) else [value]


def import_animation_frames_to_job(file_items: list) -> dict:
    candidates = []
    for item in file_items:
        raw_filename = str(getattr(item, "filename", "") or "frame")
        display_name = Path(raw_filename.replace("\\", "/")).name or "frame"
        if not getattr(item, "file", None):
            continue
        suffix = Path(display_name).suffix.lower()
        content_type = str(getattr(item, "type", "") or "")
        if suffix not in ANIMATION_FRAME_EXTENSIONS and not content_type.startswith("image/"):
            continue
        candidates.append((raw_filename, display_name, item))

    candidates.sort(key=lambda pair: natural_sort_key(pair[0]))
    if not candidates:
        raise ValueError("no supported image frames found")

    job_id = timestamped_id()
    root = job_dir(job_id)
    raw_dir = root / "raw"
    processed_dir = root / "processed"
    thumbs_dir = root / "thumbs"
    for directory in (raw_dir, processed_dir, thumbs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    frame_entries: list[dict] = []
    max_width = 0
    max_height = 0
    for index, (_, display_name, item) in enumerate(candidates):
        frame_name = f"frame_{index + 1:03d}.png"
        thumb_name = f"thumb_{index + 1:03d}.png"
        raw_path = raw_dir / frame_name
        frame_path = processed_dir / frame_name
        thumb_path = thumbs_dir / thumb_name

        with Image.open(item.file) as source_image:
            image = source_image.convert("RGBA")
            image.save(raw_path)
            image.save(frame_path)
            thumb = image.copy()
            thumb.thumbnail((128, 128))
            thumb.save(thumb_path)
            bbox = image.getchannel("A").getbbox()
            max_width = max(max_width, image.size[0])
            max_height = max(max_height, image.size[1])

            frame_entries.append(
                {
                    "index": index,
                    "name": frame_name,
                    "original_name": display_name,
                    "url": f"/work/jobs/{job_id}/processed/{frame_name}",
                    "thumb_url": f"/work/jobs/{job_id}/thumbs/{thumb_name}",
                    "bbox": list(bbox) if bbox else None,
                    "width": image.size[0],
                    "height": image.size[1],
                }
            )
            image.close()

    manifest = {
        "job_id": job_id,
        "upload_id": "",
        "job_dir": str(root),
        "processed_dir": str(processed_dir),
        "raw_dir": str(raw_dir),
        "source_path": "",
        "source_media_type": "animation",
        "ffmpeg_accel": custom_animation_payload(),
        "video_info": {
            "media_type": "animation",
            "duration": 0,
            "fps": 0,
            "width": max_width,
            "height": max_height,
        },
        "options": {
            "start_time": 0,
            "end_time": 0,
            "keep_every": 1,
            "target_size": max_height,
            "reduce_px": 0,
            "canvas_mode": "custom",
            "output_width": max_width,
            "output_height": max_height,
            "chroma_enabled": False,
            "matte_mode": "none",
            "matte": {"mode": "none", "source": "custom_animation"},
            "key_mode": "none",
            "key_color": "#000000",
            "threshold": 0,
            "softness": 0,
            "despill_strength": 0,
            "halo_pixels": 0,
            "corridorkey_enabled": False,
            "corridorkey_screen": "auto",
            "scale": 1,
            "source_order": "filename",
        },
        "frame_count": len(frame_entries),
        "frames": frame_entries,
    }
    save_job_manifest(job_id, manifest)
    return manifest


def save_alpha_mov(
    frame_paths: list[Path],
    frame_sizes: list[tuple[int, int]],
    output_path: Path,
    cell_width: int,
    cell_height: int,
    duration_ms: int,
) -> None:
    if not frame_paths:
        raise ValueError("no frames selected for alpha video export")
    ffmpeg = resolve_ffmpeg_binary("ffmpeg")
    duration_ms = clamp_int(duration_ms, 20, 5000)
    video_frames_dir = output_path.parent / "video_frames_tmp"
    if video_frames_dir.exists():
        shutil.rmtree(video_frames_dir)
    video_frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, frame_path in enumerate(frame_paths, start=1):
            frame = open_rgba_image(frame_path)
            frame_width, frame_height = frame_sizes[index - 1]
            canvas = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
            offset_x = (cell_width - frame_width) // 2
            offset_y = (cell_height - frame_height) // 2
            canvas.paste(frame, (offset_x, offset_y), frame)
            frame.close()
            canvas.save(video_frames_dir / f"frame_{index:03d}.png")
            canvas.close()

        input_pattern = video_frames_dir / "frame_%03d.png"
        run_process(
            [
                ffmpeg,
                "-y",
                "-framerate",
                f"1000/{duration_ms}",
                "-start_number",
                "1",
                "-i",
                str(input_pattern),
                "-frames:v",
                str(len(frame_paths)),
                "-c:v",
                "qtrle",
                "-pix_fmt",
                "argb",
                str(output_path),
            ]
        )
    finally:
        shutil.rmtree(video_frames_dir, ignore_errors=True)


def export_job(job_id: str, selected_indices: list[int], sheet_columns: int, video_duration_ms: int) -> dict:
    manifest = load_job_manifest(job_id)
    processed_dir = job_dir(job_id) / "processed"
    target_dir = EXPORTS_DIR / f"{timestamped_id()}-export"
    frames_dir = target_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frame_map = {entry["index"]: entry for entry in manifest["frames"]}
    seen_indices: set[int] = set()
    indices: list[int] = []
    for index in selected_indices:
        if index in frame_map and index not in seen_indices:
            indices.append(index)
            seen_indices.add(index)
    if not indices:
        raise ValueError("no frames selected for export")

    copied_paths: list[Path] = []
    for output_index, frame_index in enumerate(indices, start=1):
        entry = frame_map[frame_index]
        source_path = processed_dir / entry["name"]
        target_path = frames_dir / f"frame_{output_index:03d}.png"
        shutil.copy2(source_path, target_path)
        copied_paths.append(target_path)

    zip_path = target_dir / "frames.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for frame_path in copied_paths:
            archive.write(frame_path, arcname=frame_path.name)

    cell_width = 0
    cell_height = 0
    frame_sizes: list[tuple[int, int]] = []
    for frame_path in copied_paths:
        frame = open_rgba_image(frame_path)
        frame_sizes.append(frame.size)
        cell_width = max(cell_width, frame.size[0])
        cell_height = max(cell_height, frame.size[1])
        frame.close()
    columns = max(1, sheet_columns or round(math.sqrt(len(copied_paths))))
    rows = math.ceil(len(copied_paths) / columns)
    sheet = Image.new("RGBA", (columns * cell_width, rows * cell_height), (0, 0, 0, 0))
    for index, frame_path in enumerate(copied_paths):
        row = index // columns
        column = index % columns
        frame = open_rgba_image(frame_path)
        frame_width, frame_height = frame_sizes[index]
        offset_x = column * cell_width + (cell_width - frame_width) // 2
        offset_y = row * cell_height + (cell_height - frame_height) // 2
        sheet.paste(frame, (offset_x, offset_y), frame)
        frame.close()
    sheet_path = target_dir / "sprite_sheet.png"
    sheet.save(sheet_path)
    sheet.close()

    video_duration_ms = clamp_int(video_duration_ms, 20, 5000)
    video_path = target_dir / "animation.mov"
    save_alpha_mov(copied_paths, frame_sizes, video_path, cell_width, cell_height, video_duration_ms)

    export_manifest = {
        "job_id": job_id,
        "selected_indices": indices,
        "sheet_columns": columns,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "frame_count": len(copied_paths),
        "frames_dir": str(frames_dir),
        "zip_path": str(zip_path),
        "sheet_path": str(sheet_path),
        "video_path": str(video_path),
        "video_duration_ms": video_duration_ms,
    }
    (target_dir / "export.json").write_text(json.dumps(export_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "output_dir": str(target_dir),
        "frames_dir": str(frames_dir),
        "zip_url": f"/work/exports/{target_dir.name}/frames.zip",
        "sheet_url": f"/work/exports/{target_dir.name}/sprite_sheet.png",
        "video_url": f"/work/exports/{target_dir.name}/animation.mov",
        "manifest_url": f"/work/exports/{target_dir.name}/export.json",
        "frame_count": len(copied_paths),
        "video_duration_ms": video_duration_ms,
    }


def asset_lab_repo() -> tuple[AssetLabConfig, object, AssetRepository]:
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
        "ok": True,
        "workspace_root": str(config.workspace_root),
        "providers": providers,
    }


def read_dotenv_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def set_dotenv_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = read_dotenv_lines(path)
    output: list[str] = []
    written = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            current_key = stripped.split("=", 1)[0].strip()
            if current_key == key:
                if not written:
                    output.append(f"{key}={value}")
                    written = True
                continue
        output.append(line)
    if not written:
        output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def save_asset_lab_provider_key_payload(payload: dict) -> dict:
    provider_name = str(payload.get("provider") or "").strip().lower()
    api_key = str(payload.get("api_key") or "").strip()
    key_map = {
        "toioto": "TOIOTO_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    if provider_name not in key_map:
        raise ValueError("不支持的生图来源")
    if not api_key:
        raise ValueError("请填写 API key")
    env_key = key_map[provider_name]
    set_dotenv_value(TOOL_ENV_PATH, env_key, api_key)
    os.environ[env_key] = api_key
    return {
        "ok": True,
        "provider": provider_name,
        "message": "API key 已保存到工具 .env。",
    }


def create_asset_lab_project_payload(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("project name is required")
    description = str(payload.get("description", "")).strip()
    _config, conn, repo = asset_lab_repo()
    try:
        project = repo.create_project(name, description)
    finally:
        conn.close()
    return {"ok": True, "project": project}


def list_asset_lab_projects_payload() -> dict:
    _config, conn, repo = asset_lab_repo()
    try:
        return {"ok": True, "projects": repo.list_projects()}
    finally:
        conn.close()


def list_asset_lab_assets_payload(query: str) -> dict:
    params = parse_qs(query)
    filters = {
        "project_id": safe_int(params["project_id"][0], 0) if params.get("project_id") else None,
        "status": params.get("status", [""])[0],
        "asset_type": params.get("asset_type", [""])[0],
        "component_type": params.get("component_type", [""])[0],
        "provider": params.get("provider", [""])[0],
        "prompt": params.get("prompt", [""])[0],
    }
    if filters["project_id"] == 0:
        filters["project_id"] = None
    _config, conn, repo = asset_lab_repo()
    try:
        return {"ok": True, "assets": repo.search_assets(filters)}
    finally:
        conn.close()


def normalize_asset_lab_size(value, default: int = 1024) -> int:
    size = safe_int(value, default)
    return max(64, min(4096, size))


def normalize_asset_lab_count(value) -> int:
    count = safe_int(value, 1)
    return max(1, min(4, count))


def save_asset_lab_reference_file(file_item, output_dir: Path, index: int) -> Path:
    filename = clean_filename(file_item.filename or f"reference-{index}.png")
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = content_type_extension(getattr(file_item, "type", "")) or ".png"
    if suffix not in IMAGE_EXTENSIONS:
        raise ValueError("参考图只支持 png / jpg / jpeg / webp / bmp")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"reference_{index:02d}{suffix}"
    with target.open("wb") as output:
        shutil.copyfileobj(file_item.file, output)
    return target


def create_asset_lab_generation_payload(
    payload: dict,
    reference_image_paths: list[Path] | None = None,
    mask_image_path: Path | None = None,
) -> dict:
    provider_name = str(payload.get("provider") or "").strip().lower()
    if not provider_name:
        raise ValueError("请选择生图来源")
    provider = get_provider(provider_name)
    if not provider.is_configured():
        raise ValueError(provider.configuration_message())

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("请填写提示词")

    project_id = safe_int(payload.get("project_id"), 0)
    project_id_value = project_id if project_id > 0 else None
    asset_type = str(payload.get("asset_type") or "asset").strip() or "asset"
    component_type = str(payload.get("component_type") or "").strip()
    negative_prompt = str(payload.get("negative_prompt") or "").strip()
    style_text = str(payload.get("style_text") or "").strip()
    width = normalize_asset_lab_size(payload.get("width"), 1024)
    height = normalize_asset_lab_size(payload.get("height"), 1024)
    count = normalize_asset_lab_count(payload.get("count"))
    quality = str(payload.get("quality") or "low").strip() or "low"
    transparent_background = bool(payload.get("transparent_background"))
    request_params = {
        "quality": quality,
        "width": width,
        "height": height,
        "count": count,
        "transparent_background": transparent_background,
        "mode": "reference" if reference_image_paths else "text",
        "reference_image_count": len(reference_image_paths or []),
        "has_mask": mask_image_path is not None,
    }
    request = GenerationRequest(
        project_id=project_id_value,
        asset_type=asset_type,
        component_type=component_type,
        prompt=prompt,
        negative_prompt=negative_prompt,
        style_text=style_text,
        width=width,
        height=height,
        count=count,
        transparent_background=transparent_background,
        reference_image_paths=reference_image_paths or [],
        mask_image_path=mask_image_path,
        params={"quality": quality},
    )

    config, conn, repo = asset_lab_repo()
    job = repo.create_generation_job(
        project_id=project_id_value,
        provider=provider_name,
        asset_type=asset_type,
        component_type=component_type,
        prompt=prompt,
        negative_prompt=negative_prompt,
        style_text_snapshot=style_text,
        request_params=request_params,
    )
    tmp_dir = config.tmp_dir / f"generation-{job['id']}"
    assets = []
    try:
        repo.update_generation_job_status(job["id"], "running")
        result = provider.generate(request, tmp_dir)
        for index, image_path in enumerate(result.image_paths):
            saved = save_candidate_image(config, image_path, provider_name, asset_type)
            seed = result.seeds[index] if index < len(result.seeds) else ""
            asset = repo.create_asset(
                project_id=project_id_value,
                source_job_id=job["id"],
                asset_type=asset_type,
                component_type=component_type,
                provider=provider_name,
                file_path=str(saved.file_path),
                relative_file_path=saved.relative_file_path,
                thumbnail_path=str(saved.thumbnail_path),
                relative_thumbnail_path=saved.relative_thumbnail_path,
                width=saved.info.width,
                height=saved.info.height,
                has_alpha=saved.info.has_alpha,
                is_transparent_bg=saved.info.is_transparent_bg,
                prompt=prompt,
                background_color=saved.info.background_color,
                negative_prompt=negative_prompt,
                style_text_snapshot=style_text,
                provider_params=result.provider_params,
                seed=seed,
                format=saved.info.format,
            )
            assets.append(asset)
        job = repo.update_generation_job_status(job["id"], "completed")
    except Exception as exc:
        repo.update_generation_job_status(job["id"], "failed", str(exc))
        raise
    finally:
        conn.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"ok": True, "job": job, "assets": assets}


def create_asset_lab_generation_from_form(form: cgi.FieldStorage) -> dict:
    payload = {
        "provider": form.getfirst("provider", ""),
        "project_id": form.getfirst("project_id", ""),
        "asset_type": form.getfirst("asset_type", ""),
        "component_type": form.getfirst("component_type", ""),
        "style_text": form.getfirst("style_text", ""),
        "prompt": form.getfirst("prompt", ""),
        "negative_prompt": form.getfirst("negative_prompt", ""),
        "width": form.getfirst("width", ""),
        "height": form.getfirst("height", ""),
        "quality": form.getfirst("quality", ""),
        "count": form.getfirst("count", ""),
        "transparent_background": form.getfirst("transparent_background", "") in {"1", "true", "True", "on"},
    }
    reference_dir = load_config().tmp_dir / f"references-{timestamped_id()}"
    reference_paths: list[Path] = []
    mask_path: Path | None = None
    try:
        for index, file_item in enumerate(field_storage_items(form, "reference_images"), start=1):
            if getattr(file_item, "file", None):
                reference_paths.append(save_asset_lab_reference_file(file_item, reference_dir, index))
        mask_items = field_storage_items(form, "mask_image")
        if mask_items and getattr(mask_items[0], "file", None) and mask_items[0].filename:
            mask_path = save_asset_lab_reference_file(mask_items[0], reference_dir, 0)
        return create_asset_lab_generation_payload(payload, reference_paths, mask_path)
    finally:
        shutil.rmtree(reference_dir, ignore_errors=True)


def send_asset_lab_asset_to_sprite_payload(asset_id: int) -> dict:
    if asset_id <= 0:
        raise ValueError("asset id is required")

    config, conn, repo = asset_lab_repo()
    try:
        asset = repo.get_asset(asset_id)
    except KeyError as exc:
        raise FileNotFoundError(f"asset not found: {asset_id}") from exc
    finally:
        conn.close()

    source_path = repair_mojibake_path(Path(str(asset.get("file_path") or ""))).expanduser().resolve()
    if not is_within_root(source_path, config.workspace_root):
        raise ValueError("asset file path is outside workspace")

    upload = register_video_from_path(source_path)
    return {"ok": True, "upload": upload, "asset": asset}


def resolve_asset_lab_file(relative_path: str) -> Path:
    config = load_config()
    root = config.workspace_root.resolve()
    target = (root / relative_path).resolve()
    if not is_within_root(target, root):
        raise ValueError("asset file path is outside workspace")
    return target


class AppHandler(BaseHTTPRequestHandler):
    server_version = "SpriteVideoLab/0.1"

    def log_message(self, format, *args) -> None:
        return

    def send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"ok": False, "error": message}, status=status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/app-version":
            self.send_json(
                {
                    "ok": True,
                    "version": current_app_version(),
                    "poll_ms": APP_VERSION_POLL_MS,
                }
            )
            return
        if parsed.path == "/api/asset-lab/status":
            self.send_json(asset_lab_status_payload())
            return
        if parsed.path == "/api/asset-lab/projects":
            self.send_json(list_asset_lab_projects_payload())
            return
        if parsed.path == "/api/asset-lab/assets":
            self.send_json(list_asset_lab_assets_payload(parsed.query))
            return
        if parsed.path == "/":
            self.serve_app_file(APP_DIR / "index.html", content_type="text/html; charset=utf-8")
            return
        if parsed.path.startswith("/app/"):
            relative = parsed.path.removeprefix("/app/")
            self.serve_app_file(APP_DIR / relative)
            return
        if parsed.path.startswith("/media/upload/"):
            upload_id = parsed.path.removeprefix("/media/upload/")
            self.serve_media_file(source_video_path(upload_id), allow_range=True)
            return
        if parsed.path.startswith("/work/"):
            relative = parsed.path.removeprefix("/work/")
            self.serve_work_file((WORK_DIR / relative).resolve())
            return
        if parsed.path.startswith("/asset-lab-files/"):
            relative = unquote(parsed.path.removeprefix("/asset-lab-files/"))
            try:
                self.serve_asset_lab_file(resolve_asset_lab_file(relative))
            except ValueError:
                self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/asset-lab/projects":
                payload = self.read_json_body()
                self.send_json(create_asset_lab_project_payload(payload), status=HTTPStatus.CREATED)
                return
            if parsed.path == "/api/asset-lab/provider-key":
                payload = self.read_json_body()
                self.send_json(save_asset_lab_provider_key_payload(payload))
                return
            if parsed.path == "/api/asset-lab/generate":
                content_type = self.headers.get("Content-Type", "")
                if content_type.lower().startswith("multipart/form-data"):
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={
                            "REQUEST_METHOD": "POST",
                            "CONTENT_TYPE": content_type,
                            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                        },
                    )
                    result = create_asset_lab_generation_from_form(form)
                else:
                    payload = self.read_json_body()
                    result = create_asset_lab_generation_payload(payload)
                self.send_json(result, status=HTTPStatus.CREATED)
                return
            asset_sprite_match = re.fullmatch(r"/api/asset-lab/assets/(\d+)/send-to-sprite", parsed.path)
            if asset_sprite_match:
                result = send_asset_lab_asset_to_sprite_payload(int(asset_sprite_match.group(1)))
                self.send_json(result)
                return
            if parsed.path == "/api/import-path":
                payload = self.read_json_body()
                raw_path = str(payload.get("path") or "").strip().strip("\"'")
                result = register_video_from_path(Path(raw_path))
                self.send_json({"ok": True, "upload": result})
                return
            if parsed.path == "/api/upload":
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                        "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                    },
                )
                file_item = form["video"] if "video" in form else None
                if file_item is None or not getattr(file_item, "file", None):
                    raise ValueError("media file missing")
                result = register_uploaded_file(file_item)
                self.send_json({"ok": True, "upload": result})
                return
            if parsed.path == "/api/import-animation":
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                        "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                    },
                )
                result = import_animation_frames_to_job(field_storage_items(form, "frames"))
                self.send_json({"ok": True, "job": result})
                return
            if parsed.path == "/api/process":
                payload = self.read_json_body()
                result = process_video_to_job(
                    upload_id=str(payload.get("upload_id") or ""),
                    start_time=safe_float(payload.get("start_time"), 0.0),
                    end_time=safe_float(payload.get("end_time"), 0.0),
                    keep_every=max(1, safe_int(payload.get("keep_every"), 1)),
                    target_size=max(32, safe_int(payload.get("target_size"), 256)),
                    reduce_px=max(0, safe_int(payload.get("reduce_px"), 20)),
                    canvas_mode=normalize_canvas_mode(str(payload.get("canvas_mode") or "auto")),
                    chroma_enabled=bool(payload.get("chroma_enabled", True)),
                    matte_mode=str(payload.get("matte_mode") or ""),
                    key_mode=str(payload.get("key_mode") or "auto"),
                    manual_key_hex=str(payload.get("manual_key_hex") or "#00FF00"),
                    threshold=max(0, safe_int(payload.get("threshold"), 80)),
                    softness=max(0, safe_int(payload.get("softness"), 32)),
                    despill_strength=max(0.0, safe_float(payload.get("despill_strength"), 0.85)),
                    halo_pixels=max(0, safe_int(payload.get("halo_pixels"), 1)),
                    ai_model=normalize_ai_model_key(str(payload.get("ai_model") or DEFAULT_AI_MATTE_MODEL)),
                    ai_device=normalize_ai_device(str(payload.get("ai_device") or "auto")),
                    ai_resolution=normalize_ai_resolution(payload.get("ai_resolution")),
                    luma_black=max(0, min(254, safe_int(payload.get("luma_black"), 24))),
                    luma_white=max(1, min(255, safe_int(payload.get("luma_white"), 230))),
                    luma_gamma=max(0.05, safe_float(payload.get("luma_gamma"), 1.0)),
                    luma_strength=max(0.0, min(2.0, safe_float(payload.get("luma_strength"), 1.0))),
                    corridorkey_enabled=bool(payload.get("corridorkey_enabled", False)),
                    corridorkey_screen=normalize_corridorkey_screen(str(payload.get("corridorkey_screen") or "auto")),
                    batch_green_to_black=bool(payload.get("batch_green_to_black", False)),
                    batch_semitransparent_to_black=bool(payload.get("batch_semitransparent_to_black", False)),
                    batch_semitransparent_to_opaque=bool(payload.get("batch_semitransparent_to_opaque", False)),
                )
                self.send_json({"ok": True, "job": result})
                return
            if parsed.path == "/api/preview-frame":
                payload = self.read_json_body()
                result = preview_frame(
                    upload_id=str(payload.get("upload_id") or ""),
                    sample_time=safe_float(payload.get("sample_time"), 0.0),
                    target_size=max(32, safe_int(payload.get("target_size"), 256)),
                    reduce_px=max(0, safe_int(payload.get("reduce_px"), 20)),
                    canvas_mode=normalize_canvas_mode(str(payload.get("canvas_mode") or "auto")),
                    chroma_enabled=bool(payload.get("chroma_enabled", True)),
                    matte_mode=str(payload.get("matte_mode") or ""),
                    key_mode=str(payload.get("key_mode") or "auto"),
                    manual_key_hex=str(payload.get("manual_key_hex") or "#00FF00"),
                    threshold=max(0, safe_int(payload.get("threshold"), 80)),
                    softness=max(0, safe_int(payload.get("softness"), 32)),
                    despill_strength=max(0.0, safe_float(payload.get("despill_strength"), 0.85)),
                    halo_pixels=max(0, safe_int(payload.get("halo_pixels"), 1)),
                    ai_model=normalize_ai_model_key(str(payload.get("ai_model") or DEFAULT_AI_MATTE_MODEL)),
                    ai_device=normalize_ai_device(str(payload.get("ai_device") or "auto")),
                    ai_resolution=normalize_ai_resolution(payload.get("ai_resolution")),
                    luma_black=max(0, min(254, safe_int(payload.get("luma_black"), 24))),
                    luma_white=max(1, min(255, safe_int(payload.get("luma_white"), 230))),
                    luma_gamma=max(0.05, safe_float(payload.get("luma_gamma"), 1.0)),
                    luma_strength=max(0.0, min(2.0, safe_float(payload.get("luma_strength"), 1.0))),
                    corridorkey_enabled=bool(payload.get("corridorkey_enabled", False)),
                    corridorkey_screen=normalize_corridorkey_screen(str(payload.get("corridorkey_screen") or "auto")),
                    batch_green_to_black=bool(payload.get("batch_green_to_black", False)),
                    batch_semitransparent_to_black=bool(payload.get("batch_semitransparent_to_black", False)),
                    batch_semitransparent_to_opaque=bool(payload.get("batch_semitransparent_to_opaque", False)),
                )
                self.send_json({"ok": True, "preview": result})
                return
            if parsed.path == "/api/save-preview":
                payload = self.read_json_body()
                result = save_preview_as_job(str(payload.get("preview_id") or ""))
                self.send_json({"ok": True, "job": result})
                return
            if parsed.path == "/api/preview-green-to-black":
                payload = self.read_json_body()
                result = green_to_black_preview(
                    str(payload.get("preview_id") or ""),
                    threshold=max(0, min(255, safe_int(payload.get("threshold"), 42))),
                    dominance=max(0, min(255, safe_int(payload.get("dominance"), 24))),
                )
                self.send_json({"ok": True, "preview": result})
                return
            if parsed.path == "/api/preview-semitransparent-to-black":
                payload = self.read_json_body()
                result = semitransparent_to_black_preview(
                    str(payload.get("preview_id") or ""),
                    alpha_min=max(0, min(255, safe_int(payload.get("alpha_min"), 1))),
                    alpha_max=max(0, min(255, safe_int(payload.get("alpha_max"), 254))),
                )
                self.send_json({"ok": True, "preview": result})
                return
            if parsed.path == "/api/preview-semitransparent-to-opaque":
                payload = self.read_json_body()
                result = semitransparent_to_opaque_preview(
                    str(payload.get("preview_id") or ""),
                    alpha_min=max(0, min(255, safe_int(payload.get("alpha_min"), 1))),
                    alpha_max=max(0, min(255, safe_int(payload.get("alpha_max"), 254))),
                )
                self.send_json({"ok": True, "preview": result})
                return
            if parsed.path == "/api/export":
                payload = self.read_json_body()
                result = export_job(
                    job_id=str(payload.get("job_id") or ""),
                    selected_indices=[safe_int(value, -1) for value in (payload.get("selected_indices") or [])],
                    sheet_columns=max(1, safe_int(payload.get("sheet_columns"), 4)),
                    video_duration_ms=safe_int(payload.get("video_duration_ms"), 100),
                )
                self.send_json({"ok": True, "export": result})
                return
            if parsed.path == "/api/open-path":
                payload = self.read_json_body()
                target = Path(str(payload.get("path") or "").strip()).expanduser().resolve()
                if not target.exists():
                    raise FileNotFoundError(target)
                open_path_in_file_browser(target)
                self.send_json({"ok": True})
                return
        except FileNotFoundError as exc:
            self.send_error_json(str(exc), status=HTTPStatus.NOT_FOUND)
            return
        except Exception as exc:
            self.send_error_json(str(exc), status=HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def serve_app_file(self, path: Path, content_type: str | None = None, allow_range: bool = False) -> None:
        if not is_within_root(path, APP_DIR):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.serve_file(path, content_type=content_type, allow_range=allow_range)

    def serve_work_file(self, path: Path, content_type: str | None = None, allow_range: bool = False) -> None:
        if not is_within_root(path, WORK_DIR):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.serve_file(path, content_type=content_type, allow_range=allow_range)

    def serve_asset_lab_file(self, path: Path, content_type: str | None = None, allow_range: bool = False) -> None:
        config = load_config()
        if not is_within_root(path, config.workspace_root):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.serve_file(path, content_type=content_type, allow_range=allow_range)

    def serve_media_file(self, path: Path, content_type: str | None = None, allow_range: bool = False) -> None:
        self.serve_file(path, content_type=content_type, allow_range=allow_range)

    def serve_file(self, path: Path, content_type: str | None = None, allow_range: bool = False) -> None:
        path = path.resolve()
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        guessed_type = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        file_size = path.stat().st_size
        range_header = self.headers.get("Range") if allow_range else None

        if range_header and range_header.startswith("bytes="):
            start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
            start = int(start_text or "0")
            end = int(end_text or file_size - 1)
            end = min(end, file_size - 1)
            if start > end:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            length = (end - start) + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Type", guessed_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                self.wfile.write(handle.read(length))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", guessed_type)
        self.send_header("Content-Length", str(file_size))
        if allow_range:
            self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)


def serve_once(host: str, port: int) -> None:
    ensure_runtime_dirs()
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Sprite Video Lab running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def stop_child_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_with_reloader(host: str, port: int) -> None:
    ensure_runtime_dirs()
    watch_state = watch_snapshot()
    child: subprocess.Popen | None = None
    print(f"Sprite Video Lab reloader watching {len(watch_state)} files.")
    try:
        while True:
            if child is None or child.poll() is not None:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT_DIR / "server.py"),
                        "--serve",
                        "--host",
                        host,
                        "--port",
                        str(port),
                    ],
                    cwd=str(ROOT_DIR),
                )
            time.sleep(0.8)
            next_snapshot = watch_snapshot()
            if next_snapshot != watch_state:
                print("Changes detected. Reloading Sprite Video Lab...")
                watch_state = next_snapshot
                stop_child_process(child)
                child = None
    except KeyboardInterrupt:
        pass
    finally:
        stop_child_process(child)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Sprite Video Lab.")
    parser.add_argument("--serve", action="store_true", help="Run the HTTP server once without file watching.")
    parser.add_argument("--host", default=None, help=f"Host to bind. Defaults to ${HOST_ENV} or {DEFAULT_HOST}.")
    parser.add_argument("--port", type=int, default=None, help=f"Port to bind. Defaults to ${PORT_ENV} or {DEFAULT_PORT}.")
    args = parser.parse_args()
    host = configured_host(args.host)
    port = configured_port(args.port)
    if args.serve:
        serve_once(host, port)
        return
    run_with_reloader(host, port)


if __name__ == "__main__":
    main()
