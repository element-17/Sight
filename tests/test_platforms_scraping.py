"""
全平台抓取功能契约与解析测试套件 (CI/CD 必跑)

覆盖所有已注册平台 (netease, bilibili, douyin, qqmusic, weibo, genshin, xhs, github)：
1. 注册表完整性校验：任何新增平台若未在此测试套件中编写抓取测试，CI 直接失败。
2. 各平台核心抓取链路测试：
   - 签名/加密/SSR 解码器真实执行（网易云 weapi AES+RSA、抖音 DouyinAuth/JS 签名、小红书 XHSPcAuth、QQ音乐 g_tk/JSONP/SSR 双重解码）
   - search_user / get_profile / get_content_lists / get_content_detail / get_history / get_events / get_follows / get_followers / refresh_user_info / check_alive / get_login_user
   - 错误处理契约：风控、登录失效、接口异常一律 raise RuntimeError，不伪装成空列表；用户不存在 (404) get_profile 返回 None。
3. REST 聚合接口 (/api/<platform>/search 与 /api/<platform>/all) 全平台端到端连通性验证。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from flask import Flask

from app.credentials import CredentialManager, PLATFORMS
from app.data.store import DataStore
from app.platforms import get_adapter, get_pool, known_platform_ids
from app.platforms.base import ContentItem, EventItem, MediaEntry, PlatformProfile
from app.platforms.bilibili.adapter import BilibiliAdapter
from app.platforms.douyin.adapter import DouyinAdapter
from app.platforms.genshin.adapter import GenshinAdapter, detect_server
from app.platforms.github.adapter import GitHubAdapter
from app.platforms.netease.adapter import NeteaseAdapter
from app.platforms.netease.crypto import encrypt_request
from app.platforms.qqmusic.adapter import QQMusicAdapter
from app.platforms.weibo.adapter import WeiboAdapter
from app.platforms.xhs.adapter import XhsAdapter
from app.services.timeline import TimelineBuilder


TESTED_PLATFORMS = {
    "netease",
    "bilibili",
    "douyin",
    "qqmusic",
    "weibo",
    "genshin",
    "xhs",
    "github",
}


class PlatformRegistryContractTests(unittest.TestCase):
    """确保所有已注册平台在各模块配置一致，且都有对应的抓取测试"""

    def test_all_registered_platforms_have_scraping_tests(self):
        registered = set(known_platform_ids())
        self.assertEqual(
            registered,
            TESTED_PLATFORMS,
            f"平台注册表与抓取测试覆盖集合不一致: registered={registered}, tested={TESTED_PLATFORMS}",
        )
        self.assertEqual(set(PLATFORMS), TESTED_PLATFORMS)

    def test_every_platform_has_adapter_pool_and_timeline_mapping(self):
        for pid in known_platform_ids():
            with self.subTest(platform=pid):
                adapter = get_adapter(pid)
                pool = get_pool(pid)
                self.assertIsNotNone(adapter, f"{pid} 未注册适配器")
                self.assertIsNotNone(pool, f"{pid} 未注册账号池")
                self.assertEqual(adapter.platform_id, pid)
                self.assertIn(pid, TimelineBuilder.PLATFORM_NAME_MAP)
                self.assertIn(pid, TimelineBuilder.CONTENT_TYPE_MAP)

    def test_cookie_parser_supports_cookies_and_tokens(self):
        self.assertEqual(
            CredentialManager.parse_cookie_str("a=1; b=hello=world"),
            {"a": "1", "b": "hello=world"},
        )
        self.assertEqual(
            CredentialManager.parse_cookie_str("ghp_1234567890abcdef"),
            {"token": "ghp_1234567890abcdef"},
        )
        self.assertEqual(
            CredentialManager.parse_cookie_str("Bearer github_pat_abc_123"),
            {"token": "github_pat_abc_123"},
        )
        self.assertEqual(
            CredentialManager.parse_cookie_str("Authorization=Bearer ghp_xyz; dotcom_user=octocat"),
            {"token": "ghp_xyz", "dotcom_user": "octocat"},
        )


class NeteaseScrapingTests(unittest.TestCase):
    """网易云音乐抓取功能测试"""

    def setUp(self):
        self.adapter = NeteaseAdapter(credentials={"MUSIC_U": "mock_music_u"})
        self.client_mock = MagicMock()
        self.adapter._client = self.client_mock

    def test_weapi_crypto_generates_valid_encrypted_payload(self):
        encrypted = encrypt_request({"s": "测试", "type": 1002, "limit": 20, "offset": 0})
        self.assertIn("params", encrypted)
        self.assertIn("encSecKey", encrypted)
        self.assertTrue(len(encrypted["params"]) > 32)
        self.assertEqual(len(encrypted["encSecKey"]), 256)

    def test_search_profile_playlists_history_events_and_social(self):
        def fake_weapi_post(endpoint, data):
            if endpoint == "/weapi/search/get":
                return {
                    "code": 200,
                    "result": {
                        "userprofiles": [
                            {
                                "userId": 1001,
                                "nickname": "网易测试歌手",
                                "avatarUrl": "https://p1.music.126.net/a.jpg",
                                "signature": "独立音乐人",
                                "gender": 1,
                                "vipType": 11,
                                "followeds": 5200,
                                "authStatus": 1,
                            }
                        ]
                    },
                }
            if endpoint == "/weapi/v1/user/detail/1001":
                return {
                    "code": 200,
                    "profile": {
                        "userId": 1001,
                        "nickname": "网易测试歌手",
                        "avatarUrl": "https://p1.music.126.net/a.jpg",
                        "backgroundUrl": "https://p1.music.126.net/bg.jpg",
                        "signature": "独立音乐人",
                        "gender": 1,
                        "vipType": 11,
                        "createTime": 1600000000000,
                        "followeds": 5200,
                        "follows": 42,
                        "eventCount": 12,
                        "playlistCount": 5,
                        "authStatus": 1,
                    },
                }
            if endpoint == "/weapi/user/level":
                return {"code": 200, "data": {"level": 9, "listenSongs": 12345}}
            if endpoint == "/weapi/subcount":
                return {"code": 200, "createdPlaylistCount": 5, "subPlaylistCount": 3}
            if endpoint == "/weapi/user/playlist":
                return {
                    "code": 200,
                    "more": False,
                    "playlist": [
                        {
                            "id": 9001,
                            "name": "我喜欢的音乐",
                            "coverImgUrl": "https://p1.music.126.net/pl.jpg",
                            "trackCount": 88,
                            "playCount": 1024,
                            "creator": {"nickname": "网易测试歌手"},
                            "description": "测试歌单描述",
                            "subscribed": False,
                            "createTime": 1700000000000,
                            "subscribedCount": 15,
                            "userId": 1001,
                        }
                    ],
                }
            if endpoint == "/weapi/v6/playlist/detail":
                return {
                    "code": 200,
                    "playlist": {
                        "name": "我喜欢的音乐",
                        "coverImgUrl": "https://p1.music.126.net/pl.jpg",
                        "trackCount": 1,
                        "playCount": 1024,
                        "description": "详情描述",
                        "creator": {"nickname": "网易测试歌手"},
                        "createTime": 1700000000000,
                        "subscribedCount": 15,
                        "tracks": [
                            {
                                "id": 5001,
                                "name": "晴天",
                                "ar": [{"name": "周杰伦"}],
                                "al": {"name": "叶惠美", "picUrl": "https://p1.music.126.net/s.jpg"},
                                "dt": 269000,
                            }
                        ],
                    },
                }
            if endpoint == "/weapi/v1/play/record":
                return {
                    "code": 200,
                    "allData": [
                        {
                            "playCount": 55,
                            "score": 100,
                            "song": {
                                "id": 5001,
                                "name": "晴天",
                                "ar": [{"name": "周杰伦"}],
                                "al": {"name": "叶惠美", "picUrl": "https://p1.music.126.net/s.jpg"},
                                "dt": 269000,
                            },
                        }
                    ],
                }
            if endpoint == "/weapi/event/get/1001":
                return {
                    "code": 200,
                    "more": False,
                    "events": [
                        {
                            "id": 7001,
                            "eventTime": 1700000000000,
                            "info": {"type": 18, "pics": []},
                            "json": json.dumps(
                                {
                                    "msg": "分享单曲",
                                    "song": {"name": "晴天", "artists": [{"name": "周杰伦"}]},
                                }
                            ),
                        }
                    ],
                }
            if endpoint == "/weapi/user/getfollows/1001":
                return {
                    "code": 200,
                    "more": False,
                    "follow": [
                        {"userId": 2001, "nickname": "关注对象A", "avatarUrl": "", "signature": "sig", "userType": 4}
                    ],
                }
            if endpoint == "/weapi/user/getfolloweds/1001":
                return {
                    "code": 200,
                    "more": False,
                    "followeds": [
                        {"userId": 3001, "nickname": "粉丝对象B", "avatarUrl": "", "signature": "sig", "authStatus": 0}
                    ],
                }
            raise AssertionError(f"Unexpected endpoint: {endpoint}")

        self.client_mock.weapi_post.side_effect = fake_weapi_post
        self.client_mock.api_get.return_value = {"profile": {"userId": 1001, "nickname": "网易测试歌手"}}

        self.assertTrue(self.adapter.check_alive())
        self.assertEqual(self.adapter.get_login_user()["uid"], "1001")

        users = self.adapter.search_user("测试")
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["uid"], "1001")
        self.assertTrue(users[0]["is_verified"])

        profile = self.adapter.get_profile("1001")
        self.assertIsInstance(profile, PlatformProfile)
        self.assertEqual(profile.nickname, "网易测试歌手")
        self.assertEqual(profile.level, 9)
        self.assertEqual(profile.extra["listenSongs"], 12345)

        playlists = self.adapter.get_content_lists("1001")
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0].item_id, "9001")

        detail = self.adapter.get_content_detail("9001")
        self.assertEqual(detail["items"][0]["title"], "晴天")

        history = self.adapter.get_history("1001", "all")
        self.assertEqual(len(history), 1)
        self.assertIsInstance(history[0], MediaEntry)
        self.assertEqual(history[0].play_count, 55)

        events = self.adapter.get_events("1001")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].media_title, "晴天")

        follows, more, total = self.adapter.get_follows("1001")
        self.assertEqual(len(follows), 1)
        self.assertFalse(more)
        self.assertEqual(total, -1)
        self.assertTrue(follows[0]["is_verified"])

        followers, _, _ = self.adapter.get_followers("1001")
        self.assertEqual(followers[0]["uid"], "3001")

        refreshed = self.adapter.refresh_user_info("1001")
        self.assertEqual(refreshed["fans"], 5200)
        self.assertTrue(refreshed["is_verified"])

    def test_expired_cookie_on_social_raises_runtime_error(self):
        self.client_mock.weapi_post.return_value = {"code": 301, "msg": "需要登录"}
        with self.assertRaisesRegex(RuntimeError, "登录态已失效"):
            self.adapter.get_followers("1001")

    def test_check_alive_handles_null_profile_without_crashing(self):
        self.client_mock.api_get.return_value = {"code": 200, "account": None, "profile": None}
        self.assertFalse(self.adapter.check_alive())
        self.assertIsNone(self.adapter.get_login_user())


class BilibiliScrapingTests(unittest.TestCase):
    """哔哩哔哩抓取功能测试"""

    def setUp(self):
        self.adapter = BilibiliAdapter()
        self.rate_patch = patch.object(self.adapter, "_rate_limit", return_value=None)
        self.rate_patch.start()
        self.addCleanup(self.rate_patch.stop)

    def test_search_profile_videos_events_and_social_pagination(self):
        def fake_get(endpoint, params=None):
            params = params or {}
            if endpoint == "/x/web-interface/search/type":
                return {
                    "result": [
                        {
                            "mid": 946974,
                            "uname": "影视飓风",
                            "upic": "//i0.hdslb.com/bfs/face/a.jpg",
                            "usign": "无限进步",
                            "gender": "男",
                            "vip": {"status": 1},
                            "official_verify": {"type": 0},
                            "fans": 10000000,
                            "videos": 350,
                        }
                    ]
                }
            if endpoint == "/x/space/acc/info":
                return {
                    "mid": 946974,
                    "name": "影视飓风",
                    "face": "https://i0.hdslb.com/bfs/face/a.jpg",
                    "top_photo": "",
                    "sign": "无限进步",
                    "sex": "男",
                    "level": 6,
                    "follower": 10000000,
                    "following": 120,
                    "vip": {"status": 1},
                    "official": {"title": "bilibili 知名科技UP主"},
                    "live_room": {"liveStatus": 0},
                }
            if endpoint == "/x/space/upstat":
                return {"archive": {"view": 500000000}, "article": {"view": 1000}, "likes": 40000000}
            if endpoint == "/x/space/arc/search":
                return {
                    "list": {
                        "vlist": [
                            {
                                "aid": 11001,
                                "bvid": "BV1xx411c7mD",
                                "title": "测试投稿视频",
                                "pic": "https://i0.hdslb.com/bfs/archive/v.jpg",
                                "play": 99999,
                                "author": "影视飓风",
                                "description": "视频简介",
                                "created": 1700000000,
                                "length": "12:34",
                                "comment": 500,
                                "video_review": 1200,
                            }
                        ]
                    }
                }
            if endpoint == "/x/web-interface/view":
                return {
                    "title": "测试投稿视频",
                    "pic": "https://i0.hdslb.com/bfs/archive/v.jpg",
                    "stat": {"view": 99999, "favorite": 3000},
                    "desc": "视频详情",
                    "owner": {"name": "影视飓风"},
                    "pubdate": 1700000000,
                }
            if endpoint == "/x/polymer/web-dynamic/v1/feed/space":
                return {
                    "items": [
                        {
                            "id_str": "dyn_1",
                            "type": "DYNAMIC_TYPE_AV",
                            "modules": {
                                "module_author": {"name": "影视飓风", "pub_ts": 1700000000},
                                "module_dynamic": {
                                    "desc": {"text": "发了新视频"},
                                    "major": {"archive": {"title": "测试投稿视频"}},
                                },
                                "module_stat": {
                                    "like": {"count": 100},
                                    "comment": {"count": 20},
                                    "forward": {"count": 5},
                                },
                            },
                        }
                    ],
                    "offset": "",
                }
            if endpoint in ("/x/relation/followings", "/x/relation/followers"):
                return {
                    "total": 3,
                    "list": [
                        {"mid": 1, "uname": "用户1", "face": "", "sign": "s1", "official_verify": {"type": -1}},
                        {"mid": 2, "uname": "用户2", "face": "", "sign": "s2", "official_verify": {"type": 0}},
                        {"mid": 3, "uname": "用户3", "face": "", "sign": "s3", "official_verify": {"type": 1}},
                    ],
                }
            raise AssertionError(f"Unexpected endpoint: {endpoint}")

        with patch.object(self.adapter, "_get", side_effect=fake_get):
            users = self.adapter.search_user("影视飓风")
            self.assertEqual(users[0]["uid"], "946974")
            self.assertTrue(users[0]["is_verified"])

            profile = self.adapter.get_profile("946974")
            self.assertEqual(profile.nickname, "影视飓风")
            self.assertEqual(profile.extra["likes"], 40000000)

            videos = self.adapter.get_content_lists("946974")
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0].extra["bvid"], "BV1xx411c7mD")

            detail = self.adapter.get_content_detail("11001")
            self.assertEqual(detail["viewCount"], 99999)

            events = self.adapter.get_events("946974")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "投稿视频")

            # 测试 skip=1 跳过第 1 条
            follows, more, total = self.adapter.get_follows("946974", limit=2, skip=1)
            self.assertEqual([u["uid"] for u in follows], ["2", "3"])
            self.assertFalse(more)
            self.assertEqual(total, 3)

            refreshed = self.adapter.refresh_user_info("946974")
            self.assertEqual(refreshed["fans"], 10000000)
            self.assertTrue(refreshed["is_verified"])

    def test_business_error_raises_runtime_error(self):
        mock_resp = Mock(status_code=200, text='{"code": -404, "message": "啥都木有"}')
        mock_resp.json.return_value = {"code": -404, "message": "啥都木有"}
        with patch.object(self.adapter.session, "get", return_value=mock_resp):
            with self.assertRaisesRegex(RuntimeError, "code=-404"):
                self.adapter.get_profile("999999999")


class DouyinScrapingTests(unittest.TestCase):
    """抖音抓取与签名栈测试"""

    def setUp(self):
        self.adapter = DouyinAdapter()
        self.rate_patch = patch.object(self.adapter, "_rate_limit", return_value=None)
        self.rate_patch.start()
        self.addCleanup(self.rate_patch.stop)

    def test_douyin_auth_and_abogus_signature_stack(self):
        from app.platforms.douyin.ref_builder.auth import DouyinAuth
        from app.platforms.douyin.ref_utils.dy_util import generate_a_bogus

        auth = DouyinAuth()
        auth.perepare_auth("sessionid=test_sid; ttwid=test_ttwid;odin_tt=test_odin")
        self.assertIn("sessionid", auth.cookie)
        ab = generate_a_bogus("aid=6383&device_platform=webapp", "")
        self.assertTrue(isinstance(ab, str) and len(ab) > 20)

    def test_search_profile_works_events_and_social_restrictions(self):
        raw_user = {
            "uid": "88888",
            "sec_uid": "MS4wLjABAAAA_test_sec",
            "nickname": "抖音测试达人",
            "signature": "记录美好生活",
            "gender": 2,
            "follower_count": 65432,
            "following_count": 18,
            "aweme_count": 12,
            "total_favorited": 999999,
            "unique_id": "dy_88888",
            "custom_verify": "优质创作者",
            "avatar_thumb": {"url_list": ["https://p3.douyinpic.com/aweme/a.jpg"]},
        }
        aweme = {
            "aweme_id": "7300000000000000001",
            "desc": "第一条抖音作品",
            "create_time": 1700000000,
            "author": {"nickname": "抖音测试达人"},
            "video": {"cover": {"url_list": ["https://p3.douyinpic.com/c.jpg"]}, "duration": 15000},
            "statistics": {"play_count": 2048, "comment_count": 33, "digg_count": 512, "share_count": 9},
        }
        with patch.object(self.adapter, "_load_cookies", return_value={"sessionid": "mock_sid"}), \
             patch("app.platforms.douyin.adapter.DouyinAPI") as api_mock:
            api_mock.search_some_user.return_value = [{"user_info": raw_user}]
            api_mock.get_user_info.return_value = {"user": raw_user}
            api_mock.get_user_all_work_info.return_value = [aweme]
            api_mock.get_work_info.return_value = {"aweme_detail": aweme}
            api_mock.get_user_following_list.return_value = {
                "status_code": 0,
                "has_more": 0,
                "min_time": "1700000000",
                "followings": [raw_user],
            }

            users = self.adapter.search_user("抖音测试")
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["sec_uid"], "MS4wLjABAAAA_test_sec")
            self.assertTrue(users[0]["is_verified"])

            profile = self.adapter.get_profile("MS4wLjABAAAA_test_sec")
            self.assertEqual(profile.uid, "88888")
            self.assertEqual(profile.extra["follower_count"], 65432)

            works = self.adapter.get_content_lists("MS4wLjABAAAA_test_sec")
            self.assertEqual(len(works), 1)
            self.assertEqual(works[0].item_id, "7300000000000000001")

            detail = self.adapter.get_content_detail("7300000000000000001")
            self.assertEqual(detail["title"], "第一条抖音作品")

            events = self.adapter.get_events("MS4wLjABAAAA_test_sec")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].timestamp, 1700000000000)

            follows, more, total = self.adapter.get_follows("MS4wLjABAAAA_test_sec", limit=10)
            self.assertEqual(len(follows), 1)
            self.assertFalse(more)
            self.assertEqual(total, -1)

            # 2096 列表隐私限制应明确抛 RuntimeError
            api_mock.get_user_follower_list.return_value = {"status_code": 2096, "status_msg": "列表不可见"}
            with self.assertRaisesRegex(RuntimeError, "无法获取该用户的关注/粉丝列表"):
                self.adapter.get_followers("MS4wLjABAAAA_test_sec")


class QQMusicScrapingTests(unittest.TestCase):
    """QQ音乐抓取与 SSR 解码测试"""

    def setUp(self):
        self.adapter = QQMusicAdapter()
        self.rate_patch = patch.object(self.adapter, "_rate_limit", return_value=None)
        self.rate_patch.start()
        self.addCleanup(self.rate_patch.stop)

    def test_g_tk_jsonp_and_ssr_double_encoded_decoder(self):
        self.assertEqual(QQMusicAdapter._calc_g_tk(""), 5381)
        self.assertNotEqual(QQMusicAdapter._calc_g_tk("skey_test_123"), 5381)

        parsed = QQMusicAdapter._parse_response('MusicJsonCallback({"code": 0, "data": {"ok": 1}})')
        self.assertEqual(parsed["data"]["ok"], 1)

        ssr_obj = {
            "homeData": {
                "data": {
                    "Info": {
                        "BaseInfo": {
                            "Name": "QQ音乐人",
                            "EncryptedUin": "oK6kowEA**",
                            "Avatar": "https://y.gtimg.cn/a.jpg",
                        },
                        "FansNum": {"Num": 321},
                        "FollowNum": {"Num": 12},
                    },
                    "TabDetail": {
                        "IntroductionTab": {
                            "List": [
                                {
                                    "ItemType": 10,
                                    "DissList": [
                                        {
                                            "list": [
                                                {
                                                    "dissid": "88001",
                                                    "title": "夜晚歌单",
                                                    "picurl": "https://y.gtimg.cn/p.jpg",
                                                    "subtitle": "15首 · 200次播放",
                                                }
                                            ]
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                }
            }
        }
        # 模拟 __ssrFirstPageData__ 的双重 JSON 编码
        double_encoded = json.dumps(json.dumps(ssr_obj))[1:-1]
        html = f'<script>window.__ssrFirstPageData__="{double_encoded}";</script>'

        with patch.object(self.adapter, "_fetch_html", return_value=html), \
             patch.object(self.adapter, "_try_get_follow_count_via_fcg", return_value={"follow": 12, "fans": 321}):
            profile = self.adapter.get_profile("oK6kowEA**")
            self.assertIsNotNone(profile)
            self.assertEqual(profile.nickname, "QQ音乐人")
            self.assertEqual(profile.extra["fan_count"], 321)

            playlists = self.adapter.get_content_lists("oK6kowEA**")
            self.assertEqual(len(playlists), 1)
            self.assertEqual(playlists[0].item_id, "88001")
            self.assertEqual(playlists[0].count, 15)
            self.assertEqual(playlists[0].view_count, 200)

    def test_musicu_search_and_social(self):
        musicu_resp = {
            "music.search.SearchCgiService": {
                "data": {
                    "body": {
                        "user": {
                            "list": [
                                {
                                    "uin": "12345678",
                                    "encrypt_uin": "oK6kowEA**",
                                    "nick": "周杰伦迷",
                                    "avatar": "https://y.gtimg.cn/u.jpg",
                                    "sign": "听妈妈的话",
                                }
                            ]
                        }
                    }
                }
            }
        }
        with patch.object(self.adapter, "_api_post_json", return_value=musicu_resp):
            users = self.adapter.search_user("周杰伦")
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["uid"], "12345678")
            self.assertEqual(users[0]["nickname"], "周杰伦迷")


class WeiboScrapingTests(unittest.TestCase):
    """微博抓取功能测试"""

    def setUp(self):
        self.adapter = WeiboAdapter()
        self.rate_patch = patch.object(self.adapter, "_rate_limit", return_value=None)
        self.rate_patch.start()
        self.addCleanup(self.rate_patch.stop)

    def test_search_profile_posts_events_and_pc_ajax_social(self):
        search_html = """
        <html><head><title>微博搜索</title></head><body>
        <script>$CONFIG['islogin'] = '1';</script>
        <div class="card card-user-b s-pg16 s-brt1">
            <div class="avator"><img src="https://tvax1.sinaimg.cn/crop.0.0.100.100.180/a.jpg"></div>
            <div class="info">
                <a href="//weibo.com/u/1669879400" class="name">迪丽热巴</a>
                <p>粉丝：8000万</p>
            </div>
        </div>
        </body></html>
        """
        mobile_profile = {
            "userInfo": {
                "id": 1669879400,
                "screen_name": "迪丽热巴",
                "profile_image_url": "https://tvax1.sinaimg.cn/a.jpg",
                "cover_image_phone": "",
                "description": "演员",
                "gender": "f",
                "location": "上海",
                "verified": True,
                "verified_reason": "知名演员",
                "statuses_count": 1200,
            },
            "tabs": {"follow": {"count": 300}, "fans": {"count": 80000000}},
            "tabsInfo": {"containerid": "1076031669879400"},
        }
        mobile_posts = {
            "cards": [
                {
                    "card_type": 9,
                    "mblog": {
                        "id": "4900000000000001",
                        "created_at": "Tue May 19 12:00:00 +0800 2026",
                        "text": "<p>今天天气真好</p>",
                        "user": {"screen_name": "迪丽热巴"},
                        "reposts_count": 100,
                        "comments_count": 200,
                        "attitudes_count": 500,
                        "pics": [],
                        "source": "iPhone客户端",
                    },
                }
            ]
        }

        def fake_mobile_get(params):
            if "containerid" in params:
                return mobile_posts if params.get("page", 1) == 1 else {"cards": []}
            return mobile_profile

        pc_friends = {
            "ok": 1,
            "total_number": 2,
            "users": [
                {
                    "id": 2001,
                    "screen_name": "微博好友1",
                    "profile_image_url": "https://tvax1.sinaimg.cn/1.jpg",
                    "description": "简介1",
                    "gender": "m",
                    "verified": True,
                    "followers_count": 15000,
                },
                {
                    "id": 2002,
                    "screen_name": "微博好友2",
                    "profile_image_url": "https://tvax1.sinaimg.cn/2.jpg",
                    "description": "简介2",
                    "gender": "f",
                    "verified": False,
                    "followers_count": 99,
                },
            ],
        }

        with patch.object(self.adapter, "_web_get", return_value=search_html), \
             patch.object(self.adapter, "_mobile_get", side_effect=fake_mobile_get), \
             patch.object(self.adapter, "_pc_ajax_get", return_value=pc_friends):
            users = self.adapter.search_user("迪丽热巴")
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["uid"], "1669879400")
            self.assertEqual(users[0]["fans"], 80000000)

            profile = self.adapter.get_profile("1669879400")
            self.assertEqual(profile.nickname, "迪丽热巴")
            self.assertTrue(profile.is_vip)

            posts = self.adapter.get_content_lists("1669879400")
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0].title, "今天天气真好")

            events = self.adapter.get_events("1669879400")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "发布微博")

            follows, more, total = self.adapter.get_follows("1669879400", limit=1, skip=1)
            self.assertEqual(len(follows), 1)
            self.assertEqual(follows[0]["uid"], "2002")
            self.assertFalse(more)
            self.assertEqual(total, 2)

    def test_expired_cookie_on_search_raises_runtime_error(self):
        with patch.object(self.adapter, "_web_get", return_value="<html>passport.weibo.com</html>"):
            with self.assertRaisesRegex(RuntimeError, "登录态已失效"):
                self.adapter.search_user("测试")


class GenshinScrapingTests(unittest.TestCase):
    """原神 Enka.Network 与米游社绑定抓取测试"""

    def setUp(self):
        self.adapter = GenshinAdapter()
        self.rate_patch = patch.object(self.adapter, "_rate_limit", return_value=None)
        self.rate_patch.start()
        self.addCleanup(self.rate_patch.stop)

    def test_server_detection_profile_characters_and_errors(self):
        self.assertEqual(detect_server("100000001"), "cn_gf01")
        self.assertEqual(detect_server("800000001"), "os_asia")

        enka_payload = {
            "playerInfo": {
                "nickname": "荧",
                "level": 60,
                "signature": "向着星辰与深渊",
                "worldLevel": 8,
                "finishAchievementNum": 1180,
                "towerFloorIndex": 12,
                "towerLevelIndex": 3,
                "profilePicture": {"id": 1, "avatarId": 10000007},
            },
            "avatarInfoList": [
                {
                    "avatarId": 10000046,
                    "avatarInfo": {
                        "name": "胡桃",
                        "level": 90,
                        "element": "火",
                        "constellationNum": 1,
                        "fetterLevel": 10,
                        "weapon": {"name": "护摩之杖", "level": 90},
                    },
                }
            ],
        }

        with patch.object(self.adapter, "_enka_get", return_value=enka_payload):
            users = self.adapter.search_user("100000001")
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["nickname"], "荧")

            profile = self.adapter.get_profile("100000001")
            self.assertEqual(profile.level, 60)
            self.assertEqual(profile.extra["achievements"], 1180)
            self.assertEqual(profile.extra["characters_count"], 1)

            chars = self.adapter.get_content_lists("100000001")
            self.assertEqual(len(chars), 1)
            self.assertEqual(chars[0].title, "胡桃 Lv.90")
            self.assertEqual(chars[0].extra["weapon_name"], "护摩之杖")

        with self.assertRaisesRegex(RuntimeError, "仅支持数字 UID 搜索"):
            self.adapter.search_user("胡桃")


class XhsScrapingTests(unittest.TestCase):
    """小红书 PC 签名栈与抓取测试"""

    def setUp(self):
        self.adapter = XhsAdapter()
        self.rate_patch = patch.object(self.adapter, "_rate_limit", return_value=None)
        self.rate_patch.start()
        self.addCleanup(self.rate_patch.stop)

    def test_xhs_pc_auth_cookie_parser_and_signature_stack(self):
        from ref_apis.xhs_pc_apis import XHS_Apis
        from ref_xhs_pc.auth import XHSPcAuth
        from ref_xhs_pc.params import generate_search_id

        with patch.object(XHS_Apis, "bootstrap", lambda self, proxies=None: self):
            auth = XHSPcAuth.from_cookie(
                "a1=18a0000000000000000000000000000000000000000000000000; web_session=test_web_session; webId=test_web_id"
            )
        self.assertIn(
            "a1=18a0000000000000000000000000000000000000000000000000",
            auth.cookies,
        )
        self.assertIn("web_session=test_web_session", auth.cookies)
        sid = generate_search_id()
        self.assertTrue(isinstance(sid, str) and len(sid) >= 16)

    def test_search_profile_notes_and_events(self):
        api_mock = MagicMock()
        api_mock.get_user_me.return_value = (
            True,
            "ok",
            {"data": {"basic_info": {"user_id": "5d8c00000000000010000001", "nickname": "小红薯", "images": "https://sns-avatar.xhscdn.com/a.jpg"}}},
        )
        api_mock.search_some_user.return_value = (
            True,
            "ok",
            [
                {
                    "user": {
                        "user_id": "5d8c00000000000010000001",
                        "nickname": "小红薯",
                        "avatar": "https://sns-avatar.xhscdn.com/a.jpg",
                        "desc": "生活分享",
                        "fans": 2500,
                        "official_verified": True,
                    }
                }
            ],
        )
        api_mock.get_user_info.return_value = (
            True,
            "ok",
            {
                "data": {
                    "basic_info": {
                        "nickname": "小红薯",
                        "images": "https://sns-avatar.xhscdn.com/a.jpg",
                        "desc": "生活分享",
                        "gender": 1,
                        "ip_location": "上海",
                        "red_id": "red_1001",
                        "notes_count": 18,
                    },
                    "interactions": [
                        {"type": "follows", "count": 66},
                        {"type": "fans", "count": 2500},
                        {"type": "interaction", "count": 12000},
                    ],
                }
            },
        )
        api_mock.get_user_all_notes.return_value = (
            True,
            "ok",
            [
                {
                    "note_id": "660000000000000000000001",
                    "display_title": "周末探店笔记",
                    "time": 1700000000000,
                    "cover": {"url_default": "https://sns-webpic.xhscdn.com/n.jpg"},
                    "user": {"nickname": "小红薯"},
                    "interact_info": {"liked_count": 320, "collected_count": 80, "comment_count": 15},
                }
            ],
        )

        self.adapter._api_pc = api_mock
        with patch.object(self.adapter, "_load_cookies", return_value={"a1": "x", "web_session": "y"}):
            self.assertTrue(self.adapter.check_alive())
            self.assertEqual(self.adapter.get_login_user()["uid"], "5d8c00000000000010000001")

        users = self.adapter.search_user("小红薯")
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["uid"], "5d8c00000000000010000001")
        self.assertTrue(users[0]["is_verified"])

        profile = self.adapter.get_profile("5d8c00000000000010000001")
        self.assertEqual(profile.nickname, "小红薯")
        self.assertEqual(profile.gender, 2)
        self.assertEqual(profile.extra["fans"], 2500)

        notes = self.adapter.get_content_lists("5d8c00000000000010000001")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].title, "周末探店笔记")

        events = self.adapter.get_events("5d8c00000000000010000001")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "发布笔记")


class GitHubScrapingTests(unittest.TestCase):
    """GitHub 平台抓取功能测试"""

    def setUp(self):
        self.adapter = GitHubAdapter(credentials={"token": "ghp_test_token_123"})
        self.rate_patch = patch.object(self.adapter, "_rate_limit", return_value=None)
        self.rate_patch.start()
        self.addCleanup(self.rate_patch.stop)

    def test_token_header_and_uid_normalization(self):
        self.assertEqual(
            self.adapter.session.headers.get("Authorization"),
            "Bearer ghp_test_token_123",
        )
        self.assertEqual(GitHubAdapter._clean_uid("@torvalds"), "torvalds")
        self.assertEqual(
            GitHubAdapter._clean_uid("https://github.com/chenglei6-arch/Sight"),
            "chenglei6-arch",
        )

    def test_search_profile_repos_starred_detail_events_and_social(self):
        user_payload = {
            "login": "torvalds",
            "id": 1024025,
            "name": "Linus Torvalds",
            "avatar_url": "https://avatars.githubusercontent.com/u/1024025?v=4",
            "bio": "Creator of Linux and Git",
            "location": "Portland, OR",
            "company": "Linux Foundation",
            "blog": "https://kernel.org",
            "created_at": "2011-09-03T15:26:22Z",
            "followers": 220000,
            "following": 0,
            "public_repos": 8,
            "public_gists": 1,
            "site_admin": False,
            "hireable": False,
            "type": "User",
            "html_url": "https://github.com/torvalds",
        }
        owned_repos = [
            {
                "name": "linux",
                "full_name": "torvalds/linux",
                "owner": {"login": "torvalds", "avatar_url": "https://avatars.githubusercontent.com/u/1024025?v=4"},
                "description": "Linux kernel source tree",
                "stargazers_count": 185000,
                "forks_count": 55000,
                "language": "C",
                "fork": False,
                "pushed_at": "2026-11-20T18:00:00Z",
                "created_at": "2011-09-04T22:48:12Z",
                "html_url": "https://github.com/torvalds/linux",
                "topics": ["kernel", "linux"],
                "license": {"spdx_id": "GPL-2.0"},
            }
        ]
        starred_repos = [
            {
                "name": "git",
                "full_name": "git/git",
                "owner": {"login": "git", "avatar_url": "https://avatars.githubusercontent.com/u/18133?v=4"},
                "description": "Git Source Code Mirror",
                "stargazers_count": 53000,
                "forks_count": 26000,
                "language": "C",
                "fork": False,
                "pushed_at": "2026-11-19T12:00:00Z",
                "html_url": "https://github.com/git/git",
            }
        ]
        commits_payload = [
            {
                "sha": "abcdef1234567890",
                "commit": {
                    "message": "Linux 6.12\n\nSigned-off-by: Linus Torvalds",
                    "author": {"name": "Linus Torvalds", "date": "2026-11-20T18:00:00Z"},
                },
                "author": {"login": "torvalds"},
            }
        ]
        events_payload = [
            {
                "id": "ev_101",
                "type": "PushEvent",
                "actor": {"login": "torvalds"},
                "repo": {"name": "torvalds/linux"},
                "created_at": "2026-11-20T18:00:00Z",
                "payload": {
                    "ref": "refs/heads/master",
                    "commits": [{"message": "Linux 6.12"}],
                },
            },
            {
                "id": "ev_102",
                "type": "WatchEvent",
                "actor": {"login": "torvalds"},
                "repo": {"name": "git/git"},
                "created_at": "2026-11-19T10:00:00Z",
                "payload": {"action": "started"},
            },
        ]
        followers_payload = [
            {"login": "octocat", "avatar_url": "https://avatars.githubusercontent.com/u/583231?v=4", "site_admin": True, "type": "User"},
            {"login": "github", "avatar_url": "https://avatars.githubusercontent.com/u/9919?v=4", "site_admin": False, "type": "Organization"},
        ]

        def fake_get(endpoint, params=None, allow_404=False, allow_409=False):
            if endpoint == "/user":
                return user_payload
            if endpoint == "/search/users":
                return {"items": [user_payload]}
            if endpoint in ("/users/torvalds", "/user/1024025"):
                return user_payload
            if endpoint == "/users/torvalds/repos":
                return owned_repos
            if endpoint == "/users/torvalds/starred":
                return starred_repos
            if endpoint == "/repos/torvalds/linux":
                return owned_repos[0]
            if endpoint == "/repos/torvalds/linux/commits":
                return commits_payload
            if endpoint == "/users/torvalds/events/public":
                return events_payload
            if endpoint == "/users/torvalds/followers":
                return followers_payload
            if endpoint == "/users/torvalds/following":
                return []
            raise AssertionError(f"Unexpected GitHub endpoint: {endpoint}")

        with patch.object(self.adapter, "_get", side_effect=fake_get):
            self.assertTrue(self.adapter.check_alive())
            login_user = self.adapter.get_login_user()
            self.assertEqual(login_user["uid"], "torvalds")
            self.assertTrue(self.adapter.test_account()["ok"])

            users = self.adapter.search_user("torvalds")
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["uid"], "torvalds")

            # 支持 @username 与数字 ID 查询
            profile = self.adapter.get_profile("@torvalds")
            self.assertIsNotNone(profile)
            self.assertEqual(profile.uid, "torvalds")
            self.assertEqual(profile.nickname, "Linus Torvalds")
            self.assertEqual(profile.extra["public_repos"], 8)
            self.assertEqual(profile.extra["followers"], 220000)
            self.assertTrue(profile.join_time.isdigit())

            by_num = self.adapter.get_profile("1024025")
            self.assertEqual(by_num.uid, "torvalds")

            repos = self.adapter.get_content_lists("torvalds")
            self.assertEqual(len(repos), 2)
            self.assertEqual(repos[0].item_id, "torvalds__linux")
            self.assertTrue(repos[0].is_owner)
            self.assertEqual(repos[0].count, 185000)
            self.assertEqual(repos[1].item_id, "git__git")
            self.assertFalse(repos[1].is_owner)

            detail = self.adapter.get_content_detail("torvalds__linux")
            self.assertEqual(detail["title"], "torvalds/linux")
            self.assertEqual(detail["subscribedCount"], 185000)
            self.assertEqual(detail["items"][0]["title"], "Linux 6.12")
            self.assertEqual(detail["items"][0]["id"], "abcdef1")

            events = self.adapter.get_events("torvalds")
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0].event_type, "推送代码")
            self.assertIn("Linux 6.12", events[0].content)
            self.assertEqual(events[1].event_type, "Star 仓库")

            followers, has_more, total = self.adapter.get_followers("torvalds", limit=10, skip=1)
            self.assertEqual(len(followers), 1)
            self.assertEqual(followers[0]["uid"], "github")
            self.assertTrue(followers[0]["is_verified"])
            self.assertTrue(has_more)
            self.assertEqual(total, 220000)

            refreshed = self.adapter.refresh_user_info("torvalds")
            self.assertEqual(refreshed["fans"], 220000)

    def test_github_404_returns_none_and_403_rate_limit_raises(self):
        resp_404 = Mock(status_code=404, headers={}, text='{"message": "Not Found"}')
        resp_404.json.return_value = {"message": "Not Found"}
        with patch.object(self.adapter.session, "get", return_value=resp_404):
            self.assertIsNone(self.adapter.get_profile("non_existent_user_12345"))

        resp_403 = Mock(
            status_code=403,
            headers={"X-RateLimit-Remaining": "0"},
            text='{"message": "API rate limit exceeded"}',
        )
        resp_403.json.return_value = {"message": "API rate limit exceeded"}
        with patch.object(self.adapter.session, "get", return_value=resp_403):
            with self.assertRaisesRegex(RuntimeError, "速率限制"):
                self.adapter.get_profile("torvalds")


class AllPlatformsRestAggregationTests(unittest.TestCase):
    """测试所有已注册平台经过 REST /api/<platform>/search 与 /api/<platform>/all 的聚合抓取与快照落库"""

    def setUp(self):
        from app.routes import api as api_module

        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.store = DataStore(db_path=Path(self.tmpdir.name) / "test_sight.db")
        self.store_patch = patch.object(api_module, "_store", self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)

        app = Flask(__name__)
        app.register_blueprint(api_module.bp)
        self.client = app.test_client()

    def test_every_platform_search_and_all_endpoint_works(self):
        for pid in known_platform_ids():
            with self.subTest(platform=pid):
                adapter = get_adapter(pid)
                sample_profile = PlatformProfile(
                    platform=pid,
                    uid="u_100",
                    nickname=f"{pid}_测试用户",
                    avatar_url="https://example.com/a.jpg",
                    signature="测试签名",
                    extra={"followers": 10, "following": 5},
                )
                sample_content = [
                    ContentItem(
                        item_id="item_1",
                        title=f"{pid}_测试内容",
                        count=3,
                        view_count=99,
                        creator=f"{pid}_测试用户",
                        create_time="1700000000000",
                    )
                ]
                sample_events = [
                    EventItem(
                        event_id="ev_1",
                        event_type="动态",
                        content=f"{pid}_动态内容",
                        timestamp=1700000000000,
                    )
                ]
                sample_social = ([{"uid": "u_200", "nickname": "好友"}], False, 1)

                with patch.object(
                    adapter,
                    "search_user",
                    return_value=[{"uid": "u_100", "nickname": f"{pid}_测试用户"}],
                ), patch.object(
                    adapter, "get_profile", return_value=sample_profile
                ), patch.object(
                    adapter, "get_content_lists", return_value=sample_content
                ), patch.object(
                    adapter, "get_events", return_value=sample_events
                ), patch.object(
                    adapter, "get_follows", return_value=sample_social
                ), patch.object(
                    adapter, "get_followers", return_value=sample_social
                ), patch.object(
                    adapter, "get_history", return_value=[]
                ):
                    search_res = self.client.get(f"/api/{pid}/search?keyword=test")
                    self.assertEqual(search_res.status_code, 200)
                    self.assertEqual(search_res.json["code"], 200)
                    self.assertEqual(search_res.json["data"][0]["uid"], "u_100")

                    all_res = self.client.get(f"/api/{pid}/all?uid=u_100&refresh=1")
                    self.assertEqual(all_res.status_code, 200)
                    self.assertEqual(all_res.json["code"], 200)
                    payload = all_res.json["data"]
                    self.assertEqual(payload["profile"]["nickname"], f"{pid}_测试用户")
                    self.assertEqual(len(payload["playlists"]), 1)
                    self.assertEqual(len(payload["events"]), 1)
                    self.assertEqual(len(payload["follows"]), 1)
                    self.assertEqual(len(payload["followers"]), 1)

    def test_all_endpoint_rejects_cached_or_partial_data_when_cookie_expired(self):
        adapter = get_adapter("netease")
        # 先预热一条新鲜快照到数据库
        self.store.save_snapshot(
            "netease",
            "u_expired",
            "profile",
            {"platform": "netease", "uid": "u_expired", "nickname": "旧快照用户"},
        )
        # 当后续接口报登录态已失效时，/all 必须拒绝返回旧快照或残缺数据
        with patch.object(
            adapter,
            "get_content_lists",
            return_value=[],
        ), patch.object(
            adapter,
            "get_history",
            return_value=[],
        ), patch.object(
            adapter,
            "get_events",
            return_value=[],
        ), patch.object(
            adapter,
            "get_follows",
            return_value=([], False, -1),
        ), patch.object(
            adapter,
            "get_followers",
            side_effect=RuntimeError("[网易云] 登录态已失效，请更新 Cookie 后重试"),
        ):
            res = self.client.get("/api/netease/all?uid=u_expired")
            self.assertEqual(res.status_code, 500)
            self.assertEqual(res.json["code"], -1)
            self.assertIn("登录凭证已失效", res.json["message"])

    def test_all_endpoint_fails_fast_on_first_auth_expired_module(self):
        adapter = get_adapter("weibo")
        with patch.object(
            adapter,
            "get_profile",
            side_effect=RuntimeError("[微博] 登录态已失效，请更新 Cookie"),
        ), patch.object(
            adapter, "get_content_lists"
        ) as mock_pl, patch.object(
            adapter, "get_events"
        ) as mock_ev, patch.object(
            adapter, "get_follows"
        ) as mock_fl, patch.object(
            adapter, "get_followers"
        ) as mock_fwr:
            res = self.client.get("/api/weibo/all?uid=6136329850&refresh=1")
            self.assertEqual(res.status_code, 500)
            self.assertEqual(res.json["code"], -1)
            self.assertIn("登录凭证已失效", res.json["message"])
            mock_pl.assert_not_called()
            mock_ev.assert_not_called()
            mock_fl.assert_not_called()
            mock_fwr.assert_not_called()

    def test_timeline_ignores_expired_snapshots_and_invalid_cookies(self):
        # 写入一条 2 个月前的过期快照
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO snapshots (platform, uid, data_type, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    "xhs",
                    "u_stale",
                    "events",
                    json.dumps(
                        {
                            "count": 1,
                            "items": [
                                {
                                    "event_id": "old_1",
                                    "event_type": "发布笔记",
                                    "content": "两个月前的旧笔记",
                                    "timestamp": 1700000000000,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    "2026-09-01T10:00:00+08:00",
                ),
            )
            conn.commit()

        adapter = get_adapter("xhs")
        with patch.object(CredentialManager, "load_cookies", return_value={"a1": "expired"}), \
             patch.object(adapter, "check_alive", return_value=False):
            entries = TimelineBuilder.build({"xhs": "u_stale"}, store=self.store)
            self.assertEqual(entries, [])

    def test_timeline_stored_text_and_markdown_export(self):
        from app.services.timeline import TimelineEntry

        self.store.insert_timeline_entries(
            [
                TimelineEntry(
                    platform="github",
                    uid="torvalds",
                    event_type="PushEvent",
                    timestamp=1700000000000,
                    time_str="2023-11-15 06:13",
                    summary="在 GitHub 推送了提交",
                    detail="linux",
                )
            ]
        )

        res_text = self.client.get("/api/timeline?uids=github:torvalds&source=stored&format=text")
        self.assertEqual(res_text.status_code, 200)
        self.assertEqual(res_text.json["code"], 200)
        self.assertIn("在 GitHub 推送了提交", res_text.json["data"]["timeline"])

        res_md = self.client.get("/api/timeline?uids=github:torvalds&source=stored&format=markdown")
        self.assertEqual(res_md.status_code, 200)
        self.assertEqual(res_md.json["code"], 200)
        md_body = res_md.json["data"]["timeline"]
        self.assertIn("多平台活动时间线", md_body)
        self.assertIn("GitHub", md_body)
        self.assertIn("在 GitHub 推送了提交", md_body)


if __name__ == "__main__":
    unittest.main()
