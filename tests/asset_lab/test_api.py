def test_status_payload_uses_configured_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_VIDEO_LAB_WORKSPACE", str(tmp_path / "workspace"))

    from server import asset_lab_status_payload

    payload = asset_lab_status_payload()

    assert payload["ok"] is True
    assert payload["workspace_root"] == str(tmp_path / "workspace")
    assert "openai" in payload["providers"]
    assert "toioto" in payload["providers"]


def test_create_project_api_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_VIDEO_LAB_WORKSPACE", str(tmp_path / "workspace"))

    from server import create_asset_lab_project_payload

    payload = create_asset_lab_project_payload(
        {"name": "Project A", "description": "manual"}
    )

    assert payload["ok"] is True
    assert payload["project"]["name"] == "Project A"
    assert payload["project"]["description"] == "manual"


def test_project_list_includes_asset_stats(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_VIDEO_LAB_WORKSPACE", str(tmp_path / "workspace"))

    from server import asset_lab_repo, create_asset_lab_project_payload, list_asset_lab_projects_payload

    project_payload = create_asset_lab_project_payload(
        {"name": "Project Stats", "description": "has activity"}
    )
    project_id = project_payload["project"]["id"]
    _config, conn, repo = asset_lab_repo()
    try:
        repo.create_asset(
            project_id=project_id,
            asset_type="icon",
            component_type="item",
            provider="manual",
            file_path=str(tmp_path / "a.png"),
            relative_file_path="images/a.png",
            width=32,
            height=32,
            has_alpha=True,
            is_transparent_bg=True,
            prompt="first",
        )
        repo.create_asset(
            project_id=project_id,
            asset_type="icon",
            component_type="item",
            provider="manual",
            file_path=str(tmp_path / "b.png"),
            relative_file_path="images/b.png",
            width=32,
            height=32,
            has_alpha=True,
            is_transparent_bg=True,
            prompt="second",
        )
    finally:
        conn.close()

    payload = list_asset_lab_projects_payload()
    project = next(item for item in payload["projects"] if item["id"] == project_id)

    assert project["asset_count"] == 2
    assert project["latest_asset_at"]
    assert project["activity"][0]["count"] == 2
    assert project["activity"][0]["first_asset_at"]
    assert project["activity"][0]["latest_asset_at"]


def test_generate_asset_api_records_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_VIDEO_LAB_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("TOIOTO_API_KEY", "test-key")

    from PIL import Image

    from asset_lab.providers.base import GenerationResult
    from server import create_asset_lab_generation_payload

    def fake_generate(self, request, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / "generated.png"
        Image.new("RGBA", (32, 24), (255, 0, 0, 0)).save(image_path)
        return GenerationResult(
            image_paths=[image_path],
            provider_params={"model": "gpt-image-2", "quality": request.params["quality"]},
        )

    monkeypatch.setattr("asset_lab.providers.toioto.ToioToProvider.generate", fake_generate)

    payload = create_asset_lab_generation_payload(
        {
            "provider": "toioto",
            "asset_type": "icon",
            "component_type": "item",
            "prompt": "A local test icon",
            "width": 1024,
            "height": 1024,
            "quality": "low",
            "transparent_background": True,
        }
    )

    assert payload["ok"] is True
    assert payload["job"]["status"] == "completed"
    assert payload["assets"][0]["provider"] == "toioto"
    assert payload["assets"][0]["width"] == 32
    assert payload["assets"][0]["relative_file_path"].startswith("images/candidates/")


def test_send_asset_lab_asset_to_sprite_registers_local_image(tmp_path, monkeypatch):
    monkeypatch.setenv("SPRITE_VIDEO_LAB_WORKSPACE", str(tmp_path / "workspace"))

    from PIL import Image

    from server import (
        asset_lab_repo,
        create_asset_lab_project_payload,
        send_asset_lab_asset_to_sprite_payload,
    )

    project_id = create_asset_lab_project_payload({"name": "Sprite Bridge"})["project"]["id"]
    image_path = tmp_path / "workspace" / "images" / "candidates" / "bridge.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (40, 30), (255, 0, 0, 0)).save(image_path)

    _config, conn, repo = asset_lab_repo()
    try:
        asset = repo.create_asset(
            project_id=project_id,
            asset_type="icon",
            component_type="item",
            provider="manual",
            file_path=str(image_path),
            relative_file_path="images/candidates/bridge.png",
            width=40,
            height=30,
            has_alpha=True,
            is_transparent_bg=True,
            prompt="bridge to sprite",
        )
    finally:
        conn.close()

    payload = send_asset_lab_asset_to_sprite_payload(asset["id"])

    assert payload["ok"] is True
    assert payload["asset"]["id"] == asset["id"]
    assert payload["upload"]["media_type"] == "image"
    assert payload["upload"]["display_name"] == "bridge.png"
    assert payload["upload"]["media_info"]["width"] == 40
    assert payload["upload"]["media_info"]["height"] == 30


def test_save_provider_key_writes_tool_env(tmp_path, monkeypatch):
    import server

    env_path = tmp_path / ".env"
    monkeypatch.setattr(server, "TOOL_ENV_PATH", env_path)
    monkeypatch.delenv("TOIOTO_API_KEY", raising=False)

    payload = server.save_asset_lab_provider_key_payload(
        {"provider": "toioto", "api_key": "sk-test-local"}
    )

    assert payload["ok"] is True
    assert "TOIOTO_API_KEY=sk-test-local" in env_path.read_text(encoding="utf-8")
    assert server.os.environ["TOIOTO_API_KEY"] == "sk-test-local"


def test_parse_ffmpeg_video_info_fallback():
    from server import parse_ffmpeg_video_info

    payload = parse_ffmpeg_video_info(
        """
        Duration: 00:00:06.08, start: 0.000000, bitrate: 6710 kb/s
        Stream #0:0: Video: h264 (High), yuv420p(progressive), 960x960, 24.10 fps, 60 tbr
        """
    )

    assert payload["width"] == 960
    assert payload["height"] == 960
    assert payload["fps"] == 24.10
    assert payload["duration"] == 6.08
    assert payload["codec"] == "h264"
