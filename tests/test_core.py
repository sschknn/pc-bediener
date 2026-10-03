"""Tests für Konfiguration, Sicherheits-Gate und Pfad-Guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbediener import runtime
from pcbediener.config import Config, load_config
from pcbediener.paths import resolve_within
from pcbediener.safety import (
    ConfirmationRequired,
    ForbiddenCommand,
    PathNotAllowed,
    check_not_forbidden,
    find_forbidden,
    require_confirm,
)


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.safety_mode == "confirm"
        assert cfg.requires_confirmation is True
        assert cfg.screenshot_dir  # wird in __post_init__ gefüllt

    def test_auto_mode_needs_no_confirmation(self):
        assert Config(safety_mode="auto").requires_confirmation is False

    def test_invalid_safety_mode_rejected(self):
        with pytest.raises(ValueError, match="safety_mode"):
            Config(safety_mode="yolo")  # type: ignore[arg-type]

    def test_invalid_timeout_rejected(self):
        with pytest.raises(ValueError, match="exec_timeout"):
            Config(exec_timeout=0)

    def test_load_defaults_when_file_missing(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nicht-da.json")
        assert cfg.safety_mode == "confirm"

    def test_load_from_file(self, tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"safety_mode": "auto", "exec_timeout": 5, "allowed_paths": [str(tmp_path)]}),
            encoding="utf-8",
        )
        cfg = load_config(path)
        assert cfg.safety_mode == "auto"
        assert cfg.exec_timeout == 5
        assert cfg.resolved_allowed_paths() == [tmp_path.resolve()]

    def test_unknown_key_is_error(self, tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"gibt_es_nicht": 1}), encoding="utf-8")
        with pytest.raises(ValueError, match="Unbekannte"):
            load_config(path)

    def test_env_overrides_file(self, tmp_path: Path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"exec_timeout": 5}), encoding="utf-8")
        monkeypatch.setenv("PCB_EXEC_TIMEOUT", "99")
        assert load_config(path).exec_timeout == 99

    def test_env_bool_coercion(self, monkeypatch):
        monkeypatch.setenv("PCB_ALLOWED_PATHS", str(Path.cwd()))
        cfg = load_config(Path("gibt-es-nicht.json"))
        assert cfg.resolved_allowed_paths() == [Path.cwd().resolve()]

    def test_save_and_reload_roundtrip(self, tmp_path: Path):
        cfg = Config(safety_mode="auto", exec_timeout=42, forbidden_patterns=["^x"])
        target = cfg.save(tmp_path / "sub" / "config.json")
        again = load_config(target)
        assert again.safety_mode == "auto"
        assert again.exec_timeout == 42
        assert again.forbidden_patterns == ["^x"]


class TestSafetyPatterns:
    @pytest.mark.parametrize(
        "code",
        [
            "format C:",
            "del /s /q C:\\*",
            "Remove-Item C:\\Windows -Recurse",
            "Remove-Item -Recurse C:\\Windows",
            "rm -rf /",
            "vssadmin delete shadows /all /quiet",
            "shutdown /s /f",
            "Set-ExecutionPolicy Unrestricted",
            "cipher /w:C",
            "reg add HKCU\\...\\Run",
        ],
    )
    def test_dangerous_patterns_are_blocked(self, code: str, cfg: Config):
        assert find_forbidden(code) is not None
        with pytest.raises(ForbiddenCommand):
            check_not_forbidden(code, cfg)

    @pytest.mark.parametrize(
        "code",
        [
            "print('hallo')",
            "import os; os.remove('C:\\\\temp\\\\test.txt')",
            "Get-ChildItem C:\\Users | Measure-Object",
            "for f in pathlib.Path('.').glob('*.py'): print(f)",
        ],
    )
    def test_harmless_code_passes(self, code: str, cfg: Config):
        assert find_forbidden(code) is None
        check_not_forbidden(code, cfg)  # darf nicht werfen

    def test_extra_pattern_from_config(self, cfg: Config):
        cfg.forbidden_patterns.append(r"mein_geheimes_wort")
        with pytest.raises(ForbiddenCommand, match="mein_geheimes_wort"):
            check_not_forbidden("echo mein_geheimes_wort", cfg)

    def test_forbidden_also_blocks_in_auto_mode(self):
        """Die Sperrliste gilt unabhängig vom Sicherheitsmodus."""
        cfg = Config(safety_mode="auto")
        with pytest.raises(ForbiddenCommand):
            check_not_forbidden("format C:", cfg)


class TestConfirmation:
    def test_confirm_mode_requires_flag(self, cfg: Config):
        with pytest.raises(ConfirmationRequired, match="bestätig|Bestätigung|confirm"):
            require_confirm(False, cfg, "Löschen", "C:\\test.txt")

    def test_confirm_mode_passes_with_flag(self, cfg: Config):
        require_confirm(True, cfg, "Löschen", "C:\\test.txt")  # darf nicht werfen

    def test_auto_mode_never_asks(self):
        cfg = Config(safety_mode="auto")
        require_confirm(False, cfg, "Löschen", "egal")  # darf nicht werfen

    def test_error_message_contains_detail(self, cfg: Config):
        with pytest.raises(ConfirmationRequired, match="meine_datei.txt"):
            require_confirm(False, cfg, "Löschen", "meine_datei.txt")


class TestPathGuard:
    def test_allows_path_inside_root(self, cfg: Config, workspace: Path):
        target = workspace / "unterordner" / "datei.txt"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        assert resolve_within(target, cfg) == target.resolve()

    def test_allows_root_itself(self, cfg: Config, workspace: Path):
        assert resolve_within(workspace, cfg) == workspace.resolve()

    def test_blocks_outside_root(self, cfg: Config, tmp_path: Path):
        with pytest.raises(PathNotAllowed, match="verweigert"):
            resolve_within(tmp_path / "fremd", cfg)

    def test_blocks_parent_traversal(self, cfg: Config, workspace: Path):
        with pytest.raises(PathNotAllowed):
            resolve_within(workspace / ".." / ".." / "Windows", cfg)

    def test_blocks_system_root(self, cfg: Config):
        with pytest.raises(PathNotAllowed):
            resolve_within("C:\\Windows\\System32", cfg)

    def test_relative_path_resolved_against_cwd(self, cfg: Config, workspace: Path):
        (workspace / "datei.txt").write_text("x", encoding="utf-8")
        assert resolve_within("datei.txt", cfg).name == "datei.txt"

    def test_missing_file_raises_filenotfound(self, cfg: Config, workspace: Path):
        with pytest.raises(FileNotFoundError):
            resolve_within(workspace / "gibtsnicht.txt", cfg, must_exist=True)


class TestRuntime:
    def test_safety_mode_can_switch_at_runtime(self, cfg: Config):
        runtime.set_config(cfg)
        assert runtime.describe()["requires_confirmation"] is True
        runtime.set_safety_mode("auto")
        assert runtime.get_config().safety_mode == "auto"
        assert runtime.describe()["requires_confirmation"] is False

    def test_invalid_mode_rejected(self, cfg: Config):
        runtime.set_config(cfg)
        with pytest.raises(Exception):
            runtime.set_safety_mode("völlig egal")

    def test_describe_lists_allowed_paths(self, cfg: Config, workspace: Path):
        runtime.set_config(cfg)
        assert str(workspace.resolve()) in runtime.describe()["allowed_paths"]