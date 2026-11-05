# Thông báo URL nguồn thay đổi

Checker so SHA-256 của bytes tải lại với `Document.content_hash` đã lưu khi nhập
nguồn. Chỉ kiểm tra nguồn `source_type=url`; dùng lại chính sách URL/host/IP/TLS,
redirect và giới hạn kích thước của `fetch_source` hiện có.

Khi bytes khác baseline, tạo notification với `document_id`, `baseline_hash`,
`observed_hash`. Unique constraint trên bộ ba này và `ON CONFLICT DO NOTHING`
ngăn thông báo trùng, kể cả notification trước đã được đánh dấu đọc. Thay đổi
bytes khác tạo notification khác. Checker chỉ cập nhật `last_checked_at` khi
kiểm tra thành công; không đổi baseline, chunks, embedding hay tự re-index.

Nguồn cũ thiếu hash trả `unknown_baseline`, không tải URL và không tạo cảnh báo
phỏng đoán. Fetch thất bại trả `fetch_error`. Checker nhả transaction trước khi
tải, rồi đọc khóa lại nguồn; nếu admin refresh/xóa/đổi baseline trong lúc tải thì
trả `stale`, không so kết quả với baseline mới.

## Migration

Migration mới `f9d4b2c7e501` có `down_revision = b6c8d0e2f4a1`.
Migration cha đã có trên develop; không sửa các migration cũ. Chuỗi nhánh này có
một head là `f9d4b2c7e501`. Không cần migration phiên bản file gốc hay activation.

Migration tạo bảng `source_change_notifications`, unique constraint chống trùng,
index `read_at` và foreign key xóa theo document. Kiểm tra graph từ `backend`:

```powershell
python -m alembic history
```

Lần tách này chỉ kiểm thử migration trên DB tạm; chưa áp dụng lên DB đang dùng.
Trước khi vận hành, triển khai migration qua quy trình DB của môi trường đó.

## API admin

Cả hai route yêu cầu Bearer token và `require_admin` hiện có:

- `GET /admin/source-change-notifications?unread_only=true&limit=100&offset=0`:
  trả danh sách kèm URL hiện tại, mới nhất trước; `limit` nhận 1–100, `offset` ≥ 0.
  Bỏ `unread_only` để xem cả thông báo đã đọc.
- `POST /admin/source-change-notifications/{notification_id}/read`: đánh dấu đọc;
  gọi lại giữ thời điểm đọc cũ. Không tìm thấy trả 404, lỗi DB trả 503 an toàn.

Không thêm màn hình Admin hoặc thay đổi quyền của API hiện có.

## Kiểm tra thủ công

Chạy từ repository root với Python đã cài dependencies backend; lệnh tự chuyển
sang `backend` để đọc `.env` đúng vị trí:

```powershell
backend/.venv/Scripts/python.exe scripts/check_url_source_changes.py --help
backend/.venv/Scripts/python.exe scripts/check_url_source_changes.py
```

Lệnh thực thi sẽ truy cập URL nguồn và ghi notification/`last_checked_at` vào DB
được cấu hình. Mỗi nguồn in UUID và trạng thái, cuối cùng in `checked=N failures=M`.
`fetch_error` hoặc `stale` làm exit code 1; các trạng thái còn lại exit 0. Help và
tham số sai thoát trước khi nạp Settings, DB hoặc URL. Không tự cài scheduler,
không gọi model hay nhập lại tài liệu.

## Kiểm thử cô lập

```powershell
cd backend
python -m unittest discover -s tests -p test_source_change_checks.py -v
python -m unittest discover -s tests -p test_source_change_notifications_integration.py -v
```

Tests dùng URL/fetch giả và SQLite trong thư mục tạm: áp dụng rồi downgrade đúng
migration mới, kiểm tra unique constraint/FK, retry sau khi đọc, HTTP admin và CLI
qua transaction thật. Các test SQL mock kiểm tra thêm cú pháp PostgreSQL
`ON CONFLICT`. Không dùng DB hay URL thực. SQLite không xác minh row lock hoặc
cạnh tranh transaction PostgreSQL giữa nhiều worker; cần kiểm tra riêng trên
PostgreSQL thử nghiệm trước khi vận hành đồng thời.
