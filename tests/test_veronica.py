"""tests/test_veronica.py — does Veronica (core/veronica.py) actually
work? Exercises the real behaviors against real files in a sandboxed
tmp_path (not the real repo, not mocked-away) rather than just reading
the code and assuming: save a baseline, delete a file, restore it;
corrupt syntax, detect it; tamper a "firewall" component, confirm
HulkBuster gets triggered; contain a component, confirm the original
gets backed up and a working stub takes its place.
"""
import json
from unittest import mock

import pytest

import core.veronica as veronica_module


@pytest.fixture
def v(tmp_path, monkeypatch):
    """A real Veronica instance pointed at a throwaway two-component
    fixture repo instead of the real one -- same code, sandboxed data,
    so these tests prove the logic works without ever touching the
    actual FRIDAY source files."""
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "comp_a.py").write_text("x = 1\n")
    (tmp_path / "core" / "comp_b.py").write_text("y = 2\n")

    veronica_dir = tmp_path / "veronica_backups"
    monkeypatch.setattr(veronica_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(veronica_module, "VERONICA_DIR", veronica_dir)
    monkeypatch.setattr(veronica_module, "VERONICA_LOG", tmp_path / "logs" / "veronica.jsonl")
    monkeypatch.setattr(veronica_module, "BASELINE_FILE", veronica_dir / "baseline_hashes.json")
    monkeypatch.setattr(veronica_module, "FRIDAY_COMPONENTS", {
        "comp_a": "core/comp_a.py",
        "comp_b": "core/comp_b.py",
    })
    monkeypatch.setattr(veronica_module, "FIREWALL_COMPONENTS", {"comp_b"})

    return veronica_module.Veronica()


class TestSaveBaselines:
    def test_creates_a_backup_copy_of_every_component(self, v, tmp_path):
        result = v.save_baselines()

        assert result["saved"] == 2
        assert set(result["components"]) == {"comp_a", "comp_b"}
        backup_a = tmp_path / "veronica_backups" / "comp_a_backup.py"
        assert backup_a.read_text() == "x = 1\n"

    def test_writes_baseline_hash_file(self, v, tmp_path):
        v.save_baselines()
        baseline_file = tmp_path / "veronica_backups" / "baseline_hashes.json"
        assert baseline_file.exists()
        data = json.loads(baseline_file.read_text())
        assert set(data["baselines"].keys()) == {"comp_a", "comp_b"}


class TestSelfTest:
    def test_reports_nominal_when_everything_is_fine(self, v):
        v.save_baselines()
        result = v.self_test()
        assert result["all_systems"] == "NOMINAL"
        assert result["components"]["comp_a"]["exists"] is True
        assert result["components"]["comp_a"]["syntax"] is True
        assert result["components"]["comp_a"]["backed_up"] is True

    def test_reports_degraded_when_a_file_is_missing(self, v, tmp_path):
        v.save_baselines()
        (tmp_path / "core" / "comp_a.py").unlink()

        result = v.self_test()

        assert result["all_systems"] == "DEGRADED"
        assert result["components"]["comp_a"]["exists"] is False

    def test_reports_degraded_on_a_syntax_error(self, v, tmp_path):
        v.save_baselines()
        (tmp_path / "core" / "comp_a.py").write_text("def broken(:\n")

        result = v.self_test()

        assert result["all_systems"] == "DEGRADED"
        assert result["components"]["comp_a"]["syntax"] is False


class TestMonitorRestoresFromBackup:
    def test_restores_a_missing_component_from_its_backup(self, v, tmp_path):
        v.save_baselines()
        live = tmp_path / "core" / "comp_a.py"
        live.unlink()

        health = v.monitor()

        assert live.exists()
        assert live.read_text() == "x = 1\n"
        assert health["repaired"] == 1
        assert health["status"]["comp_a"] == "MISSING"

    def test_restores_a_component_with_bad_syntax_from_backup(self, v, tmp_path):
        v.save_baselines()
        live = tmp_path / "core" / "comp_a.py"
        live.write_text("def broken(:\n")

        health = v.monitor()

        assert live.read_text() == "x = 1\n"
        assert health["repaired"] == 1

    def test_no_backup_available_alerts_instead_of_improvising(self, v, tmp_path):
        """The whole point documented in veronica.py's module docstring:
        no backup means alert, never a guessed replacement."""
        live = tmp_path / "core" / "comp_a.py"
        live.unlink()  # never called save_baselines() -- no backup exists

        health = v.monitor()

        assert not live.exists()  # nothing was improvised into existence
        assert health["repaired"] == 0
        assert health["damaged"] == 1

    def test_nominal_when_nothing_is_wrong(self, v):
        v.save_baselines()
        health = v.monitor()
        assert health["damaged"] == 0
        assert health["repaired"] == 0
        assert all(status == "NOMINAL" for status in health["status"].values())


class TestFirewallTamperTriggersHulkbuster:
    def test_modified_firewall_component_triggers_hulkbuster(self, v, tmp_path):
        v.save_baselines()
        (tmp_path / "core" / "comp_b.py").write_text("y = 999  # tampered\n")

        with mock.patch("services.hulkbuster.hulkbuster") as hb:
            health = v.monitor()

        hb.deploy.assert_called_once()
        assert "comp_b" in hb.deploy.call_args.kwargs.get("reason", "") or \
               "comp_b" in str(hb.deploy.call_args)
        assert health["status"]["comp_b"] == "MODIFIED"

    def test_modified_non_firewall_component_does_not_trigger_hulkbuster(self, v, tmp_path):
        """comp_a isn't in FIREWALL_COMPONENTS -- a modification there is
        just a status line, not an escalation."""
        v.save_baselines()
        (tmp_path / "core" / "comp_a.py").write_text("x = 999  # changed\n")

        with mock.patch("services.hulkbuster.hulkbuster") as hb:
            health = v.monitor()

        hb.deploy.assert_not_called()
        assert health["status"]["comp_a"] == "MODIFIED"


class TestDeployReplacement:
    def test_restores_the_named_component(self, v, tmp_path):
        v.save_baselines()
        (tmp_path / "core" / "comp_a.py").write_text("corrupted")

        result = v.deploy_replacement("comp_a", "manual")

        assert result["repaired"] is True
        assert (tmp_path / "core" / "comp_a.py").read_text() == "x = 1\n"

    def test_unknown_component_is_rejected(self, v):
        result = v.deploy_replacement("not_a_real_component", "manual")
        assert result["repaired"] is False
        assert "unknown component" in result["reason"]

    def test_missing_backup_is_reported_not_improvised(self, v):
        result = v.deploy_replacement("comp_a", "manual")  # no save_baselines() call
        assert result["repaired"] is False
        assert "no backup" in result["reason"]


class TestContainFailingComponent:
    def test_backs_up_original_and_installs_a_stub(self, v, tmp_path):
        original = (tmp_path / "core" / "comp_a.py").read_text()

        result = v.contain_failing_component("comp_a")

        assert result["contained"] is True
        backup = tmp_path / "veronica_backups" / "comp_a_pre_containment.py"
        assert backup.read_text() == original
        live_content = (tmp_path / "core" / "comp_a.py").read_text()
        assert "CONTAINMENT STUB" in live_content
        assert "comp_a" in live_content

    def test_stub_is_valid_python(self, v, tmp_path):
        """The replacement has to actually import cleanly, or containing
        a broken component just breaks it a different way."""
        v.contain_failing_component("comp_a")
        import py_compile
        py_compile.compile(str(tmp_path / "core" / "comp_a.py"), doraise=True)

    def test_unknown_component_is_rejected(self, v):
        result = v.contain_failing_component("not_a_real_component")
        assert result["contained"] is False


class TestGetStatus:
    def test_reflects_real_backup_and_repair_counts(self, v, tmp_path):
        v.save_baselines()
        (tmp_path / "core" / "comp_a.py").unlink()
        v.monitor()

        status = v.get_status()

        assert status["baselines_saved"] is True
        assert status["components_backed_up"] == 2
        assert status["repairs_performed"] == 1
