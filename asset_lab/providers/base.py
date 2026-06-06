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
    reference_image_paths: list[Path] = field(default_factory=list)
    mask_image_path: Path | None = None
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

    def generate(
        self,
        request: GenerationRequest,
        output_dir: Path,
    ) -> GenerationResult:
        ...
