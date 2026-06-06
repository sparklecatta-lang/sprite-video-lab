from pathlib import Path


def test_sprite_page_accessibility_copy_is_chinese():
    html = Path("app/index.html").read_text(encoding="utf-8")

    for text in (
        "源图片预览",
        "起点增加一帧",
        "起点减少一帧",
        "终点增加一帧",
        "终点减少一帧",
    ):
        assert text in html

    for text in (
        "source image preview",
        "Start plus one frame",
        "Start minus one frame",
        "End plus one frame",
        "End minus one frame",
    ):
        assert text not in html
