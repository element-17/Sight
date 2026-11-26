"""跨平台关系图搜索、社交展开队列、节点刷新与图谱持久化路由"""
import json
from concurrent.futures import ThreadPoolExecutor

from flask import request

from app.platforms import get_pool
from app.routes.common import (
    _error,
    _result,
    bp,
    get_store,
)
from app.services.expand_queue import get_expand_queue
from app.services.search_service import (
    name_similarity as _name_similarity,
    norm_nickname as _norm_nickname,
    search_cross_platform,
    search_user_cached as _search_user_cached,
)
from app.services.social_expander import clamp_int

GRAPH_REFRESH_MAX_NODES = 300
GRAPH_NAME_MAX_LEN = 60


@bp.route("/graph/search")
def graph_search():
    """按关键词并行搜索各平台用户，聚合为关系图数据"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return _error("请输入搜索关键词", http_status=400)

    limit = clamp_int(request.args.get("limit", 10), 3, 20, 10)
    requested = request.args.get("platforms", "").strip()
    platform_ids = [p for p in requested.split(",") if p] if requested else None
    refresh = request.args.get("refresh", "").strip() in ("1", "true")

    overrides: dict[str, str] = {}
    raw_kw = request.args.get("keywords", "").strip()
    if raw_kw:
        try:
            parsed = json.loads(raw_kw)
            if isinstance(parsed, dict):
                overrides = {
                    str(k).strip(): str(v).strip()
                    for k, v in parsed.items()
                    if str(k).strip() and str(v).strip()
                }
        except (ValueError, TypeError):
            overrides = {}

    return _result(
        search_cross_platform(
            keyword,
            platform_ids=platform_ids,
            limit=limit,
            refresh=refresh,
            keyword_overrides=overrides,
        )
    )


# ==================== 社交展开队列 ====================

@bp.route("/graph/expand/enqueue", methods=["POST"])
def graph_expand_enqueue():
    """把一批展开任务加入按平台隔离的后台队列"""
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return _error("缺少展开任务列表", http_status=400)
    try:
        return _result(get_expand_queue().enqueue(body.get("graph_id"), items))
    except Exception as e:
        return _error(f"入队失败: {e}")


@bp.route("/graph/expand/results")
def graph_expand_results():
    """增量轮询某图谱的展开结果"""
    graph_id = request.args.get("graph_id", "").strip()
    if not graph_id:
        return _error("缺少 graph_id", http_status=400)
    since_id = clamp_int(request.args.get("since_id", 0), 0, 10**9, 0)
    limit = clamp_int(request.args.get("limit", 50), 1, 200, 50)
    try:
        return _result(get_expand_queue().results(graph_id, since_id, limit))
    except Exception as e:
        return _error(f"查询结果失败: {e}")


@bp.route("/graph/expand/stop", methods=["POST"])
def graph_expand_stop():
    """停止某图谱（可选限单平台）的排队任务"""
    body = request.get_json(silent=True) or {}
    graph_id = body.get("graph_id")
    if graph_id is None:
        return _error("缺少 graph_id", http_status=400)
    platform = str(body.get("platform", "")).strip() or None
    return _result({"cancelled": get_expand_queue().stop(graph_id, platform)})


@bp.route("/graph/expand/resume", methods=["POST"])
def graph_expand_resume():
    """恢复熔断暂停的平台队列"""
    body = request.get_json(silent=True) or {}
    platform = str(body.get("platform", "")).strip() or None
    get_expand_queue().resume(platform)
    return _result({"ok": True})


@bp.route("/graph/expand/status")
def graph_expand_status():
    """各平台展开队列状态"""
    return _result({"queues": get_expand_queue().platform_status()})


@bp.route("/graph/refresh_nodes", methods=["POST"])
def graph_refresh_nodes():
    """批量重拉图节点最新信息（修正大V判定）"""
    body = request.get_json(silent=True) or {}
    items = body.get("nodes")
    if not isinstance(items, list) or not items:
        return _error("缺少待刷新节点", http_status=400)
    if len(items) > GRAPH_REFRESH_MAX_NODES:
        return _error(f"单次最多刷新 {GRAPH_REFRESH_MAX_NODES} 个节点", http_status=400)

    by_platform: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for item in items:
        pid = str((item or {}).get("platform", "")).strip()
        uid = str((item or {}).get("uid", "")).strip()
        if not pid or not uid or (pid, uid) in seen:
            continue
        seen.add((pid, uid))
        by_platform.setdefault(pid, []).append(uid)

    results: list[dict] = []
    errors: dict[str, str] = {}

    def _refresh_one(p_pool, uid: str):
        with p_pool.lease() as ad:
            if ad is None:
                return uid, None, "无可用账号"
            try:
                return uid, ad.refresh_user_info(uid), None
            except Exception as e:
                return uid, None, f"[账号：{p_pool.label_for(ad)}] {e}"

    for pid, uids in by_platform.items():
        p_pool = get_pool(pid)
        if not p_pool:
            for uid in uids:
                errors[f"{pid}:{uid}"] = "未知平台"
            continue

        if p_pool.size >= 2 and len(uids) >= 2:
            with ThreadPoolExecutor(max_workers=min(p_pool.size, len(uids), 8)) as ex:
                outcomes = list(ex.map(lambda u: _refresh_one(p_pool, u), uids))
        else:
            outcomes = [_refresh_one(p_pool, uid) for uid in uids]

        for uid, info, err in outcomes:
            if err:
                errors[f"{pid}:{uid}"] = err
                continue
            if not info:
                errors[f"{pid}:{uid}"] = "平台不支持或未获取到数据"
                continue
            node = {
                "id": f"{pid}:{uid}",
                "platform": pid,
                "uid": uid,
                "nickname": str(info.get("nickname", "")),
                "fans": int(info.get("fans") or 0),
            }
            if info.get("is_verified") is not None:
                node["verified"] = bool(info.get("is_verified"))
            results.append(node)

    return _result({"nodes": results, "errors": errors, "refreshed": len(results)})


# ==================== 关系图谱持久化 ====================

@bp.route("/graph/save", methods=["POST"])
def graph_save():
    """按名称保存当前关系图谱（同名覆盖）"""
    body = request.get_json(force=True, silent=True) or {}
    name = str(body.get("name", "")).strip()[:GRAPH_NAME_MAX_LEN]
    data = body.get("data")
    if not name:
        return _error("请提供图谱名称", http_status=400)
    if not isinstance(data, dict) or not data.get("nodes"):
        return _error("图谱数据为空，无法保存", http_status=400)

    keyword = str(body.get("keyword") or data.get("keyword") or "").strip()
    try:
        graph_id = get_store().save_graph(name, keyword, data)
        return _result({"id": graph_id, "name": name})
    except Exception as e:
        return _error(str(e))


@bp.route("/graph/saved")
def graph_saved_list():
    """列出已保存图谱元信息"""
    try:
        return _result(get_store().list_graphs())
    except Exception as e:
        return _error(str(e))


@bp.route("/graph/saved/<int:graph_id>")
def graph_saved_detail(graph_id):
    """获取单张已保存图谱完整数据"""
    try:
        graph = get_store().get_graph(graph_id)
        if graph is None:
            return _error("图谱不存在或已被删除", http_status=404)
        return _result(graph)
    except Exception as e:
        return _error(str(e))


@bp.route("/graph/saved/<int:graph_id>", methods=["DELETE"])
def graph_saved_delete(graph_id):
    """删除一张已保存图谱"""
    try:
        if get_store().delete_graph(graph_id):
            return _result({"message": "删除成功", "id": graph_id})
        return _error("图谱不存在或已被删除", http_status=404)
    except Exception as e:
        return _error(str(e))
