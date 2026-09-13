"""Where an installed copy keeps its data, and whether it reads its keys.

Both of these were silent failures rather than loud ones, which is what makes them
worth pinning: a product that ignores the `.env` it told you to write looks exactly
like a free tier that is not working.
"""

from __future__ import annotations

import os

import pytest

from vc_alpha import env, paths


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("VC_ALPHA_HOME", "VC_ALPHA_DB"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(env, "_loaded", False)


def test_explicit_home_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("VC_ALPHA_HOME", str(tmp_path))
    assert paths.home() == tmp_path
    assert paths.db_path() == tmp_path / "data" / "candidates.sqlite"
    assert paths.config_dir() == tmp_path / "config" / "theses"


def test_checkout_is_detected(tmp_path, monkeypatch):
    """Running from a working copy keeps using that working copy's data."""
    (tmp_path / "vc_alpha").mkdir()
    (tmp_path / "vc_alpha" / "__init__.py").touch()
    monkeypatch.chdir(tmp_path)
    assert paths.in_checkout(tmp_path)
    assert paths.home() == tmp_path


def test_elsewhere_falls_back_to_the_installed_location(tmp_path, monkeypatch):
    """The bug this exists to prevent: `vc-alpha` run from any other directory.

    It used to create a fresh empty database wherever the shell happened to be and
    report no funds configured, because every default path was relative.
    """
    monkeypatch.chdir(tmp_path)
    assert not paths.in_checkout(tmp_path)
    assert paths.home() == paths.FALLBACK
    assert paths.db_path() == paths.FALLBACK / "data" / "candidates.sqlite"


def test_vc_alpha_db_still_overrides(tmp_path, monkeypatch):
    """CI and the tests set this directly; it has to keep winning."""
    monkeypatch.setenv("VC_ALPHA_HOME", str(tmp_path))
    monkeypatch.setenv("VC_ALPHA_DB", str(tmp_path / "other.sqlite"))
    assert paths.db_path() == tmp_path / "other.sqlite"


def test_ensure_creates_the_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("VC_ALPHA_HOME", str(tmp_path))
    paths.ensure()
    for d in (paths.data_dir(), paths.config_dir(), paths.reports_dir(),
              paths.whatsapp_dir(), paths.inbox_dir()):
        assert d.is_dir()


def test_env_file_is_read(tmp_path, monkeypatch):
    monkeypatch.setenv("VC_ALPHA_HOME", str(tmp_path))
    monkeypatch.delenv("VC_ALPHA_TEST_KEY", raising=False)
    (tmp_path / ".env").write_text("VC_ALPHA_TEST_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)

    env.load(force=True)
    assert os.environ["VC_ALPHA_TEST_KEY"] == "from-file"
    monkeypatch.delenv("VC_ALPHA_TEST_KEY")


def test_a_real_environment_variable_beats_the_file(tmp_path, monkeypatch):
    """So `GROQ_API_KEY=... vc-alpha run` and CI secrets keep working."""
    monkeypatch.setenv("VC_ALPHA_HOME", str(tmp_path))
    monkeypatch.setenv("VC_ALPHA_TEST_KEY", "from-shell")
    (tmp_path / ".env").write_text("VC_ALPHA_TEST_KEY=from-file\n")
    monkeypatch.chdir(tmp_path)

    env.load(force=True)
    assert os.environ["VC_ALPHA_TEST_KEY"] == "from-shell"
