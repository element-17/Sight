"""
发版版本计算、Release Notes 生成与运行时路径解析单元测试
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.paths import get_bundle_dir, get_runtime_dir, is_frozen
from app.version import get_version
from scripts.next_version import (
    CommitInfo,
    build_release_plan,
    compute_next_tag,
    determine_bump,
    format_release_notes,
    has_skip_marker,
    highest_semver_tag,
    validate_manual_tag,
)


class ReleaseVersioningTests(unittest.TestCase):
    def test_highest_semver_tag_sorts_numerically(self):
        tags = ["v0.1.0", "v0.2.0", "v0.10.0", "v0.9.5", "not-a-tag", "v1.0.0-rc.1"]
        self.assertEqual(highest_semver_tag(tags), "v0.10.0")
        self.assertEqual(highest_semver_tag(tags, exclude="v0.10.0"), "v0.9.5")

    def test_determine_bump_patch_minor_major(self):
        self.assertEqual(
            determine_bump([CommitInfo("1111111", "fix(api): handle timeout")]),
            "patch",
        )
        self.assertEqual(
            determine_bump([CommitInfo("1111111", "docs: update readme")]),
            "patch",
        )
        self.assertEqual(
            determine_bump([
                CommitInfo("1111111", "fix: minor fix"),
                CommitInfo("2222222", "feat(github): add adapter"),
            ]),
            "minor",
        )
        self.assertEqual(
            determine_bump([
                CommitInfo("1111111", "feat!: drop legacy api"),
            ]),
            "major",
        )
        self.assertEqual(
            determine_bump([
                CommitInfo("1111111", "refactor: rewrite storage", "BREAKING CHANGE: schema changed"),
            ]),
            "major",
        )

    def test_compute_next_tag_and_collision_avoidance(self):
        tag, clean, bump = compute_next_tag("v0.1.0", [CommitInfo("aaaaaaa", "feat: new feature")])
        self.assertEqual((tag, clean, bump), ("v0.2.0", "0.2.0", "minor"))

        tag, clean, bump = compute_next_tag(
            "v0.1.0",
            [CommitInfo("bbbbbbb", "fix: bug")],
            existing_tags={"v0.1.0", "v0.1.1"},
        )
        self.assertEqual((tag, clean, bump), ("v0.1.2", "0.1.2", "patch"))

        tag, clean, bump = compute_next_tag("", [CommitInfo("ccccccc", "feat: init")])
        self.assertEqual((tag, clean, bump), ("v0.1.0", "0.1.0", "initial"))

    def test_skip_release_marker(self):
        self.assertTrue(has_skip_marker(CommitInfo("1111111", "docs: typo [skip release]")))
        self.assertTrue(has_skip_marker(CommitInfo("1111111", "chore: lint", "note [no release]")))
        self.assertFalse(has_skip_marker(CommitInfo("1111111", "feat: regular update")))

    def test_validate_manual_tag(self):
        self.assertEqual(validate_manual_tag("0.3.0"), ("v0.3.0", "0.3.0"))
        self.assertEqual(validate_manual_tag("v1.2.3-rc.1"), ("v1.2.3-rc.1", "1.2.3-rc.1"))
        with self.assertRaises(ValueError):
            validate_manual_tag("invalid-version")

    def test_format_release_notes_groups_commits(self):
        commits = [
            CommitInfo("abcdef1234", "feat(github): add github adapter"),
            CommitInfo("1234567890", "fix: close sqlite handle"),
            CommitInfo("9999999999", "docs: polish README"),
        ]
        notes = format_release_notes("v0.2.0", "v0.1.0", commits, repo="element-17/Sight")
        self.assertIn("## Sight v0.2.0", notes)
        self.assertIn("### ✨ 新功能 (Features)", notes)
        self.assertIn("**github**: add github adapter (`abcdef1`)", notes)
        self.assertIn("### 🐛 问题修复 (Bug Fixes)", notes)
        self.assertIn("Sight-v0.2.0-windows-x64.zip", notes)
        self.assertIn("Sight-v0.2.0-macos-arm64.tar.gz", notes)
        self.assertIn("Sight-v0.2.0-linux-x64.tar.gz", notes)
        self.assertIn("https://github.com/element-17/Sight/compare/v0.1.0...v0.2.0", notes)

    def test_build_release_plan_skip_and_non_ancestor_fallback(self):
        with mock.patch("scripts.next_version._list_git_tags") as mock_tags, \
             mock.patch("scripts.next_version._list_git_commits") as mock_commits, \
             mock.patch("scripts.next_version._is_ancestor", return_value=False), \
             mock.patch("scripts.next_version._commit_timestamp", return_value=1700000000):
            mock_tags.side_effect = [
                ["v0.1.0"],  # all_tags
                [],          # merged_tags (non-ancestor tag)
                [],          # head_tags
            ]
            mock_commits.side_effect = [
                [CommitInfo("abc1234", "feat: new feature")],  # head_commits
                [CommitInfo("abc1234", "feat: new feature")],  # commits since ts+1
            ]
            plan = build_release_plan(Path("."), event="push")
            self.assertTrue(plan.should_release)
            self.assertEqual(plan.prev_tag, "v0.1.0")
            self.assertEqual(plan.tag, "v0.2.0")
            self.assertEqual(plan.bump, "minor")
            _, kwargs = mock_commits.call_args_list[1]
            self.assertEqual(kwargs.get("since_ts"), 1700000001)

        with mock.patch("scripts.next_version._list_git_tags") as mock_tags, \
             mock.patch("scripts.next_version._list_git_commits") as mock_commits:
            mock_tags.side_effect = [["v0.2.0"], ["v0.2.0"], []]
            mock_commits.return_value = [CommitInfo("def5678", "docs: typo [skip release]")]
            plan = build_release_plan(Path("."), event="push")
            self.assertFalse(plan.should_release)
            self.assertIn("skip release", plan.skip_reason)


class RuntimePathsTests(unittest.TestCase):
    def test_source_mode_paths(self):
        self.assertFalse(is_frozen())
        repo_root = Path(__file__).resolve().parent.parent
        self.assertEqual(get_bundle_dir(), repo_root)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIGHT_DATA_DIR", None)
            self.assertEqual(get_runtime_dir(), repo_root)

    def test_env_override_runtime_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"SIGHT_DATA_DIR": tmp}):
                self.assertEqual(get_runtime_dir(), Path(tmp).resolve())

    def test_frozen_mode_paths_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            meipass = root / "_internal"
            (meipass / "app").mkdir(parents=True)
            (meipass / "app" / "VERSION").write_text("0.2.0\n", encoding="utf-8")
            fake_exe = root / "Sight.exe"

            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "_MEIPASS", str(meipass), create=True), \
                 mock.patch.object(sys, "executable", str(fake_exe)), \
                 mock.patch.dict(os.environ, {"SIGHT_DATA_DIR": ""}):
                self.assertTrue(is_frozen())
                self.assertEqual(get_bundle_dir(), meipass)
                self.assertEqual(get_runtime_dir(), root)
                self.assertEqual(get_version(), "0.2.0")


if __name__ == "__main__":
    unittest.main()
