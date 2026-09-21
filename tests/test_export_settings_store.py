"""export_settings_store のユニットテスト."""

from __future__ import annotations

import json
from pathlib import Path

from screen_audio_recorder.export_settings_store import (
    get_default_export_dir,
    load_export_settings,
    resolve_output_html_path,
    save_export_settings,
)
from screen_audio_recorder.models import ExportSettings


def test_load_returns_defaults_when_missing(tmp_path: Path) -> None:
    settings = load_export_settings(tmp_path / "nope.json")
    assert settings == ExportSettings()
    assert settings.html_enabled is False
    assert settings.output_dir == ""
    assert settings.include_output_file_path is False


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "export_settings.json"
    original = ExportSettings(
        html_enabled=True,
        output_dir="C:/tmp/out",
        include_output_file_path=True,
    )
    save_export_settings(original, path)
    loaded = load_export_settings(path)
    assert loaded == original


def test_load_broken_json_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert load_export_settings(path) == ExportSettings()


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "dir" / "export_settings.json"
    save_export_settings(ExportSettings(html_enabled=True), path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["html_enabled"] is True


def test_resolve_output_uses_default_when_empty() -> None:
    settings = ExportSettings(output_dir="")
    resolved = resolve_output_html_path(settings)
    assert resolved.parent == get_default_export_dir()
    assert resolved.name == "memo-viewer.html"


def test_resolve_output_dir_appends_filename(tmp_path: Path) -> None:
    settings = ExportSettings(output_dir=str(tmp_path))
    resolved = resolve_output_html_path(settings)
    assert resolved == tmp_path / "memo-viewer.html"


def test_resolve_output_html_file_used_directly(tmp_path: Path) -> None:
    target = tmp_path / "custom.html"
    settings = ExportSettings(output_dir=str(target))
    resolved = resolve_output_html_path(settings)
    assert resolved == target
