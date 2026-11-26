# Sight B站开源宣传片 · 设计规格书（DESIGN_SPEC）

- **创作模式**：自主自由创作（用户明确选择）
- **目标平台**：哔哩哔哩（B站）科技 / 开源工具区，面向开发者、AI Agent 爱好者与信息分析研究者，兼顾高完播率与收藏转发转化
- **规格**：1920×1080 @ 30fps，总长 **1300 帧（43.33s，88 拍 @ 122.002 BPM）**，H.264 MP4；固定交付 **带 BGM 版** 与 **无 BGM（仅 SFX）版** 双版本
- **工程目录**：`docs/video/`（独立 Remotion 工程 + 动效工作台清单 `src/workbench.ts`）

---

## 一、阶段 0：产品理解与需求到执行决策表

### 1.1 产品简报
- **产品名称**：**Sight**（多源公开实体画像与社交关系图谱分析平台）
- **开源仓库**：`https://github.com/element-17/Sight`
- **一句话定位**：用一套开源本地工作台，把 8 大公开平台的实体档案、快照 Diff 时间线、ECharts 社交关系图谱与 LangGraph 多模态 AI 人物侧写打通，且支持 Win / Mac / Linux 免 Python 解压即用。
- **必须展示的 6 大核心能力（P4 清单）**：
  1. **8 大公开平台统一聚合**：哔哩哔哩、抖音、小红书、微博、GitHub、网易云音乐、QQ音乐、原神（统一 AdapterPool 多凭证池 + 30 分钟快照缓存）
  2. **跨平台关键词检索与筛选穿透**：快速搜索昵称/UID，聚合展示并直达档案
  3. **ECharts 6 交互式社交关系图谱 + 实时 SSE 终端**：绿线互关 / 红线同名归并 / 蓝箭头单向关注 + 异步展开队列（限速/熔断/断点续拉）+ 实时终端日志
  4. **时序快照 Diff 与行为演化时间线**：逐对快照集合 Diff，自动推断跨平台变更时间窗口
  5. **LangGraph 原生多模态 AI 人物侧写**：看图/看视频 + 24h 作息统计 + `[E#]` 可点击零幻觉证据溯源 + Gemini / Claude / OpenAI 兼容 + 多轮追问
  6. **开源免费 · 跨平台一键包交付**：GitHub Releases 提供 Win / Mac / Linux 预打包可执行程序

### 1.2 需求到执行决策表
| 需求约束 | 执行决定 | 依据 |
|---|---|---|
| 发布平台 = B站，要吸引流量 | 43.3s 紧致高密节奏；前 3 秒用 `text-as-mask` 巨字透视雷达图谱制造强视觉钩子；强鼓点 House BGM 全程整拍对齐；底部解说字幕采用 56px 粗体中文字幕胶囊（手机端一秒读清，满足 Q11） | B站科技开源区黄金 3 秒留存 + 手机端竖握横屏小窗高占比 |
| 产品视觉还原 | 100% 从 `frontend/src/style.css` 提取原生浅灰白 + 钴蓝 `#3565e0` + 8 平台色点 + 蓝眼睛 Logo；仅在 S2 剧场聚光与 S6 悬窗文档使用克制的深海蓝灰暗场（`#0c1426`）凸显亮面 UI，绝不漂移至 Ink Press 暖纸琥珀或赛博霓虹 | `SKILL.md` 核心理念 #2 & `final-review.md` V1–V4 |
| 数据安全与合规（红线） | **严禁使用本地 `data/snapshots.db` 与 `credentials/` 中的真实数据**。通过 Playwright 拦截 `/api/**` 注入完全虚构的开源创作者演示角色「**林屿森 / linyusen-dev**」（原创 SVG 头像与作品封面，零外部 CDN、零真实人物隐私、零密钥），片尾加注清晰合规免责提示 | 本地检测存在 113MB 真实库与凭证；公开上传 B站必须零隐私风险 |
| BGM 与音效 | 选用 `assets/audio/bgm/house-vibez.mp3`（Mixkit Stock Music Free License，URL 可核查），librosa 实测 `BPM=122.0019`，`t0=0.066905s`，`T=0.491795s`（1x 匹配率 98.28%，均值误差 9.95ms）。所有 SFX 通过 `sfx-source.py` 从 Freesound 下载 CC0/CC BY 素材并保留 manifest 与署名；终渲固定输出 `sight-promo.mp4` 与 `sight-promo-nobgm.mp4` | `music-beat-sync.md` & `sfx-sourcing.md` |

---

## 二、阶段 1：视觉方向、色板与动效性格 Tokens

### 2.1 三候选方向评估与选定
1. **方向 A（选定）：「极简情报工作台 · 冷白钴蓝（Sight Native）」**
   - 直接生长自 Sight 源码设计系统：浅灰白画布 `#f6f7f9`、纯白卡面 `#ffffff`、细描边 `#e6e8eb`、深炭墨 `#1c1f23`、主强调色 Sight 钴蓝 `#3565e0`（高饱和深机器蓝 `#1d4ed8` 用于扫描准星），辅以 8 平台色点（B站粉 `#fb7299`、抖音红 `#fe2c55`、QQ音乐绿 `#31c27c`、微博橙 `#e6702e` 等）；S2/S6 两处重点聚焦段以深蓝灰 `#0b1222` 舞台衬托亮面真实页面，形成呼吸感明暗节奏。
2. 方向 B（弃用）：纯黑赛博雷达风 —— 与 Sight 真实浅色 UI 割裂，易产生「换皮包装感」（违反 V3）。
3. 方向 C（弃用）：暖纸编辑杂志风（Ink Press） —— 气质偏文艺阅读而非工程情报分析，且暖琥珀与 Sight 钴蓝冲突。

### 2.2 设计系统 Tokens
- **颜色**：`--bg: #f6f7f9` · `--surface: #ffffff` · `--border: #e6e8eb` · `--ink: #1c1f23` · `--ink-2: #5c6470` · `--accent: #3565e0` · `--accent-deep: #1d4ed8` · `--accent-soft: #edf2fd` · `--stage-dark: #0b1222` · `--success: #1e9e55` · `--danger: #d5372f`
- **字体**：中文/无衬线 `PingFang SC, Microsoft YaHei, -apple-system, Segoe UI, sans-serif`；等宽数字/标签 `JetBrains Mono, Cascadia Mono, Consolas, monospace`（`tabular-nums`）
- **字号阶梯（严格遵守 Q11）**：大字标 `116–420px` · 字卡标题 `88–104px` · 场景解说主字幕 **`56px`（有效字高 ≥5.2% 帧高）** · 辅助/副标/URL **`34–38px`（≥3% 帧高）**
- **禁用风格**：禁止暖纸米黄（`#f2eee6`）、琥珀棕（`#955905`）、赛博紫粉霓虹、游戏提示音、手持抖动（Q3）、群发卡片扫光（Q4）。

### 2.3 品牌 → 动效性格 Tokens
- 品牌坐标：**中高能量 × 理性工程感**（介于「专业信赖」与「活力大胆」之间，三个关键词：**精准、克制、利落**）
- 主入场时长：`18–22f @ 30fps`；主入场缓动：`bezier(0.16, 1, 0.3, 1)`（snappy）；落地过冲仅用于物理飞入/落位（`bezier(0.34, 1.4, 0.44, 1)`，y1 > 1）；品牌字标落定 hold ≥ 30f（R1），批量动效收尾 ≥ 15f 静止（R2），单主角弧 ≥ 3.6s（R3）。

---

## 三、阶段 2：功能到镜头卡映射表（全片零手法重复）

| 序号 | 承载功能 | Gallery 镜头卡 (`style-key`) | 参考实现 TSX | 页面素材来源 |
|---|---|---|---|---|
| S1 | 品牌钩子 & 一句话定位 | `text-as-mask` (`text-as-mask`) | `demos/opening/text-as-mask/TextAsMask.tsx` | 瓷白舞台 + Sight 暗色实时图谱视口（非复刻抽象开场） |
| S2 | 8 大平台统一聚合档案（单主角立传） | `spotlight-hero-card` (`spotlight-hero-card`) | `demos/opening/spotlight-hero-card/SpotlightHeroCard.tsx` | 真实截图 `platform-full.png` (2x) + `profile-card-hires.png` (4x) |
| C1 | 呼吸引导字卡①（8大平台） | `paper-title-card` (`paper-title-card`) | `demos/typography/paper-title-card/PaperTitleCard.tsx` | Sight 冷白钴蓝换肤 + `DigitRoll`（`8` 大平台） |
| S3 | 跨平台关键词搜索与筛选穿透 | `type-and-filter` (`type-and-filter`) | `demos/interaction/type-and-filter/TypeAndFilter.tsx` | 真实截图 `platform-empty.png` + 6 张内容卡 cutout + 搜索框坐标 |
| S4 | ECharts 6 交互式关系图谱 + 实时 SSE 终端 | `scanline-annotate-focus` (`scanline-annotate-focus`) | `demos/effects/scanline-annotate-focus/ScanlineAnnotateFocus.tsx` | 真实截图 `graph-full.png` (2x，含 24 节点图谱与 SSE 终端条) |
| C2 | 呼吸引导字卡②（快照 Diff） | `paper-title-card` (`paper-title-card`) | `demos/typography/paper-title-card/PaperTitleCard.tsx` | Sight 冷白钴蓝换肤 |
| S5 | 时序快照 Diff 与行为演化时间线 | `list-stack-press` (`list-stack-press`) | `demos/ui-entrance/list-stack-press/ListStackPress.tsx` | 真实截图 `timeline-full.png` (2x) + 5 条时间线条目 cutout |
| C3 | 呼吸引导字卡③（AI 多模态侧写） | `paper-title-card` (`paper-title-card`) | `demos/typography/paper-title-card/PaperTitleCard.tsx` | Sight 冷白钴蓝换肤 |
| S6 | LangGraph 原生多模态 AI 人物侧写（`[E#]` 溯源） | `document-typewriter-reveal` (`document-typewriter-reveal`) | `demos/ui-entrance/document-typewriter-reveal/DocumentTypewriterReveal.tsx` | 真实截图 `agent-full.png` (2x，完整三栏真排版) + 文本块与侧栏坐标 |
| S7 | 发布会合影峰值收场 + 开源免费一键包 CTA | `outro-group-photo-launch` (`outro-group-photo-launch`) | `demos/outro/outro-group-photo-launch/OutroGroupPhotoLaunch.tsx` | 9 件全片真实元素切片（侧栏/档案/作品/搜索/图谱/节点/时间线/AI证据/终端） |

---

## 四、阶段 3：BGM 节拍结构与完整帧级分镜表

### 4.1 音乐结构与网格验收（`analysis/beat_data.json` & `grid_drift.json`）
- **曲目**：`house-vibez.mp3`（Lily J · House · Mixkit Stock Music Free License）
- **源分析真值**：`BPM = 122.0019` · `SOURCE_BEAT0 = 0.066905s` · `BEAT_INT = 0.491795s`
- **获胜网格**：`1x`（`match_rate = 98.28% ≥ 98%` · `mean_abs_ms = 9.95ms < 10ms` · `first_active_beat_dist_ms = 6.02ms`）
- **能量曲线与最强 Slam 分配（R4 硬上限：全画面冲击 ≤3 处，间隔 ≥16 拍）**：
  - `b0–b28`（RMS ~0.20）：稳健起步 → S1 品牌开场 + S2 单主角立传 + 字卡①
  - `b28–b60`（RMS 0.23–0.25）：能量抬升 → S3 搜索筛选 + S4 关系图谱扫描 + 字卡② + S5 时间线堆叠
  - `b64–b88`（RMS 0.26–0.28 全曲副歌高潮）：字卡③起跳 → S6 AI 多模态侧写 → S7 发布会合影终极高潮
  - 全画面冲击仅 2 处（远低于 R4 ≤3 处上限）：① `b12`（S1 字腔冲入接管完成）② `b36`（S3 点击穿透 `FlashCut` 转场切入图谱），间隔 24 拍（≥16 拍）；S7 字标砸落（`b80`）为元素级重音。

### 4.2 帧级分镜与时间轴（`FPS = 30`，所有切点按 `beatF(n)` 整拍锚定）

| # | 拍号区间 | 帧区间（时长） | 镜头组件 | 镜头卡 | 主动作与页面状态 | 底部解说字幕（56px） / 字卡文案 | 转场与 SFX 规划 |
|---|---|---|---|---|---|---|---|
| S1 | b0–b12 | 0–179 (179f / 6.0s) | `SceneMaskOpen.tsx` | `text-as-mask` | 瓷白舞台切出巨型 `SIGHT` 字形，内透暗色 8 平台实时雷达流线平移；品牌眉题+蓝眼睛标志落定 hold > 1s → f112 吸气 → f120 指数冲入 46× 切入产品 | 眉题「开源 · 8大平台实体图谱与 AI 侧写」/ 副题「从碎片公开信息，一键构建完整数字画像」 | 无额外叠加；起手 soft whoosh + 冲入 riser-whoosh |
| S2 | b12–b24 | 179–356 (177f / 5.9s) | `SceneSpotlightHero.tsx` | `spotlight-hero-card` | 真实 Sight B站平台页压暗成深蓝剧场，聚光游走 3 站锁定主角档案卡（4x 高清），斜侧推进（rotY 34°）弹起悬浮 + 钴蓝轮廓光扫两圈 + 3D 同空间注记「8 大公开平台 / 统一画像聚合」→ 落回原位 hold 35f | 「8 大平台统一聚合，30 分钟快照智能缓存」 | 推闸机械音 + 弹起 whoosh + 轮廓光 sparkle + 落地 snap |
| C1 | b24–b28 | 356–415 (59f / 2.0s) | `SightTitleCard.tsx` | `paper-title-card` | Sight 冷白底逐词压印 + 钴蓝下划线 + `DigitRoll` 滚动数字 `8` | 「8 大公开平台，*一屏*实时检索」· 副标 `8 大公开平台全量接入` | 轻快 swoosh 入场，尾 8f 淡出 |
| S3 | b28–b36 | 415–533 (118f / 3.9s) | `SceneTypeFilter.tsx` | `type-and-filter` | 真实 Sight 平台页贴近搜索框，3f/字真人打出「林屿森」→ 11f 呼吸拉开全景 → 非目标作品卡错峰淡出下沉，目标卡滑入首行真实槽位 → 指针滑入双圈钴蓝点击 → 推进交棒 | 「输入昵称或 UID，秒级跨平台检索定位」 | 键盘打字（按字数严格截断）+ 筛选 whoosh + 真实快门 click + **FlashCut @b36** |
| S4 | b36–b48 | 533–710 (177f / 5.9s) | `SceneGraphScan.tsx` | `scanline-annotate-focus` | 浏览器窗内真实 `ViewGraph`（ECharts 6 24 节点跨平台关系图 + SSE 实时终端条）；深蓝扫描线严格匀速掠过，依次锁出 5 个真实区块并打字贴签，顶栏实时计数 `05/05 → GRAPH LOCKED`，hold 65f 读图 | 「ECharts 6 社交关系图谱，互关与同名自动归并」 | 扫描启动微嗡 + 5 次错峰机械对焦咔哒（双样本交替降音量防机枪） |
| C2 | b48–b52 | 710–769 (59f / 2.0s) | `SightTitleCard.tsx` | `paper-title-card` | Sight 冷白底逐词压印 + 钴蓝下划线 | 「时序快照 *Diff*，自动还原行为时间线」 | 同类字卡统一 swoosh |
| S5 | b52–b60 | 769–887 (118f / 3.9s) | `SceneTimelineStack.tsx` | `list-stack-press` | 正视机位真实 `ViewTimeline` 实时对比页；计数器预备拍后 5 条跨平台 Diff 卡自底逐张压弹摞起（整摞压下 6px 弹回 + 滞后高亮条 + 右上 `DigitRoll` 滚至 `05`）+ 末尾单次柔光扫过 + 静止呼吸 | 「逐对快照自动 Diff，精准推断跨时段变更窗口」 | 入场 transition + 5 连轻落 pop（递减音量防机枪）+ 计数落定 click |
| C3 | b60–b64 | 887–946 (59f / 2.0s) | `SightTitleCard.tsx` | `paper-title-card` | Sight 冷白底逐词压印 + 副标说明多模型协议 | 「LangGraph 多模态 *AI*，带证据溯源侧写」· 副标 `Gemini · Claude · OpenAI 原生看图看视频` | 同类字卡统一 swoosh |
| S6 | b64–b76 | 946–1123 (177f / 5.9s) | `SceneAgentReveal.tsx` | `document-typewriter-reveal` | 深海蓝灰暗场悬浮真实 `ViewAgent` 完整三栏出版级窗：斜侧特写起，Markdown 侧写报告（含 24h 作息图与 `[E1]`–`[E5]` 角标）两两成对打字揭示 + 钴蓝笔尖 → 相机平滑后撤至全窗，左右双栏揭开 + 右侧 6 条证据/轨迹逐条弹落 + 底部 84px 标语 | 「原生看图看视频，每条侧写结论皆可点击溯源」 + 窗底大标语「每条结论，*皆有据可查*」 | 键盘打字（严格裁剪等长）+ 6 连证据落轨 pop（音量阶梯递减） |
| S7 | b76–b88 | 1123–1300 (177f / 5.9s) | `SceneOutroLaunch.tsx` | `outro-group-photo-launch` | 9 件全片功能元素切片四方过冲飞入合影 → crane 落下 + 钴蓝舞台光 + 冰蓝微粒 → **Sight 蓝眼睛 Logo + 字标** letterpress 砸落（踩 `b80`）→ 延长线射出 → 大号开源免费 CTA + GitHub 地址，**hold 满 60f (2.0s)**，末 12f 优雅熄灯 | 无底部解说字幕（C1 例外）；画面中央大号 CTA「开源免费 · Win / Mac / Linux 解压即用 · github.com/element-17/Sight」 | 固定三拍句式：**riser → impact（全片峰值 @b80）→ sparkle** |

---

## 五、演示数据合规冻结声明（阶段 0 & 4 冻结）
- 虚构演示目标实体：**林屿森（`linyusen-dev` / UID `88421036`）**，设定为虚构独立全栈开源创作者（坐标：杭州，研究方向：前端可视化与 AI 工具链）。
- 所有头像、封面图、作品标题、歌单名称、关系图谱好友昵称（如「江晚舟」「陈知遥」「陆星河」「周明远」「许知意」等）均为 100% 原创虚构，经 Playwright 拦截 `/api/**` 注入，**零访问、零读取本机 `data/` 或 `credentials/` 目录**。
- 片尾底部加注克制合规提示：`演示数据均为虚构 · 仅用于公开数据工程与图谱可视化研究学习`。
