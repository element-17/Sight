"""日志缓冲与 SSE 实时日志流路由"""
import json

from flask import Response, request

from app.routes.common import _result, bp
from app.services.log_hub import get_log_hub


@bp.route("/logs/recent")
def logs_recent():
    """内存日志缓冲尾部（?after=seq 增量拉取，用于 SSE 降级轮询）"""
    after = request.args.get("after", 0, type=int)
    limit = min(request.args.get("limit", 200, type=int) or 200, 1000)
    entries = get_log_hub().since(after)
    if len(entries) > limit:
        entries = entries[-limit:]
    last_seq = entries[-1]["seq"] if entries else after
    return _result({"entries": entries, "last_seq": last_seq})


@bp.route("/logs/stream")
def logs_stream():
    """SSE 实时日志流；?after=seq 续传，15s 无新日志发 keepalive"""
    after = request.args.get("after", 0, type=int)

    def generate():
        hub = get_log_hub()
        last = after
        for e in hub.since(last):
            yield f"id: {e['seq']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
            last = e["seq"]
        while True:
            entries = hub.wait_since(last, timeout=15.0)
            if not entries:
                yield ": keepalive\n\n"
                continue
            for e in entries:
                yield f"id: {e['seq']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                last = e["seq"]

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
