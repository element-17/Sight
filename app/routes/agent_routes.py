"""AI Agent 模型配置、人物侧写会话管理、中断恢复、追问、多模态媒体缓存与 SSE 实时流路由"""
import json

from flask import Response, request, send_file

from app.agent.llm_config import (
    fetch_available_models,
    get_public_config,
    save_llm_config,
    test_llm_connection,
)
from app.agent.runner import get_agent_runner
from app.routes.common import _error, _result, bp
from app.services.media_fetcher import lookup_cached_media


# ==================== LLM 模型配置 ====================


@bp.route("/agent/config")
def agent_config_get():
    """读取脱敏后的 LLM 配置与常见提供商预设"""
    try:
        return _result(get_public_config())
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/config", methods=["POST"])
def agent_config_save():
    """保存 LLM 配置至 credentials/llm.json"""
    body = request.get_json(silent=True) or {}
    try:
        return _result(save_llm_config(body))
    except ValueError as e:
        return _error(str(e), http_status=400)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/config/test", methods=["POST"])
def agent_config_test():
    """探测 LLM 连通性（支持携带未保存草稿字段测试）"""
    body = request.get_json(silent=True) or {}
    overrides = body if isinstance(body, dict) and body else None
    try:
        return _result(test_llm_connection(overrides))
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/config/models", methods=["POST"])
def agent_config_models():
    """按当前草稿或已保存配置动态拉取可用模型列表（OpenAI 兼容 / Anthropic / Gemini）"""
    body = request.get_json(silent=True) or {}
    overrides = body if isinstance(body, dict) and body else None
    try:
        return _result(fetch_available_models(overrides))
    except Exception as e:
        return _error(str(e))


# ==================== 侧写档案与运行控制 ====================


@bp.route("/agent/sessions")
def agent_sessions_list():
    """列出已保存的人物侧写档案"""
    try:
        return _result(get_agent_runner().list_sessions())
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions", methods=["POST"])
def agent_sessions_create():
    """创建并（默认）立即启动一次人物侧写任务"""
    body = request.get_json(silent=True) or {}
    try:
        session = get_agent_runner().create_session(
            title=str(body.get("title") or ""),
            target_query=str(body.get("target_query") or ""),
            focus=str(body.get("focus") or ""),
            uids=body.get("uids") if isinstance(body.get("uids"), dict) else None,
            graph_id=body.get("graph_id"),
            auto_confirm=bool(body.get("auto_confirm", False)),
            refresh_data=bool(body.get("refresh_data", False)),
            auto_start=bool(body.get("auto_start", True)),
        )
        return _result(session)
    except ValueError as e:
        return _error(str(e), http_status=400)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>")
def agent_session_detail(session_id):
    """获取单条侧写档案完整数据"""
    try:
        detail = get_agent_runner().get_session_detail(session_id)
        if detail is None:
            return _error("侧写档案不存在或已被删除", http_status=404)
        return _result(detail)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>", methods=["DELETE"])
def agent_session_delete(session_id):
    """删除一条侧写档案及其 LangGraph Checkpoint"""
    try:
        if get_agent_runner().delete_session(session_id):
            return _result({"id": session_id, "deleted": True})
        return _error("侧写档案不存在", http_status=404)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>/run", methods=["POST"])
def agent_session_run(session_id):
    """对已有档案重新发起一次侧写推理"""
    body = request.get_json(silent=True) or {}
    try:
        kwargs = {
            "auto_confirm": bool(body.get("auto_confirm", False)),
            "refresh_data": bool(body.get("refresh_data", False)),
        }
        if isinstance(body.get("uids"), dict):
            kwargs["uids"] = body["uids"]
        if "target_query" in body:
            kwargs["target_query"] = body["target_query"]
        if "focus" in body:
            kwargs["focus"] = body["focus"]
        if "graph_id" in body:
            kwargs["graph_id"] = body["graph_id"]
        return _result(get_agent_runner().start_profile_run(session_id, **kwargs))
    except KeyError:
        return _error("侧写档案不存在", http_status=404)
    except (ValueError, RuntimeError) as e:
        return _error(str(e), http_status=400)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>/resume", methods=["POST"])
def agent_session_resume(session_id):
    """确认跨平台候选账号并恢复 LangGraph interrupt() 断点"""
    body = request.get_json(silent=True) or {}
    confirmed = body.get("confirmed_accounts")
    if not isinstance(confirmed, dict):
        return _error("请提供 confirmed_accounts 对象 ({platform: uid})", http_status=400)
    try:
        return _result(get_agent_runner().resume_session(session_id, confirmed))
    except KeyError:
        return _error("侧写档案不存在", http_status=404)
    except (ValueError, RuntimeError) as e:
        return _error(str(e), http_status=400)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>/continue", methods=["POST"])
def agent_session_continue(session_id):
    """从 LangGraph SqliteSaver 失败断点原地续跑（stream(None, config)），跳过已完成阶段"""
    try:
        return _result(get_agent_runner().continue_session(session_id))
    except KeyError:
        return _error("侧写档案不存在", http_status=404)
    except (ValueError, RuntimeError) as e:
        return _error(str(e), http_status=400)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>/chat", methods=["POST"])
def agent_session_chat(session_id):
    """在同一 LangGraph thread_id 上进行多轮追问"""
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return _error("追问内容不能为空", http_status=400)
    try:
        return _result(get_agent_runner().send_followup(session_id, message))
    except KeyError:
        return _error("侧写档案不存在", http_status=404)
    except (ValueError, RuntimeError) as e:
        return _error(str(e), http_status=400)
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>/cancel", methods=["POST"])
def agent_session_cancel(session_id):
    """协作式中止正在运行的侧写任务"""
    try:
        cancelled = get_agent_runner().cancel(session_id)
        return _result({"id": session_id, "cancelled": cancelled})
    except Exception as e:
        return _error(str(e))


# ==================== 实时事件流（SSE + 轮询降级） ====================


@bp.route("/agent/sessions/<session_id>/events")
def agent_session_events(session_id):
    """按游标增量拉取 Agent 运行事件（SSE 的降级轮询接口）"""
    after = request.args.get("after", 0, type=int)
    try:
        return _result(get_agent_runner().get_events(session_id, after=after))
    except Exception as e:
        return _error(str(e))


@bp.route("/agent/sessions/<session_id>/stream")
def agent_session_stream(session_id):
    """SSE 实时推送 Agent 阶段进度、工具轨迹、中断确认与流式报告"""
    after = request.args.get("after", 0, type=int)

    def generate():
        runner = get_agent_runner()
        last = after
        terminal_types = {"done", "error", "interrupt", "chat_done"}

        initial = runner.get_events(session_id, after=last)
        for ev in initial["entries"]:
            yield f"id: {ev['seq']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            last = ev["seq"]
            if ev.get("type") in terminal_types and not runner.is_running(session_id):
                return

        if not runner.is_running(session_id) and not initial["entries"]:
            yield ": idle\n\n"
            return

        while True:
            entries = runner.wait_events(session_id, after=last, timeout=15.0)
            if not entries:
                if not runner.is_running(session_id):
                    yield ": done\n\n"
                    return
                yield ": keepalive\n\n"
                continue
            for ev in entries:
                yield f"id: {ev['seq']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                last = ev["seq"]
                if ev.get("type") in terminal_types and not runner.is_running(session_id):
                    return

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ==================== 多模态证据媒体本地安全代理 ====================


@bp.route("/agent/media/<media_id>")
def agent_media_file(media_id):
    """按严格 24 位十六进制 media_id 提供本地缓存的图片/视频预览（防路径穿越与 SSRF）"""
    cached = lookup_cached_media(media_id)
    if not cached:
        return _error("媒体缓存不存在或已过期", http_status=404)
    resp = send_file(cached.path, mimetype=cached.mime_type, conditional=True)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp
