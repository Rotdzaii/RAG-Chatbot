# P2.5 — Nạp URL VLU (bản tối thiểu)

Endpoint `POST /admin/knowledge-sources/url` nhận `{ "url": "https://www.vlu.edu.vn/..." }`.
Quyền admin được kiểm tra trước khi endpoint truy cập database hay mạng.
Response `201` trả `document_id`, `filename`, `chunk_count` như upload file.

- Chỉ nhận HTTPS với hostname chính xác `www.vlu.edu.vn` hoặc `vlu.edu.vn`;
  từ chối userinfo, port tùy chỉnh, fragment và ký tự điều khiển. Không mở
  hostname con tùy ý hay host ngoài allowlist.
- Trước khi kết nối, chỉ truy vấn IPv4; kiểm tra **toàn bộ** địa chỉ IPv4 DNS
  là public và chặn riêng `168.63.129.16`. Kết nối đến
  một IP đã kiểm tra, giữ hostname cho TLS SNI và xác minh certificate. Không
  dùng proxy, không theo redirect (kể cả redirect đến host hợp lệ).
- Chỉ nhận response `200` và MIME `text/html`, `text/plain`, `application/pdf`;
  giới hạn 10 MiB và 50 chunk trước khi embedding, từ chối response nén và timeout. HTML UTF-8 được chuyển
  thành text, bỏ `script/style/nav/footer/form`; không chạy JavaScript,
  tải ảnh hoặc theo các link trong trang.
- Kiểm tra URL đã tồn tại trước khi tải/embedding; unique constraint vẫn xử lý
  request đồng thời. Document lưu `source_type=url`, URL và SHA-256 bytes tải
  được. Nếu migration provenance đã áp dụng, ingestion còn lưu embedding/chunking
  profile. TXT/PDF giữ extraction và page locator hiện có.

Quy tắc DNS/IP, pin IP và không theo redirect tham khảo
[OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html).
Test chỉ dùng mock, không tải mạng hay gọi Gemini/DB thật. Trước khi dùng URL
thật, cần kiểm tra một trang VLU đại diện vì HTML tĩnh có thể thiếu nội dung
render bằng JavaScript; cleaner tối thiểu có thể vẫn chứa menu/sidebar. URL
đổi nội dung chưa được tự động re-index; vòng đời nguồn thuộc P5.
