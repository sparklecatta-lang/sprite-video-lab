import base64
import json
import subprocess

from PIL import Image

from asset_lab.providers import get_provider, list_providers
from asset_lab.providers.base import GenerationRequest


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


def test_toioto_provider_posts_request_and_writes_png(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGBA", (16, 16), (255, 0, 0, 0)).save(source)
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        request_path = args[args.index("--data-binary") + 1].removeprefix("@")
        with open(request_path, encoding="utf-8") as handle:
            captured["body"] = json.load(handle)
        response_path = args[args.index("-o") + 1]
        with open(response_path, "w", encoding="utf-8") as handle:
            json.dump({"data": [{"b64_json": encoded}]}, handle)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setenv("TOIOTO_API_KEY", "test-key")
    monkeypatch.setattr("asset_lab.providers.toioto.shutil.which", lambda name: "curl.exe")
    monkeypatch.setattr("asset_lab.providers.toioto.subprocess.run", fake_run)
    provider = get_provider("toioto")

    result = provider.generate(
        GenerationRequest(
            project_id=None,
            asset_type="icon",
            component_type="button",
            prompt="A test icon",
            width=1024,
            height=1024,
            transparent_background=True,
            params={"quality": "low"},
        ),
        tmp_path / "out",
    )

    assert result.image_paths[0].exists()
    assert captured["args"][0] == "curl.exe"
    assert "Authorization: Bearer test-key" in captured["args"]
    assert captured["body"]["model"] == "gpt-image-2"
    assert captured["body"]["size"] == "1024x1024"
    assert captured["body"]["background"] == "transparent"


def test_toioto_provider_uses_edits_for_reference_images(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(source)
    reference = tmp_path / "reference.png"
    Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(reference)
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        response_path = args[args.index("-o") + 1]
        with open(response_path, "w", encoding="utf-8") as handle:
            json.dump({"data": [{"b64_json": encoded}]}, handle)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setenv("TOIOTO_API_KEY", "test-key")
    monkeypatch.setenv("TOIOTO_IMAGE_EDIT_ENDPOINT", "https://example.test/v1/images/edits")
    monkeypatch.setattr("asset_lab.providers.toioto.shutil.which", lambda name: "curl.exe")
    monkeypatch.setattr("asset_lab.providers.toioto.subprocess.run", fake_run)
    provider = get_provider("toioto")

    result = provider.generate(
        GenerationRequest(
            project_id=None,
            asset_type="icon",
            component_type="button",
            prompt="Make a variant",
            reference_image_paths=[reference],
            params={"quality": "low"},
        ),
        tmp_path / "out",
    )

    assert result.image_paths[0].exists()
    assert "https://example.test/v1/images/edits" in captured["args"]
    assert "-F" in captured["args"]
    assert any(str(value).startswith("image=@") and str(reference) in str(value) for value in captured["args"])
    assert result.provider_params["mode"] == "reference"
    assert result.provider_params["reference_image_count"] == 1
