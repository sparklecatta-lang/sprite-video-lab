from asset_lab.config import AssetLabConfig
from asset_lab.db import connect_db, migrate
from asset_lab.repository import AssetRepository


def make_repo(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()
    conn = connect_db(config)
    migrate(conn)
    return AssetRepository(conn)


def test_create_project_and_style(tmp_path):
    repo = make_repo(tmp_path)

    project = repo.create_project("Project A", "Local category")
    style = repo.create_style("Soft UI", "rounded bright interface")

    assert project["name"] == "Project A"
    assert project["description"] == "Local category"
    assert style["name"] == "Soft UI"
    assert style["body"] == "rounded bright interface"


def test_search_assets_by_project_status_and_prompt(tmp_path):
    repo = make_repo(tmp_path)
    project = repo.create_project("Project A", "")
    other = repo.create_project("Project B", "")

    repo.create_asset(
        project_id=project["id"],
        asset_type="icon",
        component_type="item_icon",
        provider="openai",
        file_path="D:/library/images/candidates/a.png",
        relative_file_path="images/candidates/a.png",
        width=1024,
        height=1024,
        has_alpha=True,
        is_transparent_bg=True,
        prompt="blue crystal bottle",
    )
    repo.create_asset(
        project_id=other["id"],
        asset_type="background",
        component_type="landscape",
        provider="toioto",
        file_path="D:/library/images/candidates/b.png",
        relative_file_path="images/candidates/b.png",
        width=1920,
        height=1080,
        has_alpha=False,
        is_transparent_bg=False,
        prompt="mountain sunset",
    )

    results = repo.search_assets(
        {
            "project_id": project["id"],
            "status": "candidate",
            "prompt": "crystal",
        }
    )

    assert len(results) == 1
    assert results[0]["prompt"] == "blue crystal bottle"
