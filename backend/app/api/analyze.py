"""
分析接口（含分章 Map-Reduce + SSE 流式版）
"""
import asyncio
import json
import time
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.schemas import (
    ApiResponse,
    AnalyzeRequest,
    BreakdownResult,
    InnovationResult,
    FlawsResult,
)
from app.services.llm_client import get_llm_client, LLMConfigError
from app.utils.storage import (
    load_text_json_async,
    file_exists,
    save_analysis_result_async,
)
from app.utils.logger import logger
from app.utils.validators import validate_paper_id, validate_analysis_type
from app.agent.chapter_splitter import split_chapters
from app.agent.prompts.breakdown import (
    build_breakdown_messages,        # legacy
    build_chapter_map_messages,      # map
    build_reduce_messages,           # reduce
    build_innovation_messages,
    build_flaws_messages,
    REDUCE_RETRY_BUDGET_CHARS,       # P1-2: 上下文超限重试时的激进截断预算
)

router = APIRouter(prefix="/api", tags=["analyze"])


# ============== 入口 ==============

@router.post("/analyze", response_model=ApiResponse)
async def analyze_paper(request: AnalyzeRequest):
    """
    对论文执行指定类型分析

    type: breakdown（拆解）/ innovation（创新）/ flaws（漏洞）
    """
    start_time = time.time()

    # P1-4/5: paper_id / type 校验
    validate_paper_id(request.paper_id)
    validate_analysis_type(request.type)

    # 1. 校验论文存在
    if not file_exists(request.paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")

    # 读 + 解析 text.json 是重 IO（数 MB），放线程池避免阻塞事件循环（B5）
    data = await load_text_json_async(request.paper_id)
    if not data:
        raise HTTPException(status_code=404, detail="论文数据未找到")

    paper_text = data.get("full_text", "")
    paper_meta = data.get("meta") or {}

    if not paper_text.strip():
        raise HTTPException(status_code=400, detail="论文文本为空")

    # 2. 根据类型分发
    breakdown_stats = None  # P1-3: breakdown 的章节成功/失败统计（其他类型无）
    if request.type == "breakdown":
        result, breakdown_stats = await _analyze_breakdown(data, request.paper_language)
    elif request.type == "innovation":
        result = await _analyze_with_legacy(
            paper_text, paper_meta, request.paper_language,
            build_innovation_messages, response_model=InnovationResult,
        )
    elif request.type == "flaws":
        result = await _analyze_with_legacy(
            paper_text, paper_meta, request.paper_language,
            build_flaws_messages, response_model=FlawsResult,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的分析类型: {request.type}，支持: breakdown / innovation / flaws"
        )

    elapsed_ms = int((time.time() - start_time) * 1000)

    # 3. 保存结果（B2: 返回 False 表示论文已被删除，跳过落盘即可，不影响已算出的结果）。
    # 落盘失败（论文删除竞态/磁盘满）不应让已花 token 的分析结果以 500 收场——
    # 与 SSE/compare 路径保持一致的 try/except 约定
    try:
        saved = await save_analysis_result_async(request.paper_id, request.type, result)
        if saved is False:
            logger.warning(f"论文已被删除，跳过保存分析结果: {request.paper_id}/{request.type}")
    except Exception as e:
        logger.warning(f"保存分析结果失败（分析结果已返回，未持久化）: {e}")

    logger.info(f"分析完成: {request.paper_id} - {request.type} ({elapsed_ms}ms)")

    response_data = {
        "type": request.type,
        "result": result,
        "elapsed_ms": elapsed_ms,
    }
    # P1-3: 透出章节统计（chapters_total / chapters_succeeded / failed_chapters，
    # 字段命名与 SSE 版 map_failed 等事件对齐），部分章节失败不再零提示
    if breakdown_stats is not None:
        response_data.update(breakdown_stats)

    return ApiResponse(code=0, data=response_data)


# ============== 拆解：分章 Map-Reduce ==============

def _is_context_overflow_error(e: BaseException) -> bool:
    """P1-2: 判断异常是否疑似"输入超 LLM 上下文窗口"（关键词匹配，宁缺勿滥）

    各 provider 文案不一（OpenAI 系 "maximum context length"、部分网关
    "context_length_exceeded" / "too long" 等），只做启发式判断：
    误判的代价是多一次注定失败的 LLM 调用（仍走 502），无正确性风险。
    """
    text = str(e).lower()
    keywords = (
        "context length",
        "context_length",
        "maximum context",
        "token limit",
        "too many tokens",
        "too long",
        "input length",
        "request too large",
        "上下文",
    )
    return any(kw in text for kw in keywords)


async def _analyze_breakdown(data: dict, paper_language: str) -> tuple:
    """分章 Map-Reduce 五段拆解

    返回 (result, stats)：
      result: BreakdownResult dict
      stats:  P1-3 章节统计 {chapters_total, chapters_succeeded, failed_chapters}
    """
    pages = data.get("pages", [])
    full_text = data.get("full_text", "")
    paper_meta = data.get("meta", {})
    toc = data.get("toc", [])

    # 1. 章节识别
    chapters = split_chapters(pages=pages, toc=toc, full_text=full_text)
    logger.info(f"识别到 {len(chapters)} 章: {[c.name for c in chapters]}")

    # 兜底：少于 2 章走整篇模式
    if len(chapters) < 2:
        logger.warning("章节数 <2，走整篇分析模式")
        result = await _analyze_with_legacy(
            full_text, paper_meta, paper_language,
            build_breakdown_messages, response_model=BreakdownResult,
        )
        # P1-3: 整篇模式没有逐章概念，按"单章成功"计（split 兜底恒返回 1 章）
        return result, {
            "chapters_total": 1,
            "chapters_succeeded": 1,
            "failed_chapters": [],
        }

    # 2. Map：并发分析每章（带 Semaphore 限流 + 整体超时，避免 API 限流/卡死）
    llm = get_llm_client()
    # P3-5: 并发上限从配置读取（此前硬编码 3），可用 LLM_MAP_CONCURRENCY 调节
    semaphore = asyncio.Semaphore(max(1, settings.llm_map_concurrency))
    map_timeout = settings.llm_timeout_seconds

    async def map_one(ch):
        async with semaphore:
            try:
                return await llm.chat_json(
                    messages=build_chapter_map_messages(ch, paper_meta, paper_language)
                )
            except Exception as e:
                logger.warning(f"章节 [{ch.name}] Map 失败: {e}")
                raise

    map_tasks = [asyncio.create_task(map_one(ch)) for ch in chapters]
    try:
        async with asyncio.timeout(map_timeout):
            map_results_raw = await asyncio.gather(*map_tasks, return_exceptions=True)
    except TimeoutError:
        # 整体超时：取消未完成任务，未完成章节按"该章失败"处理，不整体崩溃
        logger.error("Map 阶段整体超时（%.0fs），未完成章节按失败处理", map_timeout)
        for t in map_tasks:
            t.cancel()
        map_results_raw = await asyncio.gather(*map_tasks, return_exceptions=True)

    # 3. 收集成功结果（P1-3: 显式统计成功/失败，响应透出章节统计，不再静默丢弃）
    successful_maps = []
    failed_chapters = []
    for ch, raw in zip(chapters, map_results_raw):
        # P1-3: 超时取消的任务结果是 CancelledError（BaseException 子类，不是
        # Exception），isinstance(raw, Exception) 判不到，必须单独处理，
        # 否则会走"非 dict"分支被静默跳过
        if isinstance(raw, asyncio.CancelledError):
            logger.warning(f"章节 [{ch.name}] Map 被取消（整体超时）")
            failed_chapters.append(ch.name)
            continue
        if isinstance(raw, Exception):
            logger.warning(f"章节 [{ch.name}] Map 失败: {raw}")
            failed_chapters.append(ch.name)
            continue
        if not isinstance(raw, dict):
            logger.warning(f"章节 [{ch.name}] 返回非 dict: {type(raw)}")
            failed_chapters.append(ch.name)
            continue
        # 补 chapter_name（防 LLM 漏了）
        raw.setdefault("chapter_name", ch.name)
        successful_maps.append(raw)

    chapters_stats = {
        "chapters_total": len(chapters),
        "chapters_succeeded": len(successful_maps),
        "failed_chapters": failed_chapters,
    }

    if not successful_maps:
        # 透出根因（如缺 LLM_API_KEY），避免只看得到「Map 全失败」
        root_cause = next((r for r in map_results_raw if isinstance(r, LLMConfigError)), None)
        if root_cause is not None:
            raise HTTPException(status_code=502, detail=str(root_cause))
        raise HTTPException(
            status_code=502,
            detail="所有章节 Map 都失败了，无法 Reduce"
        )

    logger.info(f"Map 成功 {len(successful_maps)}/{len(chapters)} 章，开始 Reduce")

    # 4. Reduce：汇总成五段拆解（结构化校验，带整体超时避免 SSE 悬挂）
    try:
        async with asyncio.timeout(map_timeout):
            final = await llm.chat_json(
                messages=build_reduce_messages(successful_maps, paper_meta, paper_language),
                response_model=BreakdownResult,
            )
    except TimeoutError:
        logger.error("Reduce 阶段整体超时（%.0fs）", map_timeout)
        raise HTTPException(status_code=502, detail="Reduce 超时，请重试")
    except Exception as e:
        # P1-2: 疑似上下文超限（章节多时 Reduce 输入仍可能超窗口，provider 400
        # 不可重试）→ 用更激进的截断预算重试一次（一次为限，控制复杂度）
        if not _is_context_overflow_error(e):
            logger.error(f"Reduce 失败: {e}")
            raise HTTPException(status_code=502, detail="Reduce 失败")
        logger.warning(f"Reduce 疑似上下文超限，改用激进截断预算重试一次: {e}")
        try:
            async with asyncio.timeout(map_timeout):
                final = await llm.chat_json(
                    messages=build_reduce_messages(
                        successful_maps, paper_meta, paper_language,
                        total_budget_chars=REDUCE_RETRY_BUDGET_CHARS,
                    ),
                    response_model=BreakdownResult,
                )
        except TimeoutError:
            logger.error("Reduce 重试整体超时（%.0fs）", map_timeout)
            raise HTTPException(status_code=502, detail="Reduce 超时，请重试")
        except Exception as retry_exc:
            logger.error(f"Reduce 激进截断重试仍失败: {retry_exc}")
            raise HTTPException(status_code=502, detail="Reduce 失败")

    return final, chapters_stats


# ============== Legacy：整篇分析 ==============

async def _analyze_with_legacy(paper_text: str, paper_meta: dict, paper_language: str, build_fn, response_model=None) -> dict:
    """整篇一次性分析（用于 innovation / flaws / 兜底）

    带 llm_timeout_seconds 整体超时：与 Map/Reduce 阶段同等待遇，
    避免一次挂起的请求（含 SDK 重试最坏 4 次）长期占用连接与昂贵限流配额。

    注意：HTTPException 的 detail 只返回固定文案（异常详情只进日志），
    避免把 LLM 原始内容 / 内部异常回显给前端。
    """
    try:
        llm = get_llm_client()
        messages = build_fn(paper_text, paper_meta, paper_language)
        async with asyncio.timeout(settings.llm_timeout_seconds):
            return await llm.chat_json(messages=messages, response_model=response_model)
    except LLMConfigError as e:
        logger.error(f"LLM 未配置: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except TimeoutError:
        logger.error(f"LLM 整篇分析整体超时（{settings.llm_timeout_seconds:.0f}s）")
        raise HTTPException(status_code=502, detail="LLM 响应超时，请重试或缩短论文长度")
    except ValueError as e:
        logger.error(f"LLM 返回解析失败: {e}")
        raise HTTPException(status_code=502, detail="LLM 返回格式错误")
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        raise HTTPException(status_code=502, detail="LLM 调用失败")


# ============== 缓存读 ==============

@router.get("/analyze/{paper_id}/{analysis_type}", response_model=ApiResponse)
async def get_analysis(paper_id: str, analysis_type: str):
    """获取已保存的分析结果"""
    from pathlib import Path
    import json

    # P1-4/5: 路径参数校验（防路径穿越 + 任意 LLM 调用类型）
    paper_id = validate_paper_id(paper_id)
    analysis_type = validate_analysis_type(analysis_type)

    if not file_exists(paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")

    analysis_file = Path(settings.papers_dir) / paper_id / f"analysis_{analysis_type}.json"
    if not analysis_file.exists():
        raise HTTPException(status_code=404, detail="该分析结果未生成")

    # 读 + 解析都在线程池执行（B5：多 MB JSON 的 loads 同样会阻塞事件循环）
    def _load():
        return json.loads(analysis_file.read_text(encoding="utf-8"))

    try:
        result = await asyncio.to_thread(_load)
    except json.JSONDecodeError as e:
        # 损坏的分析结果文件：语义是服务端数据问题（500），不是客户端请求错误（400）
        logger.error(f"分析结果文件损坏: {analysis_file.name}: {e}")
        raise HTTPException(status_code=500, detail="分析结果文件损坏，请重新运行该分析")
    return ApiResponse(
        code=0,
        data={
            "type": analysis_type,
            "result": result,
        }
    )


# ============== SSE 流式版（仅 breakdown） ==============

def _sse_bytes(event: str, payload: dict) -> bytes:
    """格式化单个 SSE 事件（UTF-8 bytes）"""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@router.post("/analyze/stream")
async def analyze_stream(request: AnalyzeRequest):
    """
    SSE 流式分析端点（向后兼容，新增端点）

    事件序列：
      started           任务开始
      chapters_detected 章节识别完成
      map_started       Map 阶段开始（每章一个）
      map_completed     Map 阶段完成（每章一个）
      map_failed        Map 阶段失败（每章一个，可选）
      progress          进度更新 {completed, total, stage}
      maps_completed    所有 Map 完成
      reduce_started    Reduce 开始
      reduce_completed  Reduce 完成（含最终五段拆解 result）
      done              全部完成 {elapsed_ms, result}
      error             任意步骤出错

    限制：当前仅 breakdown 支持流式；innovation / flaws 走旧端点。
    注意：SSE 期间 HTTP 状态码始终是 200（即使 paper 不存在），错误通过 error 事件传递。
    """
    # B4: 登记事件流里 create_task 出来的所有后台 LLM 任务（Map / legacy 兜底 / Reduce），
    # 生成器以任何方式退出（客户端断连 / 超时 / 异常）时在 finally 里统一取消
    background_tasks: list = []

    async def event_generator() -> AsyncIterator[bytes]:
        try:
            async for chunk in _event_stream(request, background_tasks):
                yield chunk
        finally:
            for t in background_tasks:
                t.cancel()
            if background_tasks:
                try:
                    # 等待被取消的任务收尾；任务自身的 CancelledError 由 return_exceptions 吞掉
                    await asyncio.gather(*background_tasks, return_exceptions=True)
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 禁用 nginx 缓存，确保实时流式
            "Connection": "keep-alive",
        },
    )


async def _event_stream(request: AnalyzeRequest, background_tasks: list) -> AsyncIterator[bytes]:
    """SSE 事件流主体（B4: 从 event_generator 抽出，后台任务统一登记到 background_tasks）"""
    start_time = time.time()

    # ===== 1. 入参校验（失败走 error 事件，保持 SSE 格式）=====
    # P1-4/5: paper_id / type 校验
    try:
        validate_paper_id(request.paper_id)
        validate_analysis_type(request.type)
    except HTTPException as he:
        yield _sse_bytes("error", {"message": he.detail, "code": he.status_code})
        return

    if not file_exists(request.paper_id):
        yield _sse_bytes("error", {"message": "论文不存在", "code": 404})
        return

    # 读 + 解析 text.json 是重 IO，放线程池避免阻塞事件循环（B5）
    data = await load_text_json_async(request.paper_id)
    if not data:
        yield _sse_bytes("error", {"message": "论文数据未找到", "code": 404})
        return

    paper_text = data.get("full_text", "")
    paper_meta = data.get("meta") or {}

    if not paper_text.strip():
        yield _sse_bytes("error", {"message": "论文文本为空", "code": 400})
        return

    if request.type != "breakdown":
        yield _sse_bytes(
            "error",
            {
                "message": f"流式版暂只支持 breakdown，当前: {request.type}（请用 /api/analyze）",
                "code": 400,
            },
        )
        return

    # ===== 2. 任务开始 =====
    yield _sse_bytes("started", {
        "paper_id": request.paper_id,
        "type": request.type,
        "paper_language": request.paper_language,
    })

    # ===== 3. 章节识别 =====
    try:
        pages = data.get("pages", [])
        full_text = data.get("full_text", "")
        toc = data.get("toc", [])
        chapters = split_chapters(pages=pages, toc=toc, full_text=full_text)
    except Exception:
        logger.exception("章节识别失败")
        yield _sse_bytes("error", {"message": "章节识别失败", "code": 500})
        return

    yield _sse_bytes("chapters_detected", {
        "count": len(chapters),
        "chapters": [
            {"name": c.name, "page_start": c.page_start, "page_end": c.page_end}
            for c in chapters
        ],
    })

    # ===== 4. 兜底：章节数 < 2 走整篇分析 =====
    if len(chapters) < 2:
        yield _sse_bytes("fallback_legacy", {"reason": "章节数 < 2"})
        try:
            # B4: create_task 包装并登记，断连时由 event_generator 的 finally 取消
            legacy_task = asyncio.create_task(_analyze_with_legacy(
                full_text, paper_meta, request.paper_language,
                build_breakdown_messages, response_model=BreakdownResult,
            ))
            background_tasks.append(legacy_task)
            result = await legacy_task
        except HTTPException as he:
            yield _sse_bytes("error", {"message": he.detail, "code": he.status_code})
            return
        except Exception:
            logger.exception("legacy 整篇分析失败")
            yield _sse_bytes("error", {"message": "分析失败", "code": 500})
            return

        elapsed_ms = int((time.time() - start_time) * 1000)
        yield _sse_bytes("reduce_completed", {"result": result, "mode": "legacy"})
        yield _sse_bytes("done", {"elapsed_ms": elapsed_ms, "result": result})

        # 保存结果（非主流程；B2: 返回 False 表示论文已被删除，跳过落盘）
        try:
            saved = await save_analysis_result_async(request.paper_id, request.type, result)
            if saved is False:
                logger.warning(f"论文已被删除，跳过保存分析结果: {request.paper_id}/{request.type}")
        except Exception as e:
            logger.warning(f"保存分析结果失败: {e}")
        return

    # ===== 5. Map 阶段：并发执行 + 队列流式返回 =====
    llm = get_llm_client()
    # P3-5: 并发上限从配置读取（与非流式版同一配置），可用 LLM_MAP_CONCURRENCY 调节
    semaphore = asyncio.Semaphore(max(1, settings.llm_map_concurrency))
    map_timeout = settings.llm_timeout_seconds
    # Queue 用于 Map task -> SSE generator 的事件传递
    # None 作为哨兵表示"本 task 已结束"
    event_queue: asyncio.Queue = asyncio.Queue()

    async def map_one(ch):
        """单个章节 Map：put 事件到 queue 后返回结果或 raise"""
        async with semaphore:
            await event_queue.put(("map_started", {"chapter": ch.name}))
            try:
                result = await llm.chat_json(
                    messages=build_chapter_map_messages(ch, paper_meta, request.paper_language)
                )
                if not isinstance(result, dict):
                    raise ValueError(f"LLM 返回非 dict: {type(result).__name__}")
                # 补 chapter_name（防 LLM 漏了）
                result.setdefault("chapter_name", ch.name)
                await event_queue.put(("map_completed", {
                    "chapter": ch.name,
                    "section_type": result.get("section_type", "other"),
                    # 只发 summary 前 200 字到事件里，避免单事件过大
                    "summary_preview": (result.get("summary", "") or "")[:200],
                }))
                return result
            except Exception as e:
                logger.warning(f"章节 [{ch.name}] Map 失败: {e}")
                # 不把内部异常详情回显给前端（固定文案）
                await event_queue.put(("map_failed", {"chapter": ch.name, "error": "该章节分析失败"}))
                raise

    # 启动所有 Map 任务（B4: 登记，断连/超时时统一取消）
    map_tasks = [asyncio.create_task(map_one(ch)) for ch in chapters]
    background_tasks.extend(map_tasks)
    total = len(chapters)
    completed = 0

    # 从 queue 流式消费事件，每收到一个 map_completed / map_failed 就发 progress
    # 整体超时：若 Map 卡住，超时后停止等待、未完成章节按失败处理
    try:
        async with asyncio.timeout(map_timeout):
            while completed < total:
                try:
                    event_name, event_payload = await event_queue.get()
                except asyncio.CancelledError:
                    # 客户端断开（generator 被 cancel）—— 取消正在跑的 task
                    for t in map_tasks:
                        t.cancel()
                    raise

                yield _sse_bytes(event_name, event_payload)

                if event_name in ("map_completed", "map_failed"):
                    completed += 1
                    yield _sse_bytes("progress", {
                        "stage": "map",
                        "completed": completed,
                        "total": total,
                    })
    except TimeoutError:
        logger.error("Map 阶段整体超时（%.0fs），未完成章节按失败处理", map_timeout)
        for t in map_tasks:
            t.cancel()

    # 收集所有 task 结果（用 return_exceptions=True，失败的已是 Exception）
    map_results_raw = await asyncio.gather(*map_tasks, return_exceptions=True)

    # ===== 6. 收集成功结果 =====
    successful_maps: list = []
    for ch, raw in zip(chapters, map_results_raw):
        if isinstance(raw, Exception):
            continue
        if not isinstance(raw, dict):
            continue
        raw.setdefault("chapter_name", ch.name)
        successful_maps.append(raw)

    if not successful_maps:
        # 透出根因（如缺 LLM_API_KEY），避免只看得到「Map 全失败」
        root_cause = next((r for r in map_results_raw if isinstance(r, LLMConfigError)), None)
        yield _sse_bytes("error", {
            "message": str(root_cause) if root_cause is not None else "所有章节 Map 都失败，无法 Reduce",
            "code": 502,
        })
        return

    yield _sse_bytes("maps_completed", {
        "success": len(successful_maps),
        "total": total,
    })

    # ===== 7. Reduce =====
    yield _sse_bytes("reduce_started", {"chapter_count": len(successful_maps)})
    try:
        async with asyncio.timeout(map_timeout):
            # B4: create_task 包装并登记，断连时由 event_generator 的 finally 取消
            reduce_task = asyncio.create_task(llm.chat_json(
                messages=build_reduce_messages(successful_maps, paper_meta, request.paper_language),
                response_model=BreakdownResult,
            ))
            background_tasks.append(reduce_task)
            final = await reduce_task
    except TimeoutError:
        logger.error("Reduce 阶段整体超时（%.0fs）", map_timeout)
        yield _sse_bytes("error", {"message": "Reduce 超时，请重试", "code": 502})
        return
    except Exception:
        logger.exception("Reduce 失败")
        yield _sse_bytes("error", {"message": "Reduce 失败", "code": 502})
        return

    elapsed_ms = int((time.time() - start_time) * 1000)

    # ===== 8. 完成 =====
    yield _sse_bytes("reduce_completed", {"result": final})
    yield _sse_bytes("done", {
        "elapsed_ms": elapsed_ms,
        "result": final,
    })

    # 保存结果（非主流程，失败不影响 SSE 已发的事件；B2: 返回 False 表示论文已被删除，跳过落盘）
    try:
        saved = await save_analysis_result_async(request.paper_id, request.type, final)
        if saved is False:
            logger.warning(f"论文已被删除，跳过保存分析结果: {request.paper_id}/{request.type}")
        else:
            logger.info(f"流式分析完成: {request.paper_id} - {request.type} ({elapsed_ms}ms)")
    except Exception as e:
        logger.warning(f"保存分析结果失败: {e}")
