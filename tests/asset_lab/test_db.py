from asset_lab.config import AssetLabConfig
from asset_lab.db import connect_db, migrate


def test_workspace_directories_are_created(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()

    assert config.workspace_root.exists()
    assert config.images_candidates_dir.exists()
    assert config.images_selected_dir.exists()
    assert config.images_rejected_dir.exists()
    assert config.images_imported_dir.exists()
    assert config.thumbnails_dir.exists()
    assert config.styles_dir.exists()
    assert config.tmp_dir.exists()


def test_migrate_creates_core_tables(tmp_path):
    config = AssetLabConfig(tmp_path / "workspace")
    config.ensure()

    with connect_db(config) as conn:
        migrate(conn)
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "projects" in table_names
    assert "styles" in table_names
    assert "generation_jobs" in table_names
    assert "assets" in table_names
    assert "tags" in table_names
    assert "asset_tags" in table_names
