"""
全平台真实线上抓取测试 (Live Scraping Integration Tests)

当设置环境变量 SIGHT_LIVE_TEST=1 时激活，对每个已注册平台执行真实网络抓取测试；
若同时设置 SIGHT_LIVE_STRICT=1，则要求所有平台（含需 Cookie 的平台）必须 100% PASS。
"""
import os
import unittest

from app.platforms import known_platform_ids
from scripts.verify_live_scraping import _maybe_inject_ci_accounts, probe_platform

LIVE_ENABLED = os.environ.get("SIGHT_LIVE_TEST", "").strip() in ("1", "true", "yes")
LIVE_STRICT = os.environ.get("SIGHT_LIVE_STRICT", "").strip() in ("1", "true", "yes")


@unittest.skipUnless(LIVE_ENABLED, "未启用线上真实抓取测试（设置 SIGHT_LIVE_TEST=1 启用）")
class LivePlatformScrapingTests(unittest.TestCase):
    """逐平台执行线上真实抓取验证"""

    @classmethod
    def setUpClass(cls):
        _maybe_inject_ci_accounts()

    def _assert_platform_live(self, pid: str):
        res = probe_platform(pid)
        if LIVE_STRICT:
            self.assertEqual(
                res["status"],
                "PASS",
                f"[{pid}] 严格模式下线上抓取未通过: status={res['status']}, detail={res['detail']}",
            )
        else:
            self.assertNotEqual(
                res["status"],
                "FAIL",
                f"[{pid}] 线上抓取发生代码/协议错误: {res['detail']}",
            )
            if pid == "github":
                self.assertEqual(
                    res["status"],
                    "PASS",
                    f"[github] 线上公开 API 抓取必须通过: {res['detail']}",
                )

    def test_live_netease_scraping(self):
        self._assert_platform_live("netease")

    def test_live_bilibili_scraping(self):
        self._assert_platform_live("bilibili")

    def test_live_douyin_scraping(self):
        self._assert_platform_live("douyin")

    def test_live_qqmusic_scraping(self):
        self._assert_platform_live("qqmusic")

    def test_live_weibo_scraping(self):
        self._assert_platform_live("weibo")

    def test_live_genshin_scraping(self):
        self._assert_platform_live("genshin")

    def test_live_xhs_scraping(self):
        self._assert_platform_live("xhs")

    def test_live_github_scraping(self):
        self._assert_platform_live("github")

    def test_all_registered_platforms_covered_by_live_tests(self):
        for pid in known_platform_ids():
            self.assertTrue(
                hasattr(self, f"test_live_{pid}_scraping"),
                f"平台 {pid} 缺少对应的 test_live_{pid}_scraping 线上抓取测试方法",
            )


if __name__ == "__main__":
    unittest.main()
