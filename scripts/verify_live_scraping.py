"""
全平台真实线上抓取巡检脚本 (CI/CD Live Scraping Probe)

用途:
  python scripts/verify_live_scraping.py                  # 探测所有平台（无凭证平台自动走公开接口或跳过需登录接口）
  python scripts/verify_live_scraping.py --strict         # 严格模式：任一平台抓取失败或凭证失效均返回非 0 退出码
  python scripts/verify_live_scraping.py --platforms github,netease

环境变量:
  SIGHT_ACCOUNTS_JSON   若设置（如 GitHub Actions Secret），自动写入 credentials/accounts.json（若本地尚未存在）
  GITHUB_TOKEN          GitHub 平台免配置 Cookie 时的 API Token
  GITHUB_STEP_SUMMARY   GitHub Actions 步骤摘要文件路径，存在时自动写入 Markdown 巡检报告
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.credentials import ACCOUNTS_FILE, CredentialManager
from app.platforms import get_adapter, known_platform_ids


def _maybe_inject_ci_accounts():
    """在 CI 环境中若提供了 SIGHT_ACCOUNTS_JSON Secret 且本地无 accounts.json，则注入凭证"""
    raw = os.environ.get("SIGHT_ACCOUNTS_JSON", "").strip()
    if not raw or ACCOUNTS_FILE.exists():
        return
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            ACCOUNTS_FILE.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[CI] 已从 SIGHT_ACCOUNTS_JSON 注入凭证，包含平台: {list(parsed.keys())}")
    except Exception as e:
        print(f"[CI] SIGHT_ACCOUNTS_JSON 解析失败: {e}")


def probe_platform(pid: str) -> dict:
    """对单个平台发起真实抓取探测，返回 {platform, name, has_cred, status, latency_ms, detail}"""
    adapter = get_adapter(pid)
    name = adapter.platform_name if adapter else pid
    cookies = CredentialManager.load_cookies(pid)
    has_cred = bool(cookies) or (
        pid == "github" and hasattr(adapter, "_extract_effective_token") and bool(adapter._extract_effective_token())
    )
    t0 = time.perf_counter()

    try:
        if pid == "github":
            users = adapter.search_user("torvalds", limit=3)
            profile = adapter.get_profile("torvalds")
            repos = adapter.get_content_lists("torvalds")
            if not users or not profile or not repos:
                raise RuntimeError("GitHub 抓取返回空数据")
            detail = f"search={len(users)}, profile={profile.nickname}(followers={profile.extra.get('followers')}), repos={len(repos)}"
            status = "PASS"

        elif pid == "netease":
            users = adapter.search_user("周杰伦", limit=3)
            if not users:
                raise RuntimeError("网易云 search_user 返回空列表")
            target_uid = users[0]["uid"]
            playlists = adapter.get_content_lists(target_uid)
            detail = f"search={len(users)} (top={users[0]['nickname']}), playlists={len(playlists)}"
            status = "PASS"

        elif pid == "bilibili":
            # 公开视频详情接口免 Wbi/Cookie 即可验证 B 站线上抓取连通性；有凭证时附加搜索/登录态探测
            video = adapter.get_content_detail("2")
            if not video or not video.get("title"):
                raise RuntimeError("B站 get_content_detail('2') 未返回视频标题")
            extra_note = ""
            if has_cred:
                alive = adapter.check_alive()
                extra_note = f", cookie_alive={alive}"
            detail = f"video_detail=《{video['title'][:20]}》(views={video.get('viewCount')}){extra_note}"
            status = "PASS"

        elif pid == "qqmusic":
            users = adapter.search_user("周杰伦", limit=3)
            if users:
                detail = f"musicu_search={len(users)} (top={users[0]['nickname']})"
                status = "PASS"
            else:
                profile = adapter.get_profile("oK6kowEAoK4z7Knioivl7evl7n**")
                if profile and profile.nickname:
                    detail = f"ssr_profile={profile.nickname}"
                    status = "PASS"
                elif not has_cred:
                    detail = "未配置有效 QQ音乐 Cookie，公开网关返回空列表"
                    status = "SKIP_NO_CRED"
                else:
                    raise RuntimeError("QQ音乐搜索与 SSR 资料均未返回有效数据")

        elif pid == "genshin":
            # Enka.Network 公开 API 探测（404 或正常资料均说明协议与解析通路正常）
            profile = adapter.get_profile("100000100")
            if profile:
                detail = f"enka_profile={profile.nickname} (Lv.{profile.level})"
            else:
                detail = "enka_api=reachable (UID 100000100 未开启展柜或不存在，接口响应正常)"
            status = "PASS"

        elif pid == "weibo":
            if not has_cred:
                detail = "未配置微博 Cookie（微博移动端与搜索均需登录 Cookie）"
                status = "SKIP_NO_CRED"
            else:
                profile = adapter.get_profile("1669879400")
                if not profile or not profile.nickname:
                    raise RuntimeError("微博 get_profile 未返回有效资料")
                detail = f"profile={profile.nickname} (fans={profile.extra.get('fans_count')})"
                status = "PASS"

        elif pid == "douyin":
            from app.platforms.douyin.ref_utils.dy_util import generate_a_bogus

            ab = generate_a_bogus("aid=6383&device_platform=webapp", "")
            if not ab or len(ab) < 20:
                raise RuntimeError("抖音 a_bogus 本地签名生成失败")
            if not has_cred:
                detail = f"a_bogus 签名正常 (len={len(ab)})；未配置抖音 Cookie 跳过线上登录接口"
                status = "SKIP_NO_CRED"
            else:
                users = adapter.search_user("人民日报", limit=3)
                if not users:
                    raise RuntimeError("抖音 search_user 返回空结果（Cookie 可能失效或触发验证码）")
                detail = f"a_bogus=OK, search={len(users)} (top={users[0]['nickname']})"
                status = "PASS"

        elif pid == "xhs":
            from ref_xhs_pc.params import generate_search_id

            sid = generate_search_id()
            if not sid:
                raise RuntimeError("小红书 search_id 生成失败")
            if not has_cred:
                detail = f"PC 签名栈正常 (search_id={sid})；未配置小红书 Cookie 跳过线上接口"
                status = "SKIP_NO_CRED"
            else:
                if not adapter.check_alive():
                    raise RuntimeError("小红书 Cookie 已过期或无效 (get_user_me 失败)")
                users = adapter.search_user("美食", limit=3)
                detail = f"alive=True, search={len(users)}"
                status = "PASS"

        else:
            users = adapter.search_user("test", limit=3)
            detail = f"search={len(users)}"
            status = "PASS"

    except Exception as e:
        msg = str(e)
        # 若因 Cookie 过期/未登录/风控导致失败，在非 strict 模式下区分认证失效与代码崩溃
        auth_keywords = ("登录", "Cookie", "凭证", "401", "403", "风控", "验证", "未初始化", "过期", "502", "424")
        if any(k in msg for k in auth_keywords):
            status = "AUTH_OR_UPSTREAM_LIMIT"
        else:
            status = "FAIL"
        detail = msg

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "platform": pid,
        "name": name,
        "has_cred": has_cred,
        "status": status,
        "latency_ms": elapsed_ms,
        "detail": detail,
    }


def render_markdown_report(results: list[dict]) -> str:
    icon_map = {
        "PASS": "✅ PASS",
        "SKIP_NO_CRED": "⚪ SKIP (无凭证)",
        "AUTH_OR_UPSTREAM_LIMIT": "⚠️ AUTH/风控受限",
        "FAIL": "❌ FAIL",
    }
    lines = [
        "## 🌐 Sight 全平台抓取功能巡检报告",
        "",
        "| 平台 | 标识 | 凭证状态 | 巡检结果 | 耗时 | 抓取详情 |",
        "|------|------|:---:|:---:|---:|------|",
    ]
    for r in results:
        cred_str = "🔑 已配置" if r["has_cred"] else "🌐 免密/未配"
        status_str = icon_map.get(r["status"], r["status"])
        safe_detail = str(r["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {r['name']} | `{r['platform']}` | {cred_str} | {status_str} | {r['latency_ms']}ms | {safe_detail} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="测试每个平台的线上抓取功能是否有效")
    parser.add_argument(
        "--platforms",
        default="",
        help="逗号分隔的平台列表，默认测试全部已注册平台",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：任何平台未 PASS（含无凭证跳过或 Cookie 过期）均返回失败退出码",
    )
    args = parser.parse_args()

    _maybe_inject_ci_accounts()

    all_pids = known_platform_ids()
    if args.platforms.strip():
        target_pids = [p.strip() for p in args.platforms.split(",") if p.strip()]
    else:
        target_pids = all_pids

    results = []
    for pid in target_pids:
        print(f"--- 正在测试平台 [{pid}] 抓取功能 ---")
        res = probe_platform(pid)
        print(f"[{pid}] status={res['status']} ({res['latency_ms']}ms): {res['detail']}")
        results.append(res)

    report_md = render_markdown_report(results)
    print("\n" + report_md)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(report_md + "\n")
        except OSError as e:
            print(f"[警告] 写入 GITHUB_STEP_SUMMARY 失败: {e}")

    if args.strict:
        failed = [r for r in results if r["status"] != "PASS"]
    else:
        # 默认模式下：任何代码级 FAIL 必报错；且免密公开核心平台（如 github）必须 PASS
        failed = [
            r for r in results
            if r["status"] == "FAIL" or (r["platform"] == "github" and r["status"] != "PASS")
        ]

    if failed:
        print(f"[巡检失败] 共 {len(failed)} 个平台未通过: {[r['platform'] for r in failed]}")
        return 1
    print("[巡检通过] 所有目标平台抓取功能测试完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
