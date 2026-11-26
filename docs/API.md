# Sight API 参考

REST / SSE 接口一览。启动方式与 Cookie 配置见[根 README](../README.md)，
平台实现与开发约定见[开发手册](MANUAL.md)。

所有路径前缀 `/api`（默认 `http://127.0.0.1:5001`）。成功响应 `{"code": 200, "data": ...}`；
REST 层是唯一把异常转 JSON 的边界，失败返回 `{"code": -1, "message": 原因}`
（message 带平台前缀/账号标签/风控码）。`{platform}` 取值见开发手册平台矩阵。

## 平台数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/platforms` | 平台列表与凭证状态 |
| GET | `/{platform}/search?keyword=xxx` | 用户搜索 |
| GET | `/{platform}/all?uid=xxx` | 资料/内容/关系聚合，子模块错误收进 `data._errors`；`refresh=1` 绕过 30 分钟快照强制实时 |
| GET | `/{platform}/playlist/<item_id>` | 内容详情 |
| GET | `/{platform}/status` | 连接状态（`alive` + `login_user`） |
| GET | `/timeline?uids=p1:uid1,p2:uid2` | 跨平台统一时间线；`source=live\|stored`、`format=json\|text\|markdown`、`limit`（默认 30） |
| PUT / DELETE | `/timeline/<entry_id>` | 时间线条目编辑 / 删除 |
| POST | `/{platform}/cache/clear` | 清空平台运行期内存缓存（SQLite 快照不删，前端随后以 `refresh=1` 强制实时） |

### B 站第三方评论与弹幕存档

`GET /api/bilibili/archives?uid=123&source=aicu_reply&page=1&page_size=20`

`source` 可选 `aicu_reply`（评论）、`aicu_danmaku`（视频弹幕）、`danmakus`（直播弹幕及互动）；UID 必须是正整数，页码 1~1000，每页 1~50。只按需查询一页，不使用 B 站 Cookie。成功返回 `events / source_name / source_url / page / total / total_unit / has_more / truncated / fetched_at / cached / notice` 等字段；Danmakus 的分页单位为直播场次，上游页码从 0 开始，由服务端统一转换。参数错误 HTTP 400，上游失败 HTTP 502；5 分钟内存缓存，同源请求间隔至少 2 秒。调研、使用及限制见 [Aicu / Danmakus 接入说明](BILIBILI_ARCHIVES.md)。

## 凭证与多账号

主账号固定 id `primary`（`/credentials` 即它的更新入口，历史记录等私有数据接口固定使用）；
附加账号 id 自动生成，用于多账号并发轮询。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/credentials/<platform>` | 凭证状态（Cookie 掩码显示，不回完整值） |
| POST | `/credentials/<platform>` | 更新主账号 Cookie，body `{"cookie": "k=v; k2=v2"}`，保存后重建适配器立即生效 |
| GET | `/accounts/<platform>` | 账号列表（主账号 + 附加账号）与可用池大小 |
| POST | `/accounts/<platform>` | 添加附加账号，body `{"cookie": "...", "name"?}` |
| POST | `/accounts/<platform>/<account_id>` | 更新账号（主/附加通用），body `{"name"?, "cookie"?, "enabled"?}` 字段可选 |
| DELETE | `/accounts/<platform>/<account_id>` | 删除附加账号（主账号不可删，可停用或经 `/credentials` 覆盖） |
| POST | `/accounts/<platform>/<account_id>/test` | 测试账号 Cookie 可用性（真实调用平台接口探测），返回 `ok / warning / error + latency_ms` |

## 关系图谱

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/graph/search?keyword=xxx` | 跨平台搜索生成关系图；`keywords`（JSON 对象）给单平台指定专属搜索词，`platforms` 限定平台，`limit`（3~20），`refresh=1` 跳过 30 分钟搜索缓存 |
| POST | `/graph/expand/enqueue` | 展开任务批量入队，body `{"graph_id"?, "items": [{platform, uid, ...}]}`；同图同 uid 自动去重，返回 `{queued, duplicates, rejected}` |
| GET | `/graph/expand/results?graph_id=xxx` | 增量轮询展开结果，`since_id` 续拉；返回 `results / cursor / pending / paused` |
| POST | `/graph/expand/stop` | 停止排队任务，body `{"graph_id", "platform"?}`（可选限单平台；执行中任务照常完成） |
| POST | `/graph/expand/resume` | 恢复熔断暂停的平台队列，body `{"platform"?}`，为空恢复全部 |
| GET | `/graph/expand/status` | 各平台队列状态（排队/执行/暂停原因/账号占用） |
| POST | `/graph/refresh_nodes` | 批量重拉节点最新资料（修正大V判定），body `{"nodes": [{platform, uid}, ...]}`，单次 ≤300 |
| POST | `/graph/save` | 按名称保存图谱（同名覆盖） |
| GET | `/graph/saved[/<id>]` | 已保存图谱列表 / 完整数据 |
| DELETE | `/graph/saved/<id>` | 删除已保存图谱 |

## QQ音乐扫码登录

依赖可选 Playwright，未安装时明确报错、其余功能不受影响（见[开发手册](MANUAL.md)第 3 节）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/qqmusic/qr-login/start` | 启动扫码会话，body 可选 `{"uid": ...}` |
| GET | `/qqmusic/qr-login/status` | 轮询登录状态 |
| POST | `/qqmusic/qr-login/stop` | 停止扫码会话 |

## 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/logs/recent?after=seq` | 内存日志缓冲尾部，`after` 增量拉取（SSE 的降级轮询） |
| GET | `/logs/stream?after=seq` | SSE 实时日志流 |

## AI 人物侧写（LangGraph Agent · 原生多模态）

基于 LangGraph `StateGraph` + SQLite Checkpointer（`data/agent_checkpoints.db`）的跨平台智能体接口，模型配置存储于 `credentials/llm.json`（支持 **Google Gemini 原生多模态**、**Anthropic Messages 协议** 与 **OpenAI 兼容协议 / 本地 Ollama**，GET 返回脱敏 Key，同时支持环境变量 `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` / `SIGHT_LLM_*` 兜底）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agent/config` | 获取脱敏后的 LLM 配置（含 `provider / enable_multimodal / supports_vision / supports_video`）与提供商预设 |
| POST | `/agent/config` | 保存 LLM 配置（`provider / base_url / api_key / model / enable_multimodal / temperature / max_steps`），`provider` 可选 `gemini / anthropic / openai_compatible`，留空 `api_key` 保留原密钥 |
| POST | `/agent/config/test` | 探测模型连通性（支持传入未保存草稿字段），返回 `ok / provider / supports_video / latency_ms / reply_preview / error` |
| POST | `/agent/config/models` | 按当前草稿或已保存配置动态拉取可用模型列表（OpenAI `/models`、Anthropic `/v1/models`、Gemini `models.list`），返回 `ok / count / models / latency_ms / error` |
| GET | `/agent/sessions` | 列出已保存的人物侧写档案元信息 |
| POST | `/agent/sessions` | 创建并启动人物侧写，body 支持 `uids`（直通基线采集与多模态视觉基线）或 `target_query`（跨平台搜人 + `interrupt()` 人工确认），可选 `graph_id / focus / auto_confirm / refresh_data / auto_start` |
| GET | `/agent/sessions/<id>` | 获取单条档案完整数据（Markdown 报告、结构化元信息、24h 作息与社交拓扑统计、图文/视频证据账本、盲区、执行轨迹、追问记录） |
| DELETE | `/agent/sessions/<id>` | 删除侧写档案及其 LangGraph Checkpoint |
| POST | `/agent/sessions/<id>/run` | 对已有档案重新执行一次侧写工作流 |
| POST | `/agent/sessions/<id>/resume` | 提交勾选后的 `{"confirmed_accounts": {platform: uid}}`，通过 LangGraph `Command(resume=...)` 从人工确认断点恢复执行 |
| POST | `/agent/sessions/<id>/continue` | 从 LangGraph `SqliteSaver` 失败断点原地续跑（`stream(None, config)`），跳过已完成的基线采集/工具节点 |
| POST | `/agent/sessions/<id>/chat` | 在同一 LangGraph `thread_id` 上发送多轮追问（`{"message": "..."}`），复用证据账本并按需补调工具（含 `inspect_images` / `inspect_video`） |
| POST | `/agent/sessions/<id>/cancel` | 协作式中止正在执行的推理任务 |
| GET | `/agent/sessions/<id>/events?after=seq` | 按游标增量拉取执行事件（SSE 降级轮询） |
| GET | `/agent/sessions/<id>/stream?after=seq` | SSE 实时推送阶段进度、工具轨迹、中断确认、流式报告与追问回复 |
| GET | `/agent/media/<media_id>` | 按严格 24 位十六进制 `media_id` 提供本机防盗链缓存的图片/视频预览（24h TTL，防路径穿越与 SSRF） |
