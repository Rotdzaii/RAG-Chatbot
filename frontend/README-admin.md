# Giao diện quản trị

Chạy frontend bằng `npm run dev`, đăng nhập tài khoản được backend cấp quyền
admin; đăng nhập từ `/login` hoặc mở `/` sẽ vào `/admin` (chuyển đến
`/admin/sources`), tài khoản thường vào `/chat`. Đường dẫn cũ
`/admin/notifications` chuyển về danh sách nguồn; không còn mục Thông báo.
Dùng cấu hình Auth/API hiện có; không cần thêm UUID
admin hoặc thông tin bí mật vào frontend.

Backend chưa có API role riêng. Trang dùng `GET /admin/knowledge-sources?limit=1`
để kiểm tra quyền, dùng chung kết quả trong bộ nhớ giữa điều hướng sau đăng
nhập, trang admin và liên kết “Mở trang quản trị” ở khu vực tài khoản trong chat.
Không xác định quyền bằng email, tên hoặc một cờ role tự lưu ở localStorage.
Trước khi xác nhận xong, màn đăng nhập/đường dẫn mặc định hiển thị trạng thái
chờ. Lỗi mạng/5xx hiển thị lỗi và cho thử lại, không chuyển ngầm sang chat.
Backend vẫn xác thực
Bearer token và quyền admin trên từng request. HTTP 401 hiển thị yêu cầu đăng
nhập lại; HTTP 403 chặn nội dung quản trị, không đăng xuất tài khoản người dùng.

Khi admin chọn “Về trò chuyện”, có thể mở lại quản trị từ liên kết ở khu vực
tài khoản. Mở trực tiếp hoặc reload `/chat` vẫn ở chat. Refresh token chỉ xác
nhận lại quyền, không tự đổi trang. Nếu đăng nhập được yêu cầu bởi một đường
dẫn `/chat` hoặc `/admin/...` cụ thể, đường dẫn đó được giữ sau đăng nhập và
trang admin vẫn kiểm tra quyền.

## Đối chiếu tài khoản chưa được nhận là admin

`backend/auth.py:get_authenticated_user()` xác minh token bằng Supabase
`auth.get_claims()`, lấy UUID ở claim `sub`. `require_admin()` so UUID này với
`Settings.admin_user_id`, được cấu hình bởi `ADMIN_USER_ID` phía backend.
Thiếu cấu hình trả 503; UUID khác trả 403. Email như `admin@gmail.com` không
tự cấp quyền quản trị.

Đối chiếu tại máy, không chia sẻ giá trị `.env` hay access token:

1. Trong Supabase Dashboard của project đang dùng, mở Authentication → Users,
   tìm tài khoản đăng nhập và xem User UID.
2. Tự mở cấu hình backend bằng trình soạn thảo, đối chiếu `ADMIN_USER_ID` với
   UID trên. Kiểm tra frontend/backend cùng project Supabase và backend đã
   được khởi động bằng cấu hình mong muốn. Không đưa UUID cấu hình vào frontend.
3. Nếu vẫn 403, đối chiếu User UID đang đăng nhập (thông tin user của phiên
   Supabase trên máy) với tài khoản vừa kiểm tra. Không lấy email hoặc metadata
   do người dùng sửa được làm bằng chứng quyền.

Việc rà soát không đọc/in `.env`, sửa quyền hay thay cấu hình này.

Các API được nối:

- `GET /admin/knowledge-sources`: trả `{ items, total, limit, offset }`, lọc loại file/URL,
  `is_active`, `category` và `audience`.
- `GET /admin/knowledge-sources/{id}`: thông tin chi tiết nguồn.
- `POST /documents`: thêm PDF/TXT, multipart field `file` và metadata tùy chọn,
  có Bearer token; trình duyệt tự đặt multipart boundary.
- `POST /admin/knowledge-sources/url`: JSON `{ url, category?, audience? }`.
- `PUT /admin/knowledge-sources/{id}/file`: thay file.
- `POST /admin/knowledge-sources/{id}/refresh`: cập nhật URL theo yêu cầu admin.
- `DELETE /admin/knowledge-sources/{id}`: xóa sau xác nhận.
- `PATCH /admin/knowledge-sources/{id}/metadata`: sửa riêng category/audience, không re-index.
- `PATCH /admin/knowledge-sources/{id}/status`: JSON `{ is_active: boolean }`;
  trả `{ id, is_active, updated_at }`.

Upload trả `{ document_id, filename, chunk_count }`; thay file hoặc refresh trả
thêm `status: "updated" | "unchanged"`. Xóa thành công trả 204, không đọc JSON.
Sửa metadata trả `{ id, category, audience, updated_at }`. Các request quản trị
đều có Bearer token và yêu cầu quyền admin.

Menu URL có “Mở URL gốc”. Menu file không có “Mở bản gốc”: backend đã merge
chưa có `/admin/knowledge-sources/{id}/original` và danh sách không trả ID phiên
bản file. Luồng mở file từ citation vẫn dùng `/source-files/{version_id}` như
trước; không lấy ID tài liệu thay cho ID phiên bản.

Trong Thêm nguồn, mục Thông tin bổ sung có “Phân loại” (`category`) và “Đối tượng” (`audience`).
Đây là nhãn tự do, không mặc định đại diện cho ngành học hoặc khóa sinh viên.
Nút “Sửa thông tin” ở từng nguồn chỉ gửi trường đã thay đổi; xóa nội dung trường
sẽ gửi `null` để xóa nhãn. Bộ lọc metadata ở đầu danh sách khớp chính xác giá
trị chuẩn hóa, có phân biệt hoa–thường; “Xóa bộ lọc” trở về mọi nguồn,
gồm nguồn chưa gán nhãn. Thay file và cập nhật URL giữ metadata đang có.

Tắt/bật nguồn cần xác nhận; thay file, refresh URL và sửa metadata vẫn giữ trạng
thái tắt. Bật lại nguồn chỉ áp dụng cho câu hỏi mới; câu trả lời và citation đã
lưu giữ nguyên. Không có tiến trình ingestion theo
giai đoạn từ backend; UI hiển thị trạng thái đang chờ và kết quả request đồng
bộ. URL chỉ được cập nhật khi admin chủ động chọn Cập nhật URL; không còn checker
hoặc thông báo thay đổi nội dung. Không tự retry thao tác ghi khi
có lỗi; nên tải lại danh sách trước khi gửi lại nếu không rõ kết quả request.

## Kiểm tra bằng fixture

```powershell
cd frontend
npm run test:admin
npm run test:chat
npm run test:source-files
npm run lint
npm run build
```

Playwright dùng Microsoft Edge headless đã cài trên máy. Cấu hình test khởi động
Vite tại `127.0.0.1:5178`, đặt Auth/API thành địa chỉ fixture và chặn các request
ngoài dev server hoặc mock. Không chạy backend, không kết nối DB/provider/URL
VLU thật. Auth session và tài liệu đều là fixture.

Ảnh Admin nằm trong `data/admin-review/`; kết quả test mặc định nằm trong
`data/chat-progress-review/test-results/` (được `data/*` ignore). Có thể dùng
`ADMIN_REVIEW_DIR` và `CHAT_REVIEW_DIR` để chuyển artifact sang thư mục tạm.
GSAP chỉ dùng cho chuyển trang/hộp thoại, tắt theo `prefers-reduced-motion` và
cleanup bằng `matchMedia.revert()` khi unmount. Module admin được tải riêng,
không đưa GSAP vào đường tải ban đầu của chat.
