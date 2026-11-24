# Trang Tổng quan Admin

Sau khi xác nhận quyền quản trị, trang mặc định là **Tổng quan** tại `/admin`. **Quản lý tài liệu** có địa chỉ `/admin/sources` và vẫn mở được trực tiếp. Trang Tổng quan lấy dữ liệu từ API backend `GET /admin/statistics` với Bearer token.

**7 ngày** và **30 ngày** tính cả ngày hiện tại theo múi giờ `Asia/Ho_Chi_Minh`. Với **Tùy chọn**, khoảng tối đa là 31 ngày và ô **Đến hết ngày** tính trọn ngày kết thúc. Frontend gửi ngày kế tiếp làm mốc loại trừ theo khoảng `[from, to)` của API. Tổng quan, biểu đồ, kết quả xử lý và xếp hạng cùng dùng khoảng đã áp dụng.

Tỷ lệ kết quả dùng mẫu số lượt đã kết thúc và được phân loại. Dấu **—** biểu thị giá trị API chưa đo được. **0** là số đếm có giá trị bằng không. Dashboard hiển thị riêng lượt chưa phân loại và lượt chưa kết thúc. Nút **?** mở hướng dẫn cách đọc số liệu và cách tính ngày theo bộ lọc.

Biểu đồ theo ngày nhóm lượt đã kết thúc và được phân loại theo ngày nhận câu hỏi. Chọn **Xem bảng theo ngày** để đọc số lượt từng ngày, kể cả ngày có 0 lượt và ngày chưa có số liệu.

Xếp hạng dùng thứ tự API và hiển thị số câu trả lời có trích dẫn từng tài liệu. Các thanh dùng chung mẫu số là số câu trả lời có trích dẫn tài liệu nội bộ. Nhiều đoạn của cùng một tài liệu trong một đáp án chỉ tính một lần. Xóa hội thoại loại citation tương ứng khỏi bảng xếp hạng và giữ kết quả vận hành đã ghi. Quy tắc về tên tài liệu, mốc thời gian và dữ liệu lịch sử nằm trong [tài liệu API thống kê](admin-statistics-data.md).

Chạy `npm run test:admin` từ `frontend` để kiểm tra dashboard bằng API mock và kiểm tra điều hướng Admin.
