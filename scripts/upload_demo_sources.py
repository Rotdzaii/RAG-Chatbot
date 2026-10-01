"""Upload the three reviewed demo TXT files using the current backend contract.

Run from the repository root on Windows:
    cd backend
    uv run python ../scripts/upload_demo_sources.py

The script reads backend/.env, asks for the Supabase admin login interactively,
and never writes credentials or access tokens to disk.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "data" / "demo_sources" / "marketing_overview.txt",
    ROOT / "data" / "demo_sources" / "finance_overview.txt",
    ROOT / "data" / "demo_sources" / "industrial_design_overview.txt",
)


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"Không thấy file cấu hình: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[:1]):
            value = value[1:-1]
        values[key] = value
    return values


def request_json(url: str, method: str = "GET", *, headers: dict[str, str] | None = None,
                 body: bytes | None = None, timeout: int = 20) -> dict:
    request = Request(url, data=body, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        # Deliberately omit response headers and credentials from the error.
        try:
            payload = json.load(error)
            detail = payload.get("detail") or payload.get("msg") or payload.get("error_description")
        except (ValueError, AttributeError):
            detail = None
        raise RuntimeError(f"HTTP {error.code} tại {urlsplit(url).path}: {detail or error.reason}") from error
    except URLError as error:
        raise RuntimeError(f"Không kết nối được {urlsplit(url).netloc}: {error.reason}") from error


def access_token(supabase_url: str, key: str, admin_id: str) -> str:
    if urlsplit(supabase_url).scheme != "https":
        raise RuntimeError("SUPABASE_URL phải dùng HTTPS.")
    email = input("Email tài khoản admin Supabase: ").strip()
    password = getpass.getpass("Mật khẩu (không hiện trên màn hình): ")
    if not email or not password:
        raise RuntimeError("Cần email và mật khẩu admin.")
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    response = request_json(
        supabase_url.rstrip("/") + "/auth/v1/token?grant_type=password",
        "POST",
        headers={"apikey": key, "Content-Type": "application/json"},
        body=payload,
    )
    token = response.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Supabase không trả access_token.")
    # This comparison is only a local early check; the backend validates the JWT.
    try:
        token_payload = token.split(".")[1]
        token_payload += "=" * (-len(token_payload) % 4)
        subject = json.loads(base64.urlsafe_b64decode(token_payload))["sub"]
    except (IndexError, ValueError, KeyError) as error:
        raise RuntimeError("Access token không đọc được subject.") from error
    if str(subject).lower() != admin_id.lower():
        raise RuntimeError("Tài khoản đăng nhập không khớp ADMIN_USER_ID trong backend/.env.")
    return token


def existing_sources(base: str, headers: dict[str, str]) -> dict[str, dict]:
    by_name: dict[str, dict] = {}
    offset = 0
    while True:
        query = urlencode({"source_type": "file", "limit": 100, "offset": offset})
        page = request_json(f"{base}/admin/knowledge-sources?{query}", headers=headers)
        items = page["items"]
        for item in items:
            if item["filename"] in (path.name for path in SOURCES):
                by_name[item["filename"]] = item
        offset += len(items)
        if not items or offset >= page["total"]:
            return by_name


def upload(base: str, headers: dict[str, str], path: Path) -> dict:
    content = path.read_bytes()
    if not content or len(content) > 10 * 1024 * 1024:
        raise RuntimeError(f"File trống hoặc quá 10 MiB: {path.name}")
    marker = "NGUỒN THỬ NGHIỆM".encode("utf-8")
    if marker not in content or b"https://www.vlu.edu.vn/" not in content:
        raise RuntimeError(f"Nội dung TXT chưa đúng bộ demo: {path.name}")
    boundary = "codex-upload-" + uuid4().hex
    name_bytes = path.name.encode("ascii")
    body = (
        f"--{boundary}\r\n".encode()
        + b'Content-Disposition: form-data; name="file"; filename="' + name_bytes + b'"\r\n'
        + b"Content-Type: text/plain\r\n\r\n"
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return request_json(
        f"{base}/documents", "POST",
        headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        body=body, timeout=180,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nạp 3 TXT thử nghiệm Marketing, Tài chính và Thiết kế công nghiệp")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL backend đang chạy")
    parser.add_argument("--force", action="store_true", help="Cho phép nạp lại tên file đã có")
    args = parser.parse_args(argv)
    base = args.api.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Bộ demo này chỉ gửi tới backend local HTTP (localhost/127.0.0.1).")
    for path in SOURCES:
        if not path.is_file():
            raise RuntimeError(f"Thiếu file: {path}")

    env = load_env(ROOT / "backend" / ".env")
    supabase_url = os.getenv("SUPABASE_URL") or env.get("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or env.get("SUPABASE_PUBLISHABLE_KEY", "")
    admin_id = os.getenv("ADMIN_USER_ID") or env.get("ADMIN_USER_ID", "")
    if not all((supabase_url, key, admin_id)):
        raise RuntimeError("Thiếu SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY hoặc ADMIN_USER_ID trong backend/.env.")

    print("Kiểm tra backend và database...")
    request_json(f"{base}/health/db")
    print("Đăng nhập admin để lấy access token (không lưu mật khẩu/token)...")
    token = access_token(supabase_url, key, admin_id)
    headers = {"Authorization": f"Bearer {token}"}
    known = existing_sources(base, headers)

    for path in SOURCES:
        old = known.get(path.name)
        if old and not args.force:
            print(f"BỎ QUA {path.name}: đã có document_id={old['id']}, chunks={old['chunk_count']}."
                  " Nếu cần nạp lại, dùng --force (sẽ tạo bản ghi thứ hai).")
            continue
        print(f"Đang nạp {path.name}...")
        result = upload(base, headers, path)
        if not isinstance(result, dict):
            raise RuntimeError(f"Response POST /documents không hợp lệ cho {path.name}.")
        filename = result.get("filename")
        document_id = result.get("document_id")
        chunk_count = result.get("chunk_count")
        if (
            not isinstance(filename, str)
            or not filename
            or not isinstance(document_id, str)
            or not document_id
            or not isinstance(chunk_count, int)
            or isinstance(chunk_count, bool)
            or chunk_count <= 0
        ):
            raise RuntimeError(f"Response POST /documents không hợp lệ cho {path.name}.")
        print(
            f"OK {filename}: document_id={document_id}, chunks={chunk_count}"
        )
    print("Hoàn tất. Vào /chat hỏi: Marketing ở Văn Lang học về những gì?")
    return 0


def run(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (RuntimeError, KeyError, OSError) as error:
        print(f"LỖI: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
