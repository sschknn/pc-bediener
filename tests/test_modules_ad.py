"""Tests für Modul A (Code-Ausführung) und Modul D (Dateisystem)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pcbediener.config import Config
from pcbediener.modules import exec as mod_exec
from pcbediener.modules import files as mod_files
from pcbediener.safety import ConfirmationRequired, ForbiddenCommand


class TestExec:
    def test_python_success(self, cfg: Config):
        result = mod_exec.run_python("print('hallo welt')", cfg, confirm=True)
        assert result.ok is True
        assert result.returncode == 0
        assert "hallo welt" in result.stdout
        assert result.stderr == ""

    def test_python_error_is_captured(self, cfg: Config):
        result = mod_exec.run_python("raise ValueError('kaputt')", cfg, confirm=True)
        assert result.ok is False
        assert result.returncode != 0
        assert "ValueError" in result.stderr
        assert "kaputt" in result.stderr

    def test_python_works_without_stdin(self, cfg: Config):
        """Unter '-I' darf keine Eingabe blockieren."""
        result = mod_exec.run_python("input('x') if False else print('ok')", cfg, confirm=True)
        assert result.stdout.strip() == "ok"

    def test_stderr_separate_from_stdout(self, cfg: Config):
        code = "import sys; sys.stdout.write('out'); sys.stderr.write('err')"
        result = mod_exec.run_python(code, cfg, confirm=True)
        assert result.stdout == "out"
        assert result.stderr == "err"

    def test_timeout_is_reported(self, cfg: Config):
        cfg.exec_timeout = 1
        result = mod_exec.run_python("import time; time.sleep(30)", cfg, confirm=True)
        assert result.timed_out is True
        assert result.ok is False
        assert "Zeitüberschreitung" in result.stderr

    def test_confirmation_required_in_confirm_mode(self, cfg: Config):
        with pytest.raises(ConfirmationRequired):
            mod_exec.run_python("print(1)", cfg, confirm=False)

    def test_forbidden_code_blocked_even_with_confirm(self, cfg: Config):
        with pytest.raises(ForbiddenCommand):
            mod_exec.run_python("import os; os.system('format C:')", cfg, confirm=True)

    def test_empty_code_rejected(self, cfg: Config):
        with pytest.raises(ValueError, match="nicht leer"):
            mod_exec.run_python("   ", cfg, confirm=True)

    def test_output_is_truncated(self, cfg: Config):
        cfg.exec_max_output_chars = 500
        result = mod_exec.run_python("print('x' * 50000)", cfg, confirm=True)
        assert result.truncated is True
        assert len(result.stdout) < 50000
        assert "Zeichen ausgegeben" in result.stdout

    def test_cwd_is_used(self, cfg: Config, workspace: Path):
        result = mod_exec.run_python("import os; print(os.getcwd())", cfg, confirm=True)
        assert str(workspace.resolve()).lower() in result.stdout.lower()

    def test_exec_env_is_passed(self, cfg: Config):
        cfg.exec_env = {"MEIN_TEST_WERT": "42"}
        result = mod_exec.run_python(
            "import os; print(os.environ.get('MEIN_TEST_WERT'))", cfg, confirm=True
        )
        assert result.stdout.strip() == "42"

    def test_powershell_runs(self, cfg: Config):
        if sys.platform != "win32":
            pytest.skip("nur unter Windows verfügbar")
        result = mod_exec.run_powershell("Write-Output 'pw-ok'", cfg, confirm=True)
        assert result.ok is True
        assert "pw-ok" in result.stdout

    def test_command_routes_to_powershell(self, cfg: Config):
        if sys.platform != "win32":
            pytest.skip("nur unter Windows verfügbar")
        result = mod_exec.run_command("Write-Output 'cmd-ok'", cfg, confirm=True)
        assert "cmd-ok" in result.stdout

    def test_auto_mode_needs_no_confirm(self, workspace: Path):
        cfg = Config(safety_mode="auto", allowed_paths=[str(workspace)], exec_cwd=str(workspace))
        result = mod_exec.run_python("print('autonom')", cfg, confirm=False)
        assert result.ok is True


class TestFiles:
    def test_write_and_read_roundtrip(self, cfg: Config, workspace: Path):
        written = mod_files.write_text("hallo.txt", "Zeile 1\nZeile 2", cfg, confirm=True)
        assert written["created"] is True
        read = mod_files.read_text(workspace / "hallo.txt", cfg)
        assert read["content"] == "Zeile 1\nZeile 2"
        assert read["lines"] == 2

    def test_write_needs_confirmation(self, cfg: Config):
        with pytest.raises(ConfirmationRequired):
            mod_files.write_text("x.txt", "daten", cfg, confirm=False)

    def test_append_needs_no_confirmation(self, cfg: Config, workspace: Path):
        mod_files.write_text("log.txt", "a", cfg, confirm=True)
        result = mod_files.write_text(workspace / "log.txt", "b", cfg, append=True, confirm=False)
        assert result["append"] is True
        assert mod_files.read_text(workspace / "log.txt", cfg)["content"] == "ab"

    def test_write_creates_parents(self, cfg: Config):
        result = mod_files.write_text("a/b/c/tief.txt", "x", cfg, confirm=True)
        assert Path(result["path"]).is_file()

    def test_read_missing_file(self, cfg: Config, workspace: Path):
        with pytest.raises(FileNotFoundError):
            mod_files.read_text(workspace / "gibtsnicht.txt", cfg)

    def test_read_binary_format_refused(self, cfg: Config, workspace: Path):
        target = workspace / "bild.png"
        target.write_bytes(b"\x89PNG\r\n")
        with pytest.raises(ValueError, match="Binärformat"):
            mod_files.read_text(target, cfg)
        result = mod_files.read_binary(target, cfg)
        assert result["content_base64"] == "iVBORw0K"  # b64 von \x89PNG\r\n

    def test_read_text_truncates(self, cfg: Config, workspace: Path):
        (workspace / "lang.txt").write_text("y" * 5000, encoding="utf-8")
        result = mod_files.read_text(workspace / "lang.txt", cfg, max_chars=100)
        assert result["truncated"] is True
        assert len(result["content"]) == 100

    def test_list_dir_sorted_dirs_first(self, cfg: Config, workspace: Path):
        (workspace / "ordner").mkdir()
        (workspace / "b.txt").write_text("b", encoding="utf-8")
        (workspace / "a.txt").write_text("a", encoding="utf-8")
        names = [e["name"] for e in mod_files.list_dir(workspace, cfg)["entries"]]
        assert names == ["ordner", "a.txt", "b.txt"]

    def test_list_dir_with_pattern(self, cfg: Config, workspace: Path):
        (workspace / "x.py").write_text("", encoding="utf-8")
        (workspace / "y.txt").write_text("", encoding="utf-8")
        result = mod_files.list_dir(workspace, cfg, pattern="*.py")
        assert result["count"] == 1
        assert [e["name"] for e in result["entries"]] == ["x.py"]

    def test_search_finds_nested(self, cfg: Config, workspace: Path):
        deep = workspace / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "ziel.txt").write_text("x", encoding="utf-8")
        found = mod_files.search(workspace, cfg, pattern="ziel.txt")
        assert found["count"] == 1
        assert found["matches"][0]["path"].endswith("ziel.txt")

    def test_search_respects_max_results(self, cfg: Config, workspace: Path):
        for i in range(10):
            (workspace / f"f{i}.txt").write_text("", encoding="utf-8")
        limited = mod_files.search(workspace, cfg, max_results=3)
        assert limited["count"] == 3
        assert limited["truncated"] is True

    def test_search_respects_max_depth(self, cfg: Config, workspace: Path):
        deep = workspace / "1" / "2" / "3" / "4"
        deep.mkdir(parents=True)
        (deep / "tief.txt").write_text("", encoding="utf-8")
        shallow = mod_files.search(workspace, cfg, max_depth=2)["matches"]
        assert all("tief.txt" not in hit["path"] for hit in shallow)

    def test_tree_has_depth_field(self, cfg: Config, workspace: Path):
        (workspace / "unter").mkdir()
        (workspace / "unter" / "datei.txt").write_text("", encoding="utf-8")
        tree = mod_files.tree(workspace, cfg)["entries"]
        depths = {entry["name"]: entry["depth"] for entry in tree}
        assert depths["unter"] == 0
        assert depths["datei.txt"] == 1

    def test_move_and_rename(self, cfg: Config, workspace: Path):
        source = workspace / "alt.txt"
        source.write_text("inhalt", encoding="utf-8")
        result = mod_files.move(source, workspace / "neu.txt", cfg, confirm=True)
        assert not source.exists()
        assert Path(result["destination"]).read_text(encoding="utf-8") == "inhalt"

    def test_move_needs_confirmation(self, cfg: Config, workspace: Path):
        (workspace / "a.txt").write_text("x", encoding="utf-8")
        with pytest.raises(ConfirmationRequired):
            mod_files.move(workspace / "a.txt", workspace / "b.txt", cfg)

    def test_copy_file_and_dir(self, cfg: Config, workspace: Path):
        (workspace / "quelle").mkdir()
        (workspace / "quelle" / "innen.txt").write_text("drin", encoding="utf-8")
        mod_files.copy(workspace / "quelle", workspace / "kopie", cfg)
        assert (workspace / "kopie" / "innen.txt").read_text(encoding="utf-8") == "drin"

    def test_delete_file(self, cfg: Config, workspace: Path):
        target = workspace / "weg.txt"
        target.write_text("x", encoding="utf-8")
        result = mod_files.delete(target, cfg, confirm=True)
        assert result["bytes_deleted"] == 1
        assert not target.exists()

    def test_delete_needs_confirmation(self, cfg: Config, workspace: Path):
        target = workspace / "weg.txt"
        target.write_text("x", encoding="utf-8")
        with pytest.raises(ConfirmationRequired):
            mod_files.delete(target, cfg, confirm=False)
        assert target.exists()  # unangetastet

    def test_delete_non_empty_dir_requires_recursive(self, cfg: Config, workspace: Path):
        d = workspace / "voll"
        d.mkdir()
        (d / "x.txt").write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="nicht leer"):
            mod_files.delete(d, cfg, confirm=True)
        assert d.exists()

    def test_delete_dir_recursive(self, cfg: Config, workspace: Path):
        d = workspace / "voll"
        (d / "unter").mkdir(parents=True)
        (d / "unter" / "x.txt").write_text("x", encoding="utf-8")
        result = mod_files.delete(d, cfg, recursive=True, confirm=True)
        assert result["items_deleted"] >= 2
        assert not d.exists()

    def test_outside_path_refused_for_delete(self, cfg: Config, tmp_path: Path):
        fremd = tmp_path / "fremd.txt"
        fremd.write_text("x", encoding="utf-8")
        with pytest.raises(Exception, match="verweigert"):
            mod_files.delete(fremd, cfg, confirm=True)
        assert fremd.exists()  # wirklich unangetastet