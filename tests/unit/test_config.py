from pathlib import Path

import pytest

import app.config as config


def test_app_port_uses_render_port_when_provided(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.delenv("APP_PORT", raising=False)
    settings = config.Settings(_env_file=None)
    assert settings.APP_PORT == 10000


@pytest.mark.parametrize("resolver, executable", [
    ("resolve_ffmpeg", "ffmpeg.exe"),
    ("resolve_ffprobe", "ffprobe.exe"),
])
def test_binary_resolution_skips_inaccessible_winget_folder(monkeypatch, tmp_path, resolver, executable):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    binary_setting = "FFMPEG_BINARY" if resolver == "resolve_ffmpeg" else "FFPROBE_BINARY"
    monkeypatch.setattr(config.settings, binary_setting, None)
    blocked_folder = tmp_path / "Microsoft" / "WinGet" / "Packages"
    original_exists = Path.exists

    def exists_or_denied(path):
        if path == blocked_folder:
            raise PermissionError("restricted by policy")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", exists_or_denied)

    resolved = getattr(config.settings, resolver)()
    project_binary = Path(config.__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / executable
    assert resolved == (str(project_binary) if project_binary.is_file() else executable.removesuffix(".exe"))


@pytest.mark.parametrize("resolver, setting, path_name", [
    ("resolve_ffmpeg", "FFMPEG_BINARY", "ffmpeg"),
    ("resolve_ffprobe", "FFPROBE_BINARY", "ffprobe"),
])
def test_binary_resolution_falls_back_when_configured_path_is_inaccessible(
    monkeypatch, resolver, setting, path_name
):
    monkeypatch.setattr(config.settings, setting, r"C:\restricted\media-tools\binary.exe")
    monkeypatch.setattr(config.shutil, "which", lambda name: f"C:/available/{name}.exe")

    original_is_file = Path.is_file

    def inaccessible_configured_file(path):
        if str(path) == r"C:\restricted\media-tools\binary.exe":
            raise PermissionError("restricted by policy")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", inaccessible_configured_file)

    resolved = getattr(config.settings, resolver)()
    project_binary = Path(config.__file__).resolve().parents[1] / "tools" / "ffmpeg" / "bin" / f"{path_name}.exe"
    assert resolved == (str(project_binary) if project_binary.is_file() else f"C:/available/{path_name}.exe")
