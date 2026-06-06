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
            return "OpenAI 生图已配置。"
        return f"设置 {self.api_key_env} 后可启用 OpenAI 生图。"

    def generate(
        self,
        request: GenerationRequest,
        output_dir: Path,
    ) -> GenerationResult:
        if not self.is_configured():
            raise RuntimeError(self.configuration_message())
        raise NotImplementedError(
            "OpenAI image generation API call is not implemented yet."
        )
