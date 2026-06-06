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
