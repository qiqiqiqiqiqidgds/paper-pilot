#!/usr/bin/env python3
"""PaperPilot API smoke test - exercises all key endpoints via HTTP.

P3-1 修复：
- BASE 从环境变量 PAPERPILOT_BASE_URL 读取（默认 http://127.0.0.1:8000），
  不再硬编码机器相关路径；
- 所有请求携带 X-API-Key（从环境变量 API_KEY 读取，未设置时打印提示）；
- 删除 generate-ppt 请求里不存在的 target_pages 字段（此前被后端静默忽略）；
- 清理 5 处空 f-string（ruff F541）。
"""
import os
import sys
import time
import requests

BASE = os.environ.get("PAPERPILOT_BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("API_KEY", "")
# 后端启用了鉴权（APP_API_KEY 非空）时，不带 X-API-Key 的请求一律 401
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
if not API_KEY:
    print("提示: 未设置 API_KEY 环境变量；若后端启用了鉴权，以下请求会返回 401")


def show(label, r, truncate=300):
    body = r.text
    if len(body) > truncate:
        body = body[:truncate] + f"...(truncated, total {len(r.text)} bytes)"
    print(f"[{r.status_code}] {label}: {body}")
    return r


def section(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


# 1. Health
section("1. GET /api/health")
show("health", requests.get(f"{BASE}/api/health", timeout=5, headers=HEADERS))

# 2. List papers
section("2. GET /api/papers")
r = requests.get(f"{BASE}/api/papers", timeout=5, headers=HEADERS)
show("papers list", r, truncate=200)
papers = r.json().get("data", {}).get("items", [])
if not papers:
    print("NO PAPERS - abort")
    sys.exit(1)
paper_id = papers[0].get("paper_id") or papers[0].get("id")
print(f"=> using paper_id: {paper_id}")

# 3. Detail
section(f"3. GET /api/papers/{paper_id}")
show("paper detail", requests.get(f"{BASE}/api/papers/{paper_id}", timeout=5, headers=HEADERS))

# 4. Cached breakdown
section(f"4. GET /api/analyze/{paper_id}/breakdown")
r = requests.get(f"{BASE}/api/analyze/{paper_id}/breakdown", timeout=5, headers=HEADERS)
if r.status_code == 200 and r.json().get("data"):
    d = r.json()["data"]
    result = d.get("result", {})
    print(f"[200] breakdown cached: keys={list(result.keys())}")
    for k in ["summary", "background", "goal", "method", "experiment", "conclusion"]:
        v = result.get(k, "")
        if v:
            preview = v[:120] + "..." if len(v) > 120 else v
            print(f"  - {k}: {preview}")
else:
    show("breakdown", r)

# 5. Get full text (to confirm PDF parsed)
section(f"5. GET /api/papers/{paper_id} (check text.json)")
detail = requests.get(f"{BASE}/api/papers/{paper_id}", timeout=5, headers=HEADERS).json()["data"]
print(f"  - title: {detail.get('title')}")
print(f"  - filename: {detail.get('filename')}")
print(f"  - file_type: {detail.get('file_type')}")
print(f"  - size: {detail.get('size')} bytes")
print(f"  - page_count: {detail.get('page_count')}")
print(f"  - keywords: {detail.get('keywords')}")
print(f"  - summary (cached): {(detail.get('summary') or '')[:100]}")

# 6. Run analysis - breakdown (likely cached)
section("6. POST /api/analyze (breakdown) - first hit may use cache")
t0 = time.time()
try:
    r = requests.post(
        f"{BASE}/api/analyze",
        json={"paper_id": paper_id, "type": "breakdown", "paper_language": "中文"},
        timeout=300,
        headers=HEADERS,
    )
    print(f"elapsed: {time.time() - t0:.1f}s")
    show("analyze breakdown", r, truncate=300)
except Exception as e:
    print(f"FAILED: {e}")

# 7. Innovation analysis
section("7. POST /api/analyze (innovation)")
t0 = time.time()
try:
    r = requests.post(
        f"{BASE}/api/analyze",
        json={"paper_id": paper_id, "type": "innovation", "paper_language": "中文"},
        timeout=300,
        headers=HEADERS,
    )
    print(f"elapsed: {time.time() - t0:.1f}s")
    show("analyze innovation", r, truncate=300)
except Exception as e:
    print(f"FAILED: {e}")

# 8. Search related
section("8. POST /api/search-related")
t0 = time.time()
try:
    r = requests.post(
        f"{BASE}/api/search-related",
        json={"paper_id": paper_id, "max_results": 3},
        timeout=120,
        headers=HEADERS,
    )
    print(f"elapsed: {time.time() - t0:.1f}s")
    show("search-related", r, truncate=400)
except Exception as e:
    print(f"FAILED: {e}")

# 9. Compare
section("9. POST /api/compare")
t0 = time.time()
try:
    r = requests.post(
        f"{BASE}/api/compare",
        json={"paper_id": paper_id, "max_results": 3},
        timeout=300,
        headers=HEADERS,
    )
    print(f"elapsed: {time.time() - t0:.1f}s")
    show("compare", r, truncate=400)
except Exception as e:
    print(f"FAILED: {e}")

# 10. PPT
section("10. POST /api/generate-ppt")
t0 = time.time()
try:
    r = requests.post(
        f"{BASE}/api/generate-ppt",
        json={"paper_id": paper_id},
        timeout=300,
        headers=HEADERS,
    )
    print(f"elapsed: {time.time() - t0:.1f}s")
    show("generate-ppt", r, truncate=400)
    if r.status_code == 200:
        data = r.json().get("data", {})
        if data.get("download_url"):
            print(f"=> download URL: {data['download_url']}")
            dl = requests.get(f"{BASE}{data['download_url']}", timeout=30, headers=HEADERS)
            print(f"=> download: [{dl.status_code}] size={len(dl.content)} bytes, type={dl.headers.get('Content-Type')}")
except Exception as e:
    print(f"FAILED: {e}")

print()
print("=" * 60)
print("DONE")
print("=" * 60)
