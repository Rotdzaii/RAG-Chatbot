# Trang Tổng quan Admin

Sau khi xác nhận quyền quản trị, trang mặc định là **Tổng quan** tại `/admin`. **Quản lý tài liệu** có địa chỉ `/admin/sources` và vẫn mở được trực tiếp. Trang Tổng quan lấy dữ liệu từ API backend `GET /admin/statistics` với Bearer token.

**7 ngày** và **30 ngày** tính cả ngày hiện tại theo múi giờ `Asia/Ho_Chi_Minh`. Với **Tùy chọn**, ngày nhập ở ô **Đến hết ngày** được tính trọn ngày. Frontend gửi ngày kế tiếp làm mốc loại trừ theo khoảng `[from, to)` của API. Tổng quan, kết quả xử lý và xếp hạng cùng dùng khoảng đã áp dụng.

Tỷ lệ kết quả dùng mẫu số lượt đã kết thúc và được phân loại. Dấu **—** biểu thị giá trị API chưa đo được. **0** là số đếm có giá trị bằng không. Dashboard hiển thị lượt chưa phân loại, lượt chưa kết thúc và mốc bản ghi đầu tiên riêng. Đã trả lời đủ đầu mục là trạng thái vận hành của QA. Độ chính xác cần đánh giá riêng.

Xếp hạng dùng thứ tự API và hiển thị số câu trả lời có trích dẫn từng tài liệu. Nhiều đoạn của cùng một tài liệu trong một đáp án chỉ tính một lần. Xóa hội thoại loại citation tương ứng khỏi bảng xếp hạng và giữ kết quả vận hành đã ghi. Quy tắc về tên tài liệu, mốc thời gian và dữ liệu lịch sử nằm trong [tài liệu API thống kê](admin-statistics-data.md).

Chạy `npm run test:admin` từ `frontend` để kiểm tra dashboard bằng API mock và kiểm tra điều hướng Admin.
