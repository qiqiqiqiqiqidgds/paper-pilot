# Changelog

所有项目的显著变更都会记录在此文件。

## [Unreleased] - 2026-09-09（全面检查修复闭环：2 P0 / 5 P1 / 9 P2 / 19 P3 全部修复验收）

针对 2026-09-08 全面检查报告的问题清单，经五批「修改子代理修改 → 独立子代理验收」循环（每批全部 PASS 才进入下一批）全部修复并逐一验收通过；浏览器复测还新发现并修复了「引用跳转按钮从不传递引文文本」这一被原报告误诊归因的深层缺陷（引用高亮链路断裂的另一半根因）。完整报告见 [docs/audit/audit-2026-09-09.md](docs/audit/audit-2026-09-09.md)。

### 🐛 修复
- **后端 12 项**：带书签 TOC 的 PDF 上传必现 500（P0，`get_toc(simple=True)` + 防御性归一化）；PPT 裁剪孤儿 part 与 zip 重复条目；Reduce 输入无上限（章节雪崩 + prompt 超上下文）；非流式分析对部分章节失败零提示；P2 五项（同页多标题丢章、失败日志残留论文内容、JSON 非原子写、400 回显未清洗输入、xml.etree 改 defusedxml）；P3 九项（smoke_test 重写、死代码/死依赖清理、健康检查收敛、IPv6 限流归一化、Semaphore 可配置、提示词注入缓解、论文列表排序、生命周期清理）
- **前端 12 项 + 1 个新发现缺陷**：`<Document options>` 未 memo 化导致整本反复重载（P0）；compare/PPT loading 锁随组件卸载丢失（P1）；同页多次引用跳转旧高亮残留（P1）；引用按钮不传引文文本（新发现）；P2 四项 + 移动端 375px 布局（兜底全文搜索并发化、反代同源校验 403、状态面板枚举错判、上传可取消）；P3 八项（死代码清理、useIsMobile 抽取、下载超时、pagehide、假页码文案、a11y 等）

### 🧪 验证
- 后端 pytest **245 passed**（基线 194 + 新增 51）、ruff 零告警
- 前端 tsc --noEmit / eslint 零错误零警告、vitest 8 文件 79 用例全过、next build 成功
- 带书签 PDF 真实服务上传 200；浏览器黑盒实测 12 项全绿（缩放不回弹、引用跳转高亮出现、375px 无横向溢出等）

## [Unreleased] - 2026-09-06（收尾审查：双子代理全量代码审查 + GUI 黑盒实测）

前端、后端各由一个子代理做全量只读代码审查（前端含 tsc/eslint/vitest 全绿确认），主代理另用内建浏览器对前端做全流程 GUI 黑盒实测，主链路全部跑通。结论：后端未达收尾状态（2 个 P0，但修复量小）；前端基本达到收尾状态（1 个 P1 + 4 个 P2 建议先修）。完整报告见 [docs/audit/audit-2026-09-06.md](docs/audit/audit-2026-09-06.md)。

### 主要发现（P0–P2）
- **P0 ×2（后端）**：跑一次 pytest 会静默清空真实论文库（conftest 未注入 `DATA_DIR` + test_e2e 对真实目录 rmtree，已实际造成数据丢失）；生产环境启动/每 6 小时的清理会无差别删除 7 天前的 PPT（即使论文还在）
- **P1**：LLM 返回带 ```json 围栏/截断内容时解析失败，导致拆解整链失败（GUI 实测复现）；流式分析取消按钮竞态（旧流退出时清掉新流的取消句柄）；XFF 取最左段，公网部署限流可被伪造头绕过；后端另列 5 项 P1（SSE 断连取消传播脆弱、上传整文件驻留内存、论文列表全量 json.loads、`str(e)` 直接透出等）
- **P2**：论文详情加载失败后 PDF 区永久卡「正在摊开这一页…」无重试；DOCX 拉取无超时/无中止，弱网即卡死；react-pdf 未配置 cMapUrl，部分中文 PDF 渲染空白、引用高亮失效；标题提取 bug（标题被提取为正文截断句并拼入 PPT 文件名）；后端审查另列 8 项 P2、前端 4 项 P2（含 resizable-pane 全文件死代码、文档口径与实际不符）
- **GUI 实测新发现 4 个代码审查未覆盖问题**：引用文本高亮静默失败、PPT 成功卡不持久、书卡对比勾选框零反馈、删除按钮上半截被裁切

## [Unreleased] - 2026-09-05（最终验收：双子代理独立审计，判定可交付）

两个子代理以独立验收者身份对全部历史修复做逐条清单审计（后端 14 项、前端 20 项）并实际运行测试套件：

- **后端 14/14 PASS**：pytest 185 passed / 2 skipped（条件跳过）、ruff 全绿、6 个 router 全部加载、dev 下 /docs 正常注册
- **前端 20/20 PASS**：tsc 0 错误、eslint 0 问题、vitest 79/79、next build 成功
- 全库无裸 `except:`、无 `as any`/`@ts-ignore`/TODO 残留；python-multipart 已在修复 CVE 的版本
- 阻断项扫描：**零**。判定：**可交付**
- 浏览器端到端 smoke（截图确认）：上传 → 论文列表 → 选中 → 缓存回填（拆解/创新/对比）→ 对比表渲染 → PDF 渲染 → 暗色模式，全链路正常

### 部署提醒（非代码缺陷）
当前 `backend/.env` 为 `APP_ENV=dev + APP_HOST=0.0.0.0 + 无 APP_API_KEY`（局域网可访问、可消耗 LLM token，启动日志有双警告）。任何超出单机开发的部署必须：设置 `APP_API_KEY` + `APP_ENV=prod`（代码会强制校验，prod 下 /docs 自动关闭）、建议 `APP_HOST=127.0.0.1` 或内网 IP、**轮换已随目录分发的 LLM_API_KEY**。

### 有意遗留（后续 Sprint）
后端：Map-Reduce 双实现合并、text.json 三重存储瘦身、_list_papers_sync 全量解析、SSE 422 逃逸、页数上限、PPT 7 天死链、arXiv 锁内 sleep、死代码清理、tiktoken、smoke_test 重写。前端：组件测试（@testing-library/react 已就位，优先 pdf-viewer/upload-button）、applyHighlight 性能、markdown 渲染、分割位置持久化、页码跳转输入、上传取消。

## [Unreleased] - 2026-09-05（第八轮：契约一致性专项审查 + 修复闭环）

两个子代理以新角度（前后端契约逐字段核对 + 前两轮未深审文件）复查：**无 P0/P1**，SSE 全部 12 种事件 payload 与前端 switch 一一对齐、枚举值一致、渲染守卫完备。发现并修复：

### 🐛 修复
- **（P2）`prompts/breakdown.py` null 漏网**：abstract `[:500]` 切片 ×3、authors join ×2 对显式 null 抛 TypeError → 误导性 502「LLM 调用失败」（第七轮兜底唯独漏了本文件）；统一 `or` 兜底 + 补 3 条 prompt 构造的 null 回归测试
- **（P2）`analyze.py`/`search.py` 对 `meta` 键本身为 null 无防御**（与 compare_papers/ppt 不对称）→ 4 处统一 `data.get("meta") or {}`
- **（P2）非 SSE `/api/analyze` 的结果落盘是全项目唯一裸调用点**：落盘异常（论文删除竞态/磁盘满）会让已花 token 的分析以 500 收场 → try/except + warning，与 SSE/compare 路径约定一致
- **（P2）后端 PPT `warnings` 字段前端从不展示**：勾选「包含局限性页」但 flaws 缺失时静默少页 → `ppt-view.tsx` toast.warning + 结果卡片内 ⚠️ 行渲染（浏览器实测确认）
- **（P2）创新/漏洞视图移动端跳转不关抽屉**（F19 只覆盖了 QuoteBlock）：跳转发生在被遮挡的 PDF 上等于点击无反应 → 「关抽屉」下沉到 page.tsx 的 `onJumpToPDF` 分发点统一处理
- **（P3）前端超时与后端超时贴边/超界**：analyze 300s == 后端 300s（网络耗时会让前端先 abort）→ 360s；compare/comparePapers 300s < 后端最坏 ~490s（搜索重试 + LLM）→ 600s；同步更新超时单测
- **（P3）契约失真**：`deletePaper` 声明 `{ok:true}` 实际 data=null → `request<null>`；`PaperInfo.abstract` 声明必填但列表接口从不返回 → optional；`GET /api/papers/{id}` 的 filename 返回 `raw.pdf` 与列表口径不一致 → 优先 `meta.original_filename`
- **（P3）导出**：compare_table 单元格含换行会破坏 Markdown 表格 → 换行替换为空格；仅空 compare（4001 空壳）时 `hasAnyAnalysisResult` 误报"有结果" → 排除
- **（P3）`start_dev.ps1` 探活 `/docs`**：prod 下 /docs 已关闭会永远误报"后端未就绪" → 改探 `/api/health`
- **（P3）CI 遗留**：Build 步骤仍注入前 BFF 时代的 `NEXT_PUBLIC_API_BASE/API_KEY`（全前端零引用）→ 改为 `BACKEND_URL/BACKEND_API_KEY` 占位；eslint 范围补 `tests`
- 右侧 AI 面板 ErrorBoundary 补 `key={currentPaperId}`（其 activeTab 等状态本就随论文切换重置，重挂无副作用）；paper-store 过期注释修正

### 🧪 验证
- 后端 **185 passed**（+1 breakdown prompts null）+ ruff 全绿
- 前端 **79 passed**（超时/导出断言同步新行为）+ tsc + eslint + next build 全绿
- 浏览器实测：PPT 勾选缺失分析生成 → 警告 toast 弹出 + 结果卡片 ⚠️ 行渲染正常（截图确认）

## [Unreleased] - 2026-09-05（第七轮复查：双子代理交叉验证 + 缺口闭环）

两个独立子代理分别复查前后端全部源码，验证第七轮修复（后端 19 项中 18 项完全落地、前端 21 项中 20 项完全落地），发现并当场修复以下问题：

### 🐛 本轮复查发现并修复
- **（P1）生产环境 `/docs` 收敛实际未生效**：上轮只在中间件公开路径集合里做了 prod 剔除，但 auth/ratelimit 对非 `/api/*` 路径直接放行、`main.py` 又无条件注册 docs/redoc，prod 剔除分支是死代码。现在改为路由注册层关闭：`_schema_urls()` 在 `APP_ENV=prod` 时返回 `docs_url/redoc_url/openapi_url=None`，并补单测钉住（`test_schema_urls_gated_by_env`）
- **（P1）新测试文件 tsc 类型错误**：`robustness.test.ts` 手写 `analyzing: null as string | null` 与 `AnalysisType | null` 冲突，`tsc --noEmit` 失败（vitest 不查型所以此前未暴露）。改为 `Partial<PaperState>` 标注并导出 `PaperState`
- **（P2）PPT 标题页 `meta.authors=null` → 500**：第七轮 null 兜底漏了 `ppt_generator.py` 的 authors 路径（`:195/:361` 两处 `get` 默认值不防显式 null），补 `or []` + e2e 断言
- **（P2）`.slice` 系列 null 守卫**：compare_table 单元格 / 优劣势 / 适用场景 / 核心要点的 key 计算对 null 元素会 TypeError（旧缓存经缓存回填路径进入时），统一 `String(x ?? "")` 兜底
- **（P3）pointercancel 时 `releasePointerCapture` 抛 NotFoundError 会跳过 onResize 提交** → try/catch 包住
- **（P3）consumeSSE 的 CRLF 归一挪到 buf 层**：逐 chunk 替换漏跨 chunk 边界的 `\r\n`
- **（P3）`get_analysis` 对损坏 JSON 返回 400** → 改 500「分析结果文件损坏，请重新运行该分析」（语义修正）+ 读/解析整体入线程池
- **（P3）`save_upload_file` 失败残留空目录** → except 里同步清理
- **（P3）`core_innovations` 迭代过滤非 dict 元素**（与 related_papers 同型防护）
- **（P3）`pdfjs-exports-patch.cjs` 正则失配静默 no-op** → 失配时显式 console.warn（pdfjs-dist 升级即踩雷的坑）
- **（P3）`handleDoubleClick` 注释与实现不符** → 修正注释；`.env.example` 昂贵接口清单补 `/api/upload`

### ✅ 复查确认无问题的高风险点
- `asyncio.timeout` 异常捕获顺序 / CancelledError 穿透 / SSE background_tasks 取消链完整
- `save_ppt` 的 `except BaseException` 不会误捕 CancelledError（to_thread 工作线程内不可取消）
- CSS 变量拖拽方案与 React 受控 style 自洽、两层 var 解析链成立、lastPctRef 永不发散
- ThemeToaster 无 SSR 水合问题；jumpToPageRef latest-ref 模式无 stale 风险；globalUploading 卸载后必复位

### 🧪 验证
- 后端 **184 passed**（+3：authors null / 损坏 JSON 500 / schema 收敛开关）+ ruff 全绿
- 前端 **77 passed** + tsc + eslint + next build 全绿（tsc 错误已修复，本轮验收声明真实成立）

## [Unreleased] - 2026-09-05（第七轮：双端深度审查驱动的健壮性/安全/性能修复）

### 🐛 后端修复
- **`_strip_think_tags` 大小写绕过**：快速路径大小写敏感检查与 IGNORECASE 主正则矛盾，`<Think>` 变体会漏剥离导致 json.loads 失败。改用与主正则同语义的探测正则（llm_client.py）
- **`chat_json` 不再原地修改调用方 messages**：浅拷贝后追加 JSON 指令，复用/重试同一 messages 列表不会重复追加
- **`response_format=json_object` 兼容降级**：不支持该参数的 OpenAI 兼容网关返回 400 时，去掉参数重试一次（system prompt 已强调 JSON），不再全功能不可用
- **legacy 整篇分析整体超时**：innovation/flaws/compare 的 LLM 调用此前无外层超时（SDK 120s×4 次重试最坏挂 ~8 分钟），现统一包 `asyncio.timeout(LLM_TIMEOUT_SECONDS)` → 502；新增 `LLM_REQUEST_TIMEOUT_SECONDS` 配置单次请求超时（原硬编码 120s）
- **compare 不再吞搜索异常**：搜索供应商故障返回 502「联网搜索失败」，不再伪装成 code=4001「未搜到相关工作」误导用户
- **null 兜底**：`abstract`/`title`/`authors` 为显式 null（损坏/旧数据）时多处切片/拼接不再 TypeError（compare_papers / prompts.compare / search / ppt 文件名）
- **上传幽灵目录**：save_text_json 失败（磁盘满/权限）时清理论文目录并返回 500，不再留下"列表里看不见、分析 404"的残缺目录
- **PPT 生成健壮性**：`related_papers[].title` 硬索引改 `.get()` 兜底（LLM 输出缺键不再 500）；save_ppt 临时文件清理失败不再吞掉原始异常
- **router 懒加载不再吞真实 bug**：非 ImportError（代码错误）直接终止启动，只有缺依赖才降级
- **docx `p.style.name` 判空**（与同文件其他位置一致）+ 限流桶清理注释与实现对齐、改 `time.monotonic()`
- **uploaded_at 带时区偏移**：跨时区/DST 部署下列表排序不再错乱

### ⚡ 后端性能（B5 读侧补全）
- `load_text_json_async` / `save_analysis_result_async` 新增异步版：analyze（含 SSE 入口）/ search / compare / compare-papers / ppt / get_paper / delete_paper / get_paper_file 等 10+ 处重 IO（数 MB text.json 解析、rmtree、stat）全部移出事件循环，不再阻塞所有并发请求（含他人 SSE 流）

### 🔒 后端安全收敛
- **异常详情泄露与 `APP_DEBUG` 绑定**：不再按 `APP_ENV=dev`（默认值）回显内部异常，显式开启调试才回显
- **X-Request-ID 清洗**：客户端传入需匹配 `^[A-Za-z0-9_-]{8,64}$`，否则重新生成（防伪造/日志膨胀）
- **生产环境收敛 `/docs` `/redoc` `/openapi.json`**（公开路径集合随 `is_production` 变化）
- **XFF 信任逻辑去重**：auth/ratelimit 双拷贝抽取到 `utils/proxy.py` 统一维护
- `.env.example` 修正误导性注释（dev 下 0.0.0.0+无 key 是允许启动的），启动警告补充 APP_ENV=prod 提示与 0.0.0.0 风险提示

### 🐛 前端修复
- **analyzeStream 并发锁与 analyze 对齐**：任意类型分析进行中时不再发起新流（旧实现只拦同类型，错误框"重试"按钮可并发两个 LLM 任务）；重试按钮补 `disabled`
- **移动端删除按钮可见**：`max-lg:opacity-100`（<lg 无 hover，旧实现隐形但可点击，存在误删风险）
- **列表 key 防碰撞**：创新点/相关论文/对比表格行统一 index+内容前缀（LLM 同名输出、arXiv v1/v2 不再 key 冲突）
- **`request()` 200+非 JSON 容错**：网关故障页抛可读错误而非 "Unexpected token '<'"
- **SSE 解析容错**：CRLF 帧归一、多行 data 按 SSE 规范 `\n` 连接、generator 提前退出时 `reader.cancel()` 主动断连（不再依赖外层 abort）
- **setCurrentPaper 失败早退**：详情请求失败不再连打 4 个注定失败的缓存请求；缓存回填改 `Promise.all` 并行（高延迟下省 3×RTT）
- **SSE 载荷轻量校验**：chapters/map/progress/reduce/error 载荷字段缺失时兜底，不再让 NaN/undefined 进入 UI
- **XHR header 重建**：按第一个冒号切分，值含 `": "`（如带引号文件名）不再截断
- **暗色模式 toast**：新增 `ThemeToaster` 读取 `resolvedTheme`，sonner 不再恒为亮色
- **fallback_legacy 进度显示**：整篇模式显示"正在分析全文…"+ 50% 进行态，不再显示 "0 / 0 章节"
- **定时器/finally 清理**：CopyButton / UploadButton 定时器句柄化；CompareView/PPTView finally 无条件复位 loading（去掉对卸载时序的隐式依赖）
- **跨实例上传守卫**：模块级 `globalUploading` 标志，顶栏/空态两个 UploadButton 不能再并发上传
- **死代码清理**：store `currentPage/setCurrentPage`、`api.searchRelated`、`PDFViewerHandle`；LLM 超时文档漂移修正

### ⚡ 前端性能
- **拖拽分割条零重渲染**：拖拽期间位置经 CSS 变量 `--panel-split` 直写 flex 容器（右侧面板宽度引用该变量），pointerup 才提交 React state——不再以 60Hz 触发 HomePage 全树（论文列表/PDF 区/分析视图）重渲染
- pdf-viewer 事件监听 effect 只挂载一次（旧实现每次渲染重挂 3 个 window listener，handler 经 ref 取最新实现）
- ErrorBoundary 增加 `key={currentPaperId}`：切换论文自动复位错误态

### 🔒 前端安全
- BFF 代理同源校验：multipart/form-data 是 CORS simple request 不触发预检，现校验 Origin/Referer 与 Host 同源（缺失视为同源工具放行），防任意网页跨站投递上传请求

### 🧪 测试
- 后端 166 → **181 passed**（新增 `test_robustness_fixes.py` 7 例：legacy 超时/根因透出/null meta/幽灵目录/PPT null 标题/request-id 清洗；`test_llm_client.py` 新增 think-tag 大小写/messages 不可变/response_format 降级 7 例；compare 搜索故障 502 e2e 1 例）
- 前端 70 → **77 passed**（新增 `robustness.test.ts` 7 例：CRLF 帧/多行 data/提前退出 cancel/200+HTML 容错/并发锁）
- ruff / eslint / tsc / next build 全绿；真实 uvicorn 启动 smoke（health / request-id 回显与清洗 / docs / papers）通过

## [Unreleased] - 2026-08-06（第六轮：子代理验证驱动的缺陷修复）

### 🐛 修复（子代理独立验证发现的缺陷）
- **jumpToPage 竞态防护**：连续点击引用时旧异步流程（全文定位耗时数秒）会覆盖新跳转的目标页/误高亮/误 toast。新增 `jumpTokenRef` token 机制，所有异步回调点（numPages 重试 / 100ms / 全文定位 await 后 / 150ms 二次高亮）均校验 `isCurrent()`；`highlightInTextLayer` 增加 `isCurrent` 回调，轮询期间新跳转即作废
- **fade 渐隐 650ms 清理定时器未跟踪**：会在高亮后 3.0-3.65s 窗口内误清新高亮并取消其渐隐。650ms 定时器句柄存入同一 `highlightFadeTimer` 槽位，新跳转自动取消旧定时器
- **切换论文时 pdfjs refs 重置**（含跳转 token 失效）：过渡窗口不再用旧文档搜索/旧页码跳转新论文
- **纯页码标注引用静默跳过**：无可搜内容不弹误导 toast
- **高亮轮询等 span 就绪**：text layer 容器存在但内部 span 未填充时继续轮询，避免空容器直接判定失败
- **section-quotes 注释对齐 + 关键词补充**（architecture/benchmark/ablation/case study/limitation/purpose）

### 🧪 验证
- 子代理独立验证：6/6 修复生效、无新问题（tsc + 53 用例全绿）；残留项（token 论文切换失效）已修复
- 前端 53 passed / tsc / eslint 全绿

## [Unreleased] - 2026-08-06（第五轮：原文对照 + 全文定位跳转）

### 🚀 功能
- **拆解每段「原文对照」**（W1-01 §2.4 落地）：五段（摘要/背景/目标/方法/实验/结论）每段下方展示匹配的原文引用（`lib/section-quotes.ts` 按章节关键词归组，中文/英文章节名均可），点击引用跳转 PDF；底部保留「全部原文引用」
- **PDF 全文定位跳转**（治本"无法真正跳转"）：LLM 猜的 `page_ref` 不可靠（尤其旧分析结果），现在点击引用时：① 先按 LLM 页码快速高亮 → ② 失败则在整篇 PDF 中逐页 `getTextContent` 搜索引用文本的真实页（`pdf-viewer.tsx` `findTextPage`，页文本缓存 + pdfjs 文档实例复用）→ ③ 跳到真实页再高亮 → ④ 全文找不到才提示。即使页码猜错也能定位到原文
- `lib/highlight-candidates.ts` 新增 `stripPageAnnotations`（剥离标注后的完整文本，供全文定位使用）

### 🧪 测试
- 前端 43 → **53 passed**（新增 `section-quotes` 7 例 + `stripPageAnnotations` 3 例）

### 🔧 说明
- 本次基于用户已修改的 `lib/pdf.ts`（`initPdfJs` 懒加载，修复 SSR DOMMatrix 崩溃）继续开发，未改动该方案

## [Unreleased] - 2026-08-06（第四轮：创新 Tab 跳转高亮修复 + dev 缓存防污染）

### 🐛 修复
- **创新 Tab 点击核心创新点无法跳转高亮**（根因 4 层）：
  - 提示词要求 evidence 内嵌页码标注（`[P3]`），匹配文本含原文不存在的字符 → 必然失败
  - evidence 可能被 LLM 翻译/改写，与 PDF 原文不一致
  - 创新/漏洞 prompt 缺失 `=== Page N ===` 页标记协议 → page_ref 纯靠猜
  - 前端只用前 30 字符单窗口精确匹配，无任何容错
  - 修复：
    - `INNOVATION_SYSTEM_PROMPT` / `FLAWS_SYSTEM_PROMPT`：evidence 改为「原文逐字引用（禁止翻译/改写/页码标注）」，页码只填 `page_ref`/`page` 字段，补页标记协议说明
    - 前端新增 `lib/highlight-candidates.ts`（`buildSearchCandidates` 纯函数）：剥离 `[P3]`/（第 X 页）/见 Px 标注 → 多窗口候选（30/20/12 前缀 + 尾部 30 兜底 + 剥离前原文兜底）→ 去重过滤
    - `pdf-viewer.tsx`：`applyHighlight` 依次尝试候选、大小写不敏感匹配，任一命中即高亮
    - `innovation-view.tsx`：新增「📖 原文引用」区块（复用 QuoteBlock），逐字引用命中率更高
- **dev 缓存被生产构建污染导致静态资源 404 / 布局全丢**（上一轮）：
  - 新增 `scripts/ensure-dev-clean.mjs`：`predev` 检测 `.next/BUILD_ID`（生产构建标记）自动删除 `.next`，dev/prod 交叉构建不再产生 404

### 🧪 测试
- 后端 140 → **142 passed**（新增创新/漏洞 prompt 逐字引用 + 页标记协议断言 2 例）
- 前端 35 → **43 passed**（新增 `buildSearchCandidates` 8 例：标注剥离 / 多窗口 / 尾部兜底 / 去重 / 空输入）

## [Unreleased] - 2026-08-06（第三轮：三个遗留问题修复）

### 🐛 修复
- **`has_compare` 恒为 false（前端数据陈旧）**：后端逻辑本就正确（对比结果保存 `analysis_compare.json`，列表实时检查），但前端对比完成后从不刷新论文列表。现在联网对比（`compare-view.tsx`）与多篇对比（`file-sidebar.tsx`）成功后都会 `fetchPapers()` 同步列表；新增 e2e 断言 `test_31b_has_compare_flag_after_compare`（对比前 false → 对比后 true）钉死正确性
- **SSE 偶发中断（前端订阅时序竞态）**：旧流 A 正常完成后 for-await 收尾期间用户重开流 B，旧流 P0 兜底会误判 `analyzing === type` 报"分析中断"并清掉新流状态。修复（`paper-store.ts` `analyzeStream`）：
  - `terminated` 标记：收到 reduce_completed/done/error 后 P0 兜底不再触发
  - 每流独立 AbortController：切论文时 `abort()` 旧流 fetch（此前连接悬挂到后端完成）
  - 入口防并发：`analyzing === type` 时直接忽略（React 批处理间隙双击防护）
  - 静默关闭（无终止事件）仍保留"分析中断"兜底
  - 新增 `tests/unit/sse-race.test.ts`（3 个用例：旧流不误杀新流 / 切论文中止旧流 / 静默关闭兜底）
- **PDF Worker 配置收敛 + 复制校验**：
  - 新增 `src/lib/pdf.ts` 单点设置 `workerSrc="/pdf.worker.min.mjs"`（react-pdf 自带相对路径默认值 `pdf.worker.mjs` 会 404，此前依赖 import 顺序侥幸覆盖）；`pdf-viewer.tsx` 改为统一导入
  - `copy-pdf-worker.mjs` 复制后校验产物 ≥100KB（防 pdfjs-dist 缺失/版本异常时静默产出坏文件），并打印体积（1.00 MB）
  - 确认：worker 完全本地化（无 CDN）、惰性加载（选中论文才下载）、生产运行时 Next 自动 gzip

### 🧪 测试
- 后端 139 → **140 passed**（新增 has_compare e2e 断言）；覆盖率保持 80%
- 前端 32 → **35 passed**（新增 SSE 竞态 3 例）；tsc / eslint / build 全绿

## [Unreleased] - 2026-08-06（第二轮复检修复）

### 🐛 复检发现的残余问题修复
- **DOCX legacy 页码标记补齐**：`docx_parser.extract_full_text` 按"伪页"插入 `=== Page N ===` 标记（此前与 `BREAKDOWN_SYSTEM_PROMPT` 声明不一致，DOCX 走 legacy 兜底时 LLM 页码无锚点）
- **PPT 页数上限 15**：`MAX_SLIDES=15` 上限 + 超页裁剪末尾内容页（此前最坏 16 页突破 README 宣称）；`core_innovations` 切片 5 条双保险；新增 `test_full_data_max_cap`
- **compare-papers 回填增强**：`_backfill_related_paper_ids` 标题精确匹配优先（LLM 重排/少输出不错位）+ 位置兜底；新增 `tests/test_compare_papers.py`（6 个用例）
- **Quote.page 默认 0**：LLM 漏输出页码不再校验失败
- **分割条快捷键冲突**：`shouldIgnoreShortcut` 忽略 `role="separator"`（此前分割条聚焦时 ←/→ 同时翻页+调宽）
- **上传"解析完成"文案可见**：渲染条件改为 `uploading || phase === "done"`（此前 React 批处理导致 done 态进度条已卸载）
- **多篇对比不被旧缓存覆盖**：`paperpilot:show-compare` 事件同步写入 store `results[id].compare`（此前 externalResult 消费后回退成旧联网搜缓存）

### 🧪 测试
- 后端 132 → **139 passed**（新增 compare_papers 回填 6 例、PPT 上限 1 例、DOCX 页标记断言）；覆盖率保持 80%
- 前端 31 → **32 passed**（新增 separator 忽略用例）

## [Unreleased] - 2026-08-06（第一轮：功能完整性修复）

### 🎯 功能完整性修复（审计驱动，20+ 项）

#### 核心正确性
- **联动高亮页码链路修复**：章节文本现在带 `=== Page N ===` 页码标记（`chapter_splitter.py`），Map prompt 明确要求 `page_ref` 取自标记，Reduce 输入透传 `page_ref`（此前被丢弃 → LLM 凭空猜页码，前端跳转不可信）
- **compare 结构化校验**：新增 `CompareResult`/`CompareMainPaper`/`CompareRelatedPaper` 模型（`schemas.py`），`/api/compare` 与 `/api/compare-papers` 传 `response_model`（此前无校验，`compare_table` 畸形会破坏前端表格）；多篇对比按输入顺序回填 `paper_id`（此前前端「多篇对比」标签永不显示）
- **Reduce 阶段整体超时**：与 Map 对称加 `asyncio.timeout`（此前 SSE 最长可悬挂 ~8 分钟）
- **PPT 页数保 8 下限**：内容驱动页数 <8 时自动补页（核心要点/创新等级/应用场景/原文引用/漏洞分层/优劣势/论文信息/静态说明页），对齐 README「8-15 页」宣称；新增 `tests/test_ppt_generator.py`
- **全局快捷键**：`←`/`→` 翻页、`1-5` 切 Tab（`use-keyboard-shortcuts.ts`，USER_GUIDE 承诺落地；input/contentEditable 内自动忽略）

#### 体验修复
- **`code=4001` 空态可达**：`api.request()` 支持 `allowCodes`，对比无结果不再弹错误 toast，渲染「未搜到相关工作」空态
- **多选对比 ≤5 上限**：前端 `toggleSelect` 拦截（此前选 6 篇直接弹后端 422 原始报错）
- **对比结果持久化**：`results[paper_id].compare` 纳入 store，切论文再切回可从服务端缓存恢复
- **可拖拽分割条**：PDF|AI 面板 30:70 ~ 70:30、双击复位 50%（`resizable-pane.tsx` + `MobilePanel desktopWidth`）
- **上传体验**：阶段文案（上传中 → 解析中 → 完成）、上传后自动定位摘要页、空状态居中上传按钮
- **高亮 3 秒渐隐**：联动高亮 3s 后 CSS 过渡渐隐（W1-01 §4.1）
- **顶栏增强**：一键 PPT、导出分析报告（Markdown，`lib/export.ts`）、暗色模式切换（next-themes）
- **段落一键复制**：引用块/证据行复制按钮（`CopyButton`/`QuoteBlock`）

#### 契约统一（以代码为准）
- `GET /api/papers/{id}` 前端类型改为 `PaperDetail`（对齐后端实际返回 meta/page_count/full_text_length）

### 🧪 测试（后端 114 → 132，前端 7 → 31）
- **SSE 流式端点零测试补齐**：`tests/test_e2e_analyze_stream.py`（5 个用例：完整事件序列 / legacy 兜底 / 部分章节失败容忍 / 非 breakdown / 论文不存在）
- **搜索客户端测试**：`tests/test_search_client.py`（13 个用例：`_is_retryable`、429/503 重试、重试耗尽、404 不重试、Bearer Header 防泄露、arxiv Atom 解析、关键词提取、放宽搜索去重、供应商选择）
- **页码协议测试**：`tests/test_prompts_breakdown.py` + `test_chapter_splitter.py` 新增页标记断言
- **前端 vitest**：快捷键纯函数（`shortcuts.test.ts` 15 例）、Markdown 导出（`export.test.ts` 5 例）、api 层 4001/SSE 帧解析（`api.test.ts` 6 例）
- **覆盖率实测 80%**，超过 CI 门禁 70%（此前审计引用的 67% 为过期 `.coverage` 快照）

### 📦 配置 / 工程
- `.env.example` 补 `LLM_TIMEOUT_SECONDS`、`LLM_REASONING_EFFORT`
- `.gitignore` 补根目录 `backend.log`/`frontend.log`、`frontend/tests/screenshots/`
- 新依赖：`next-themes`（暗色模式）

### 📝 文档同步
- `docs/W1-03-接口文档.md`：错误码表标注实际实现（code=HTTP 状态码，4001 以 HTTP 200+空数据返回）、异步 PPT 方案标注废弃、`/api/papers` 无分页参数、`/api/papers/{id}` 实际返回结构、health 字段值
- `docs/W1-02-技术架构.md`：WebSocket→SSE、章节阈值 ≥3、默认搜索 arXiv
- `README.md`：测试计数/覆盖率、`requirements-mac.txt` 说明
- `frontend/README.md`/`backend/README.md`：`BACKEND_URL`/`BACKEND_API_KEY` 替代 `NEXT_PUBLIC_API_*`、react-markdown 未安装、FastAPI 版本口径

## [Unreleased] - 2026-07-31

### 🐛 Bug 修复
- **P0**: `backend/app/services/llm_client.py:144` 裸 `except:` → `except json.JSONDecodeError:`，避免吞噬 `SystemExit` / `KeyboardInterrupt`
- **P0**: 新增 `backend/pytest.ini`，限定 `python_files = test_*.py`，避免 `manual_test_*.py`（独立启 uvicorn 的脚本）污染 pytest 套件
- **P1**: 前端 PDF 下载 fetch 加 `AbortController` + 60s 超时（之前裸 fetch 网络挂起时 UI 卡死）
- **P1**: 健康检查 `/api/health` 不再泄露 `data_dir` 完整路径，改为 `data_dir_ok: bool`（公开端点）
- **P1**: CI workflow (`.github/workflows/ci.yml`) 移除 `continue-on-error: true` 与 `|| echo` 兜底，lint/build 失败真正阻断合并
- **P2**: 清理 frontend 39 处 `any` 类型，全部收紧为 `unknown` / `Error` / `PaperInfo` / `AnalysisResult` / `CompareResponse` / `RelatedPaper` / `FlawItem` 等；`tsc --noEmit` 干净通过
- **P2**: `README.md` / `USER_GUIDE.md` / `start_dev.ps1` Windows 硬编码路径改为跨平台相对路径

### 📦 配置示例完善
- **P0**: `backend/.env.example` 补充 `APP_ENV`（dev/staging/prod，prod 强制鉴权）
- **P0**: `backend/.env.example` 补充 `TRUSTED_HOSTS`（反代白名单，XFF 信任依据）
- **P0**: `backend/.env.example` 补充 `TAVILY_TIMEOUT_SECONDS`（联网搜索超时）
- **P1**: `backend/.env.example` 补充 `APP_WORKERS`（多 worker 限流警告依据）
- **P2**: `backend/.env.example` 补充 `MAX_UPLOAD_SIZE_BYTES`（上传大小上限）

### 🧹 项目工程化
- **P2**: 新增根级 `.gitignore`（75 行）— 覆盖 macOS/Windows 系统残留、Python 缓存与虚拟环境、`.env`/`.env.*`（保留 `.env.example`）、`.idea`/`.vscode` IDE 配置、后端 `data/papers/*` 运行数据（保留 `test_samples/transformer_sample.{pdf,docx}` 测试样本）、`data/uploads/`、`data/ppts/`、`logs/*.log`、前端 `node_modules/` / `.next/` / `.tsbuildinfo` / `next-env.d.ts` / `shots/`。`backend/.gitignore` 的 data 段相应收敛到根规则。
- **P2**: 新增 `LICENSE`（MIT License，Copyright 2026 PaperPilot Authors，21 行）— 修复 README badge 与实际协议文件不一致。
- **P2**: 新增 `frontend/.eslintrc.json` — `extends: next/core-web-vitals`，关闭 `react/no-unescaped-entities`（兼容中文引号），`@next/next/no-img-element` 降为 warn。配合 `package.json` 显式声明的 `eslint: ^8.57.0`，CI 不再需要 `--no-save` 兜底。
- **P2**: 清理测试残留 — 删除 5 个 `p_2026_07_19_*` 历史论文目录（6.5MB）、`backend/logs/fetched_docx.docx`（2.2MB）和 `fetched_pdf.pdf`（7KB）、`backend/.DS_Store`、`frontend/dev-err.log` + `dev.log`；保留 `test_samples/`、`app.log`、历史 `backend_*.log`/`frontend_*.log`、`browser_screenshots/`。

## [Unreleased] - 2026-07-29

### 🔒 安全 (Security)
- **路径穿越防护** (`ppt_generator.py` P0-4) — paper_id 改用正则白名单 + `resolve()` 二次防线 + 原子写
- **Magic Number 校验** (`validators.py` + `upload.py` P1-2) — 拒绝扩展名伪装（HTML 不能伪装 PDF/DOCX）
- **XFF 反代白名单** (`auth.py` + `ratelimit.py` P1-14) — `trusted_hosts` 配置；非白名单 peer 的 X-Forwarded-For 一律忽略
- **prod 启动强校验** (`main.py` P1-15) — `APP_ENV=prod` 但未配 `APP_API_KEY` 直接 raise RuntimeError
- **全局异常处理** (`error_handler.py` P1-3) — 统一 ApiResponse 格式 + Pydantic/JSON/未捕获 三类处理 + 错误脱敏
- **paper_id / analysis_type 校验** (`validators.py` + 所有 endpoint P1-4/5) — Pydantic `pattern` + `Literal` 双重保险
- **CORS 不允许 `*`** (`config.py` P1-19) — 与 `allow_credentials=True` 冲突，启动期拒绝

### 🚀 性能 / 稳定性
- **请求超时** (`api.ts` P0-11) — 所有 fetch 加 AbortController：普通 30s / SSE 10min / 上传 5min
- **XHR 上传进度** (`api.ts` + `upload-button.tsx` P2-12) — 真实 0-95% 进度条，不再跳变
- **竞态覆盖修复** (`paper-store.ts` P0-5/6) — `results` 按 paper_id 分组 + isStale 检查，A 论文分析结果不会污染 B 论文
- **多 worker 限流警告** (`ratelimit.py` P0-2) — 文档 + 启动期检测 + 内存桶定期清理（P1-16）
- **孤儿 PPT 清理** (`storage.py` + `main.py` P1-18) — 启动清理 + 每 6h 后台清理 + 磁盘监控
- **Tavily 重试 + 连接池** (`search_client.py` P1-6/7) — 指数退避（429/5xx/Timeout 自动重试 3 次）+ 共享 httpx.AsyncClient + Bearer Header
- **定时器清理** (`main.py`) — Tavily 连接池 + 清理后台任务在 lifespan 关闭时正确取消

### 🎨 用户体验
- **PPT 生成进度反馈** (`ai-analysis-panel.tsx` P2-15) — elapsed timer + 不定进度条，避免用户以为卡死
- **移动端响应式** (`mobile-toggle.tsx` + `page.tsx` P2-10) — 抽屉式侧栏 + 顶部切换按钮 + `h-[100dvh]`
- **全局 ErrorBoundary** (`error-boundary.tsx` P1-22) — 三大区域（侧栏 / PDF / 分析面板）单独隔离崩溃
- **a11y 完整化** (P2-11) — aria-label / role / aria-current / 键盘导航 / aria-busy / aria-live
- **派生状态 useMemo** (`ai-analysis-panel.tsx` P2-13) — SSE 高频更新不再每帧重算
- **stable key** (P2-14) — `key={i}` 替换为稳定字段（page/title/section/slice(0,N)）
- **Flaws 跳转 PDF** (`ai-analysis-panel.tsx` P3-1) — 与拆解/创新 Tab 一致支持页码跳转
- **PPT 字段校验** (`ai-analysis-panel.tsx` P0-8) — 删 `@ts-expect-error` + 运行时 `if` 收窄类型
- **API_BASE 统一** (P3-2) — 仅 `api.ts` 一处定义，其他文件统一 `import`
- **Button 默认 type="button"** (`button.tsx` P3-5) — 防止 form 意外提交

### 🛠️ 工程化
- **共享验证模块** (`utils/validators.py` P1-4/5/2) — paper_id / analysis_type / filename / magic number 集中
- **共享日志脱敏** (`llm_client.py` P1-10) — 移除完整响应日志，改记录长度 + 摘要首 80 字符
- **PPT 长度/控制字符防护** (`ppt_generator.py` P1-11/12) — bullet ≤200 字 / 标题 ≤120 字 / 控制字符过滤
- **paper_language Literal** (`schemas.py` + 各 endpoint P2-23) — 限定中文/English/日本語，防止污染 LLM prompt
- **未知文件后缀拒 500** (`upload.py` P2-26) — 不再静默 fallback，立即报警
- **环境变量兼容** (`config.py`) — `cors_origins` / `trusted_hosts` 支持逗号分隔字符串和 JSON 数组两种格式
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — backend pytest + ruff / frontend tsc + build

### 🐛 Bug 修复
- **本地 .env 启动失败** — Sprint 2 把 `cors_origins` 改 `List[str]` 破坏了字符串格式 `.env`，已修复为 str 字段 + property 解析
- **Tavily aclose 重复块** (粘贴遗留) — 删除重复段
- **PDF Worker 依赖 CDN** — 改 `new URL(..., import.meta.url)` 本地化，离线/CSP 严格环境也能渲染
- **PPT 路径未清洗** — 拼接前清洗 paper_id + 文件名，防路径穿越
- **Tavily API Key 通过 body 泄露** — 改 Bearer Header
- **重复 Tavily aclose 块** — 已删除

### 📊 验证
- `tsc --noEmit` — 全通过
- `compileall -q app/ tests/` — 全通过
- pytest 23/23 通过（auth 11 + pdf 5 + docx 7）
- 自定义 runner 47+51 项断言通过（PDF + DOCX 文件读取端到端）

---

## [W1-W8] 历史版本

参见 [git log](https://github.com/) 与各周文档：
- `docs/W1-01-原型与交互设计.md`
- `docs/W1-02-技术架构.md`
- `docs/W1-03-接口文档.md`
- `docs/business-plan.md`
- `docs/presentation-outline.md`