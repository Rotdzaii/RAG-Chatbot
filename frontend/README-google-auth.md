# Đăng nhập Google trên Home

Home mở hộp “Đăng nhập hoặc đăng ký” sau 750 ms kể từ khi đã xác định khách.
Mỗi tab chỉ tự mở một lần; gõ/chọn gợi ý trước đó sẽ bỏ lượt tự mở. Hai nút
đăng nhập vẫn mở hộp theo yêu cầu. Esc/× đóng hộp và trả focus, không xóa nháp.
Hiệu ứng GSAP 190 ms tôn trọng reduced motion và được dọn khi đóng.

Google chỉ chạy khi bấm nút qua `supabase.auth.signInWithOAuth`. Câu nháp lưu
bằng `pendingQuestion.ts` trước khi chuyển sang Google hoặc trang email.
Callback về `${window.location.origin}/login`; client Supabase hiện có tự khôi
phục session từ URL. Callback lỗi/hủy hiển thị thông báo và nút thử lại Google
bên cạnh luồng email/đăng ký hiện có. User vào `/chat`, điền nháp và tự gửi;
Admin vào `/admin/sources` sau khi backend xác nhận quyền. Không cấp quyền
bằng email hay metadata Google.

## Cấu hình để tự thử Google thật

Các bước này **chưa được thực hiện** trong lần sửa frontend:

1. Bật provider Google trong Supabase Authentication → Sign In / Providers;
   điền Google OAuth Client ID và Client Secret ở Supabase, không đưa secret
   vào mã nguồn hay biến `VITE_*`.
2. Trong Google Cloud OAuth client loại Web application, thêm Authorized
   redirect URI đúng bằng Callback URL hiển thị ở provider Google của Supabase,
   thường là `https://<project-ref>.supabase.co/auth/v1/callback`.
   Authorized JavaScript origins dùng origin frontend bạn thực sự mở.
3. Trong Supabase Authentication → URL Configuration → Redirect URLs, thêm
   origin frontend kèm `/login`. Ví dụ nếu dùng Vite cổng 5173:
   `http://localhost:5173/login`, hoặc `http://127.0.0.1:5173/login` nếu mở bằng
   IP; production dùng `https://<ten-mien-frontend>/login`.
   Host và port phải khớp địa chỉ đang mở; không đổi host giữa luồng vì nháp
   được lưu theo origin trong tab. Đặt Site URL theo URL frontend chính.
4. Nếu Google OAuth đang ở chế độ Testing, dùng tài khoản đã thêm vào Test users.

Tham khảo [Google với Supabase](https://supabase.com/docs/guides/auth/social-sign-in/auth-google)
và [Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls).

## Kiểm tra cục bộ

Từ `frontend`: `npm run build`, `npm run lint`, `npm run test:admin`,
`npm run test:chat`. Playwright dùng Auth/API/SSE và Google callback giả lập;
không liên hệ Google thật, Supabase thật hay backend/DB. Fixture kiểm tra
`provider=google` và `redirect_to` cùng origin `/login`.
