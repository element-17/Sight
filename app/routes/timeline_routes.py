"""多平台统一活动时间线与条目编辑路由"""
import time

from flask import request

from app.routes.common import _error, _log_fetch, _result, bp, get_store
from app.services.timeline import TimelineBuilder


def _parse_uid_map(uids_param: str) -> dict[str, str]:
    uid_map: dict[str, str] = {}
    for pair in (uids_param or "").split(","):
        parts = pair.strip().split(":")
        if len(parts) == 2 and parts[0] and parts[1]:
            uid_map[parts[0]] = parts[1]
    return uid_map


@bp.route("/timeline")
def unified_timeline():
    """多平台统一活动时间线（支持 live 实时对比与 stored 持久化历史读取）"""
    uid_map = _parse_uid_map(request.args.get("uids", ""))
    limit = int(request.args.get("limit", 30))
    fmt = request.args.get("format", "json")
    source = request.args.get("source", "live")

    if not uid_map:
        return _error("请提供 uids 参数，如 netease:5012722824,bilibili:3493284789881676", http_status=400)

    t0 = time.perf_counter()
    uid_list = ",".join(f"{k}:{v}" for k, v in uid_map.items())
    try:
        if source == "stored":
            all_rows = []
            for platform_id, uid in uid_map.items():
                all_rows.extend(get_store().get_timeline_entries(platform=platform_id, uid=uid, limit=limit))
            all_rows.sort(key=lambda r: (r.get("created_at", ""), r.get("timestamp", 0)), reverse=True)
            all_rows = all_rows[:limit]

            _log_fetch("GET /timeline", "multi", uid_list, True, (time.perf_counter() - t0) * 1000, f"{len(all_rows)} stored entries")
            if fmt == "text":
                return _result({"timeline": TimelineBuilder.build_log_text(all_rows)})
            if fmt == "markdown":
                return _result({"timeline": TimelineBuilder.build_log_markdown(all_rows, title="# 📊 多平台活动时间线（历史）")})
            return _result(all_rows)

        entries = TimelineBuilder.build(uid_map, limit_per_platform=limit, store=get_store())
        try:
            inserted = get_store().insert_timeline_entries(entries)
            print(f"[API /timeline] 时间线持久化: {inserted} 条新增")
        except Exception as e:
            print(f"[API /timeline] 时间线持久化失败: {e}")

        _log_fetch("GET /timeline", "multi", uid_list, True, (time.perf_counter() - t0) * 1000, f"{len(entries)} entries")
        if fmt == "text":
            return _result({"timeline": TimelineBuilder.build_log_text(entries)})
        if fmt == "markdown":
            return _result({"timeline": TimelineBuilder.build_log_markdown(entries)})
        return _result([
            {
                "timestamp": e.timestamp,
                "time_str": e.time_str,
                "time_suffix": e.time_suffix,
                "platform": e.platform,
                "platform_name": e.platform_name,
                "event_type": e.event_type,
                "summary": e.summary,
                "detail": e.detail,
            }
            for e in entries
        ])
    except Exception as e:
        _log_fetch("GET /timeline", "multi", uid_list, False, (time.perf_counter() - t0) * 1000, str(e))
        return _error(str(e))


@bp.route("/timeline/<int:entry_id>", methods=["PUT"])
def update_timeline_entry(entry_id):
    """更新时间线条目（summary / detail）"""
    body = request.get_json(force=True, silent=True) or {}
    summary = body.get("summary")
    detail = body.get("detail")
    if summary is None and detail is None:
        return _error("请提供 summary 或 detail 字段", http_status=400)
    try:
        if get_store().update_timeline_entry(entry_id, summary=summary, detail=detail):
            return _result({"message": "更新成功", "id": entry_id})
        return _error("条目不存在或未变更", http_status=404)
    except Exception as e:
        return _error(str(e))


@bp.route("/timeline/<int:entry_id>", methods=["DELETE"])
def delete_timeline_entry(entry_id):
    """删除时间线条目"""
    try:
        if get_store().delete_timeline_entry(entry_id):
            return _result({"message": "删除成功", "id": entry_id})
        return _error("条目不存在", http_status=404)
    except Exception as e:
        return _error(str(e))
