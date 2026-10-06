# P5 — vòng đời nguồn tri thức

Các thao tác sau dùng JWT admin hiện có. Mọi đường dẫn đều bắt đầu bằng
`/admin/knowledge-sources`.

| Thao tác | Đường dẫn | Kết quả |
| --- | --- | --- |
| Refresh URL đã nạp | `POST /{source_id}/refresh` | Fetch lại URL đã lưu, giữ document ID; `status=unchanged` nếu bytes, MIME và index profile không đổi. |
| Thay file đã nạp | `PUT /{source_id}/file` (`multipart/form-data`, field `file`) | Giữ document ID, thay file/chunks khi cần; chỉ PDF/TXT, tối đa 10 MiB. |
| Xóa nguồn | `DELETE /{source_id}` | `204`; document và chunks được xóa trong cùng transaction. |

Hai endpoint cập nhật trả `document_id`, `filename`, `chunk_count`, `status`
(`updated` hoặc `unchanged`). `404` là ID không có; `409` là sai loại nguồn,
URL đã đổi hoặc cập nhật cạnh tranh; `422` là text/chunk không hợp lệ. Lỗi fetch
URL trả `413`/`415`/`502` tương ứng kích thước, loại nội dung, kết nối. Lỗi
index/database trả `503` và không công bố thông tin kết nối/provider.

## Quy tắc cập nhật

1. Đọc nguồn và kiểm tra loại. URL refresh chỉ dùng URL đã lưu, đi qua bộ lọc
   domain, IP và TLS hiện có; không nhận URL tùy ý trong request.
2. So SHA-256 **bytes nguồn**, MIME, embedding profile và chunking profile.
   Nếu tất cả khớp và còn chunks, bỏ qua extraction/embedding. URL cập nhật
   `last_checked_at`; thay tên file cập nhật `filename`.
3. Nếu cần re-index, giải mã/chia chunk/tạo embeddings trước khi sửa dữ liệu.
   Không giữ khóa hàng trong thời gian gọi provider. Sau đó khóa lại hàng,
   kiểm tra nguồn có bị thay đổi trong lúc xử lý hay không. Nếu có, trả `409`.
4. Trong cùng transaction, xóa chunks cũ, thêm chunks/vector mới, cập nhật
   content hash, index profile, metadata rồi commit. Lỗi trước commit rollback;
   truy vấn không thấy một tập chunks đã xóa dở. Không sinh document ID mới.

Xóa dùng cascade `documents` → `chunks`. Nội dung câu trả lời và citation JSON
trong **lịch sử hội thoại đã lưu** vẫn là bản ghi lịch sử; không tự xóa hoặc
cập nhật chúng khi một nguồn bị thay thế/xóa. Các link đến nguồn đó trong lịch
sử có thể không còn mở được. Chưa có scheduler/worker: admin chủ động refresh.

## Kiểm chứng và giới hạn

- Test offline bao phủ bỏ qua embed khi không đổi, thay chunks đúng thứ tự,
  rollback khi embed/commit lỗi, từ chối cập nhật cạnh tranh, quyền admin,
  giới hạn file, kiểm tra URL và xóa. Test không gọi PostgreSQL/Gemini thật.
- Trước khi chạy live trên nguồn chính, dùng một URL/file thử nghiệm và xác minh:
  `document_id` giữ nguyên, hash/profile đúng, số vector 768 chiều đủ, retrieval
  trả chunks mới và không còn chunks cũ. Thử lỗi index để xác nhận chunks cũ
  vẫn dùng được. Chỉ sau đó mới thực hiện vòng đời trên corpus chính.
- Transaction không bao trùm request HTTP lấy URL hay lệnh embed bên ngoài DB;
  nếu update cạnh tranh, chi phí embed có thể đã phát sinh trước khi trả `409`.
