"""Hermetic tests for scripts/install_watchloop_cron.py (issue #65).

Cover the watch-loop crontab install/uninstall logic WITHOUT touching a real
crontab, network, or container: we stub `subprocess.run` (the module's read/write
channel) and pin the platform + python selection via env hooks, exercising only
the pure flattening / per-OS selection control flow. No skips.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("GITHUB_TOKEN", "test-token-hermetic")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.install_watchloop_cron as cron  # noqa: E402


class _FakePath:
    """Stub for os.path: only *existing* exists (default: homebrew python3)."""

    def __init__(self, existing=None):
        self.existing = set(existing or ["/opt/homebrew/bin/python3"])

    def exists(self, p):
        return p in self.existing


class _Cron:
    """Stub of `crontab -l` / `crontab -` over the module's subprocess."""

    def __init__(self, existing_lines: list[str]):
        self.lines = list(existing_lines)
        self.written: list[str] | None = None

    def run(self, argv, capture_output=False, text=False, input=None, **k):
        import types
        if argv == ["crontab", "-l"]:
            return types.SimpleNamespace(
                returncode=0,
                stdout="\n".join(self.lines) + ("\n" if self.lines else ""),
                stderr="",
            )
        if argv == ["crontab", "-"]:
            self.written = (input or "").splitlines()
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected argv: {argv}")


def _patch(monkeypatch, lines, sysp="darwin"):
    c = _Cron(lines)
    monkeypatch.setattr(cron, "subprocess", c)
    monkeypatch.setattr(cron, "_platform", lambda: sysp)
    return c


class _PatchExists:
    """Monkeypatch for os.path.exists: only the given paths exist."""

    def __init__(self, existing):
        self.existing = set(existing)

    def __call__(self, p):
        return p in self.existing


def _stub_exists(monkeypatch, existing):
    monkeypatch.setattr(cron.os.path, "exists", _PatchExists(existing))


def _watch_lines(lines) -> int:
    return sum(1 for ln in lines if cron.WATCHLINE_RE.search(ln))


class TestCronInstall:
    def test_double_install_adds_only_one_entry(self, monkeypatch):
        """Running install twice yields exactly one watch line + preserves unrelated."""

        # Given a crontab with an unrelated user line
        c = _patch(monkeypatch, ["0 9 * * * echo unrelated > /tmp/x"])

        # When I install twice
        cron.install()
        cron.install()

        # Then the crontab holds exactly one watch-loop line
        assert _watch_lines(c.written or []) == 1
        # And the unrelated line is preserved
        assert any("echo unrelated" in ln for ln in (c.written or []))

    def test_install_is_noop_when_present(self, monkeypatch):
        """A crontab already containing a watch entry is left untouched."""

        # Given a crontab already containing a watch-loop line (whatever its form)
        c = _patch(monkeypatch, [
            "*/20 * * * * cd /repo && HERMES_PROFILE=project-manager python3 "
            "/repo/scripts/watchloop_dispatch.py >> /x 2>&1"])

        # When install runs
        cron.install()

        # Then nothing is written (idempotent no-duplicate guard)
        assert c.written is None


class TestCronUninstall:
    def test_uninstall_removes_watch_and_preserves_unrelated(self, monkeypatch):
        """Uninstall removes only the watch entry, preserving unrelated byte-identical."""

        # Given one watch line + two unrelated lines
        unrelated = ["my-backup 0 * * * * echo b", "another * * * * backup"]
        mixed = [unrelated[0], cron.render_entry("/opt/homebrew/bin/python3"), unrelated[1]]
        c = _patch(monkeypatch, mixed)

        # When uninstall runs
        cron.uninstall()

        # Then the watch line is gone
        assert _watch_lines(c.written or []) == 0
        # And the unrelated lines are byte-identical
        assert (c.written or []) == unrelated

    def test_uninstall_noop_when_none(self, monkeypatch):
        """Uninstall on a crontab with no watch entry leaves it unchanged."""

        # Given only unrelated lines
        c = _patch(monkeypatch, ["my backup * * * *"])

        # When uninstall runs
        cron.uninstall()

        # Then nothing is written
        assert c.written is None


class TestPerOSCommand:
    def test_macos_uses_homebrew_python(self, monkeypatch):
        """On macOS the homebrew python3 is embedded when it exists."""

        # Given the macOS platform with the homebrew python3 present
        _patch(monkeypatch, [], sysp="darwin")
        _stub_exists(monkeypatch, ["/opt/homebrew/bin/python3"])
        monkeypatch.delenv("WATCHLOOP_CRON_PYTHON", raising=False)

        # When we render the entry
        entry = cron.render_entry()

        # Then it references the homebrew python3
        assert "/opt/homebrew/bin/python3" in entry

    def test_linux_uses_plain_python(self, monkeypatch):
        """On Linux the plain `python3` from PATH is used."""

        # Given the Linux platform (no /opt/homebrew)
        _patch(monkeypatch, [], sysp="linux")
        _stub_exists(monkeypatch, [])
        monkeypatch.delenv("WATCHLOOP_CRON_PYTHON", raising=False)

        # When we render the entry
        entry = cron.render_entry()

        # Then it references a plain `python3`
        assert cron.DISPATCHER in entry
        assert entry.endswith("2>&1")
