"""
Upload endpoint edge-case test (manual)

Tests POST /api/upload rejection behaviour against invalid / malicious inputs.

Run:
    cd backend
    python -m tests.manual.manual_test_upload_edge
    # or directly: python tests/manual/manual_test_upload_edge.py

NOTE: manual script (not prefixed with test_), pytest collects test_*.py only.
"""
import sys
import time
import traceback
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

# Each test: (name, expected_status, fn)
# expected_status: 0 means "should be 2xx success" (used by 50MB 整 and 50MB+1 字节
# where the design expectation differs)
def _post_no_file():
    return c.post("/api/upload")

def _post_file(name: str, content: bytes, ctype: str):
    return c.post(
        "/api/upload",
        files={"file": (name, content, ctype)},
    )

def _50mb_plus_1():
    # 50MB + 1 字节 —— 期望 413
    big = b"x" * (50 * 1024 * 1024 + 1)
    return _post_file("big.pdf", big, "application/pdf")

def _50mb_exact():
    # 50MB 整 —— 文件不是真 PDF，期望 400（解析失败）
    big = b"x" * (50 * 1024 * 1024)
    return _post_file("big.pdf", big, "application/pdf")

tests = [
    # 1. 完全没 file 字段
    ("无 file 字段",       422, _post_no_file),

    # 2. 非法后缀
    ("exe 文件",            400, lambda: _post_file("virus.exe", b"fake",  "application/octet-stream")),
    ("txt 文件",            400, lambda: _post_file("notes.txt", b"hello", "text/plain")),
    ("zip 文件",            400, lambda: _post_file("a.zip",    b"PK",    "application/zip")),
    ("无后缀",              400, lambda: _post_file("noext",    b"hello", "application/octet-stream")),

    # 3. 过小文件
    ("50 字节",             400, lambda: _post_file("tiny.pdf", b"x" * 50,  "application/pdf")),
    ("99 字节",             400, lambda: _post_file("tiny.pdf", b"x" * 99,  "application/pdf")),

    # 4. 过大文件
    ("50MB+1 字节",         413, _50mb_plus_1),
    ("50MB 整",             400, _50mb_exact),  # 解析失败

    # 5. 伪装 PDF
    ("伪装 PDF",            400, lambda: _post_file("fake.pdf", b"this is not a pdf", "application/pdf")),
]

# --- Run ---------------------------------------------------------------------

rows = []   # (name, expected, actual_status, body, elapsed_ms, error)

for name, expected, fn in tests:
    t0 = time.perf_counter()
    try:
        res = fn()
        dt = (time.perf_counter() - t0) * 1000
        body = res.text[:300]
        rows.append((name, expected, res.status_code, body, dt, None))
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        rows.append((name, expected, "EXC", f"{type(e).__name__}: {e}", dt, traceback.format_exc()))

# --- Print -------------------------------------------------------------------

print()
print("=" * 100)
print(f"{'scenario':<14}  {'exp':>4}  {'act':>5}  {'ms':>7}  {'pass':<5}  body")
print("-" * 100)
for name, expected, actual, body, dt, _err in rows:
    ok = (actual == expected)
    actual_str = str(actual)
    marker = "OK" if ok else "BUG"
    print(f"{name:<14}  {expected:>4}  {actual_str:>5}  {dt:>7.0f}  {marker:<5}  {body}")
print("=" * 100)

# --- Detect info leaks -------------------------------------------------------

print()
print("[info leak check] look for traceback / absolute path / internal exception in response body")
LEAK_PATTERNS = ["Traceback", "Traceback (most recent call last)", 'File "/', 'File "E:', 'File "C:']
for name, _exp, actual, body, _dt, _err in rows:
    if not isinstance(body, str):
        continue
    found = [p for p in LEAK_PATTERNS if p in body]
    if found:
        print(f"  [LEAK] [{name}] hit: {found}")
        print(f"     body snippet: {body[:200]}")

# --- Summary -----------------------------------------------------------------

mismatches = [(n, e, a) for (n, e, a, *_rest) in rows if a != e]
print()
print(f"total: {len(rows)}, mismatches: {len(mismatches)}")
for n, e, a in mismatches:
    print(f"  BUG: {n}: expected {e}, actual {a}")
