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
