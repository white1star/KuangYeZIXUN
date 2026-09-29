from pathlib import Path

from crawler.rules_version import compute_rules_version


def _cfg(tmp_path: Path) -> Path:
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "a.yaml").write_text("key: a\n", encoding="utf-8")
    (tmp_path / "tags.yaml").write_text("矿种: []\n", encoding="utf-8")
    return tmp_path


def test_same_content_same_version(tmp_path):
    d = _cfg(tmp_path)
    assert compute_rules_version(d) == compute_rules_version(d)


def test_changed_content_changes_version(tmp_path):
    d = _cfg(tmp_path)
    before = compute_rules_version(d)
    (d / "sources" / "a.yaml").write_text("key: a\nurl: x\n", encoding="utf-8")
    assert compute_rules_version(d) != before


def test_new_file_changes_version(tmp_path):
    d = _cfg(tmp_path)
    before = compute_rules_version(d)
    (d / "sources" / "b.yaml").write_text("key: b\n", encoding="utf-8")
    assert compute_rules_version(d) != before


def test_version_is_stable_and_prefixed(tmp_path):
    v = compute_rules_version(_cfg(tmp_path))
    assert v.startswith("rv-") and len(v) == 13  # rv- + 10 位十六进制


def test_missing_dir_returns_unknown(tmp_path):
    assert compute_rules_version(tmp_path / "nope") == "rv-unknown"
