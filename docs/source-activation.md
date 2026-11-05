# Backend bật/tắt nguồn

## API và trạng thái

`PATCH /admin/knowledge-sources/{source_id}/status` nhận JSON
`{"is_active": false}` hoặc `true`, yêu cầu admin hiện có. Body dùng boolean thật,
không nhận string/number hoặc field thừa. Thiếu xác thực trả 401, sai admin 403,
không tìm thấy nguồn 404, body/UUID không hợp lệ 422, lỗi DB 503 an toàn.

API chỉ đổi `is_active` và `updated_at`, không embedding hay re-index. Gửi lại cùng
trạng thái không đổi timestamp. Transaction lỗi rollback về trạng thái trước.

`GET /admin/knowledge-sources?is_active=true|false` lọc cả tổng số lẫn trang kết
quả; bỏ tham số để xem tất cả. Danh sách và chi tiết có thêm `is_active`.
Nguồn tắt vẫn hiện trong quản trị và vẫn có file/chunks/metadata.

## Retrieval và lịch sử

Helper `_retrieve` thêm `documents.is_active IS true` ngay trong SQL, trước
`ORDER BY`/`LIMIT`. Cả `retrieve_chunks` và `retrieve_candidates` dùng helper này.
Nguồn tắt dù có khoảng cách gần nhất cũng không chiếm một vị trí top-k rồi mới
bị loại ở Python.

Develop chưa có chế độ rerank. Nhánh này không thêm thuật toán, threshold hay
mode benchmark khác; ứng viên trả từ `retrieve_candidates` đã được lọc trạng
thái trước khi chuyển sang bước rerank bên ngoài. Test dùng scorer giả để kiểm
tra ranh giới này; không coi đó là kiểm chứng một chế độ rerank production.

Tắt nguồn ảnh hưởng truy vấn/câu hỏi mới. Không sửa câu trả lời, citation hoặc
message đã lưu; không thu hồi original đã được trích dẫn trong hội thoại thuộc
người dùng. `GET /source-files/{version_id}` giữ kiểm tra quyền hiện có. Bật lại
cho phép nguồn tham gia câu hỏi mới mà không cần dựng lại index.

File PDF/TXT đang tắt vẫn thay qua API hiện có; URL đang tắt vẫn refresh được.
Các luồng cập nhật không gán lại trạng thái nên nguồn tiếp tục tắt, cả sau cập
nhật thành công lẫn khi rollback. Không thêm route metadata/original mới.

## Migration và phạm vi

`a7e3c9d1b502` nối `c2a1e8d4f6b0`, thêm
`documents.is_active BOOLEAN NOT NULL DEFAULT true`. Nguồn cũ và nguồn mới đều
mặc định bật. Giữ nguyên nội dung migration a7 có sẵn và toàn bộ migration cũ.
Cần triển khai migration trước backend mới theo quy trình của môi trường.
Lần tách này không chạy migration trên DB thật.

Nhánh chỉ có backend. Admin UI chưa có trên develop và không nằm trong diff;
không kéo scheduler, metadata filters, rerank hay thay đổi model/embedding.

## Kiểm thử cô lập

```powershell
cd backend
python -m unittest discover -s tests -p test_source_activation.py -v
python -m unittest discover -s tests -p test_knowledge_source_api.py -v
python -m unittest discover -s tests -p test_knowledge_sources.py -v
python -m unittest discover -s tests -p test_retrieval.py -v
```

Activation tests dùng SQLite và storage tạm; mock embedding, query processing,
generation và URL fetch. Query retrieval thật được thực thi trong SQLite bằng
hàm cosine thay pgvector, với nguồn tắt gần hơn nguồn bật để phát hiện việc lọc
sai sau LIMIT. Kiểm tra migration backfill/default/downgrade, strict body,
phân quyền, idempotency, phân trang theo trạng thái, thay PDF/TXT, refresh URL,
rollback, câu hỏi mới và bất biến của answer/citation cũ.

Fixture chỉ thay biểu diễn JSONB/VECTOR cho SQLite; không gọi Gemini, URL thật
hay DB đang dùng. PostgreSQL row locking và pgvector thật chưa được kiểm chứng.
