# Dữ liệu thống kê Admin

## Đơn vị ghi nhận

`question_turns` ghi một dòng cho mỗi cặp người dùng và request ID. SSE giữ request ID và fingerprint hiện có. `POST /questions` nhận thêm `request_id` tùy chọn. Client cũ gửi HTTP không kèm ID thì mỗi lần gọi được chấp nhận là một lượt riêng. Fingerprint loại trường ID và bộ lọc rỗng để tương thích với fingerprint SSE cũ. Cùng ID với payload khác nhận HTTP 409. Replay cùng ID trả phản hồi đã lưu. Nếu lượt đã lưu phản hồi nhưng hội thoại bị xóa, replay nhận HTTP 410.

Bản ghi chứa thời điểm nhận lần đầu, thời điểm kết thúc, trạng thái, kết quả, hướng dự kiến, hướng thực thi, mã nguyên nhân và tham chiếu message khi có. Bản ghi thống kê chỉ chứa metadata vận hành. Nội dung hội thoại, dữ liệu grounding và thông tin lỗi thô nằm ngoài bản ghi này.

Lượt bắt đầu được ghi bằng giao dịch riêng. Kết thúc thành công liên kết với message trong giao dịch lưu phản hồi, có savepoint để lỗi thống kê không làm hỏng giao dịch chính. Lỗi xử lý được ghi bằng giao dịch khác sau rollback. Mã lần chạy giúp thao tác kết thúc trễ không ghi đè lần retry mới hoặc phản hồi đã commit. Retry giữ thời điểm nhận đầu tiên. Khi kho thống kê không ghi được, phản hồi chính vẫn theo luồng hiện có và số liệu có thể thiếu. Lượt chưa kết thúc hoặc bị hủy được tách khỏi mẫu số.

## Trạng thái vận hành

| Kết quả | Quy tắc |
| --- | --- |
| `answered` | Các đầu mục mà QA nhận diện đều có kết quả vận hành. |
| `partial` | Có ít nhất một đầu mục được trả lời toàn bộ hoặc một phần, và vẫn còn phần chưa xử lý được. |
| `insufficient_evidence` | Thiếu bằng chứng trong kho hoặc thiếu metadata grounding hợp lệ. |
| `clarification` | Cần thêm thông tin đầu vào để xử lý. |
| `unavailable` | Hướng xử lý chưa khả dụng, ví dụ Search đang tắt. |
| `error` | Có lỗi provider, lưu dữ liệu hoặc kiểm tra kết quả. |

Khi không có phần trả lời nào, thứ tự chọn là lỗi, cần làm rõ, không khả dụng, rồi thiếu bằng chứng. Mã nguyên nhân được giữ cho tất cả phần đã xử lý. Mỗi ô so sánh và câu trả lời dùng model có trường xác định mức độ hoàn tất riêng. Các nhánh truy xuất rỗng, kiểm kê và grounding dùng trạng thái từ kiểm tra tương ứng. Validation citation vẫn chạy riêng. Trạng thái này mô tả luồng vận hành và số đầu mục đã nhận diện. Chất lượng nội dung của model cần đánh giá riêng.

`planned_routes` ghi hướng mà bước lập kế hoạch phân bổ, còn `executed_routes` ghi hướng thực sự bắt đầu truy xuất hoặc gọi provider. Kiểm kê và quét danh mục ngành thuộc hướng nội bộ. Hướng web bị tắt không xuất hiện trong `executed_routes`. Câu làm rõ trước khi phân bổ hướng có thể có cả hai danh sách rỗng.

## API và mẫu số

`GET /admin/statistics?from=2026-11-19&to=2026-11-20&limit=10` dùng `require_admin`. Phản hồi chỉ có số đếm, tỷ lệ, thời gian và xếp hạng tài liệu. Hai ngày là khoảng nửa mở `[from, to)` ở `Asia/Ho_Chi_Minh`, được đổi sang UTC trước khi truy vấn.

- Phân bố kết quả và hướng thực thi dùng thời điểm nhận lần đầu. Mẫu số gồm lượt đã kết thúc có kết quả phân loại. `mixed` là đã thực thi nhiều hướng, `none` là chưa thực thi hướng nào. Tỷ lệ trả dưới dạng phân số từ 0 đến 1. Nếu mẫu số bằng 0 thì số đếm phân loại và tỷ lệ là `null`.
- `data_started_at` là thời điểm của bản ghi đầu tiên thực sự tồn tại. `unclassified` gồm lượt mới kết thúc thiếu kết quả có cấu trúc và câu trả lời cũ chưa liên kết bản ghi thống kê. Câu trả lời cũ lọc theo thời điểm tạo message. Không backfill trạng thái.
- Xếp hạng theo thời điểm tạo câu trả lời. Chỉ version `citation_version=1` tham gia vì router đã chọn citation hợp lệ. Đếm một lần cho mỗi cặp message và document ID. Mẫu số là tập câu trả lời có ít nhất một tài liệu hợp lệ. Tỷ lệ có thể vượt 100% khi cộng các tài liệu vì một đáp án trích nhiều tài liệu. Nguồn URL đã nhập kho vẫn có document ID và được tính.
- Khi tài liệu còn tồn tại, API dùng tên hiện tại, kể cả sau đổi tên hay thay phiên bản. Khi tài liệu đã xóa, API dùng tên citation gần nhất trong khoảng và trả `deleted: true` để hiển thị nhãn **Đã xóa**. Xóa hội thoại giữ kết quả vận hành đã ghi, đặt tham chiếu message thành NULL và loại các citation của hội thoại đó khỏi xếp hạng. Số lượt cũ chưa phân loại có thể giảm vì phụ thuộc message còn lưu.

## Migration

Từ `backend`, trên môi trường được phép triển khai, chạy `python -m alembic upgrade 8d9636d1c45e`. Revision nối sau `a7e3c9d1b502`. Bảng mới bật RLS và không cấp policy đọc từng dòng cho client. Kết nối backend cần quyền làm việc với bảng, tương tự các bảng hội thoại. Kiểm tra offline có thể dùng `python -m alembic heads` hoặc chạy các test trong `test_admin_statistics.py` với SQLite cô lập. DDL PostgreSQL được kiểm tra offline, còn migration trên PostgreSQL cần được chạy khi triển khai.
