# Phiên bản file gốc và citation

Upload PDF/TXT qua `POST /documents` tạo một `SourceFileVersion` bất biến và lưu
bytes gốc trong storage riêng. Chunks của lần nhập gắn với UUID phiên bản này.
Luồng retrieval → QA → HTTP/SSE → message history giữ `source_file_version_id`,
`mime_type`, `source_url` trong citation. Embedding, model, prompt và chính sách
retrieval không đổi.

Thay file qua `PUT /admin/knowledge-sources/{source_id}/file` giữ document ID,
tạo phiên bản mới và thay chunks trong transaction. Citation đã lưu vẫn trỏ đúng
UUID cũ; không chuyển sang bản mới nhất. Version được lưu trước chunk thông qua
quan hệ ORM, bảo đảm khóa ngoại hợp lệ khi flush.

Sau khi thay thành công, câu hỏi mới trong cùng cuộc trò chuyện tra cứu trên chunks
hiện hành. Câu hỏi cũ vẫn giúp xác định chủ đề. Câu trả lời từng trích chunks đã
thay hoặc đã tắt được giữ trong lịch sử và loại khỏi ngữ cảnh phân giải câu hỏi mới.

## Storage và rollback

Mặc định `RAG_SOURCE_FILE_STORAGE=local`. Đặt `RAG_SOURCE_FILE_DIR` thành đường dẫn
tuyệt đối tới thư mục riêng mà backend có quyền đọc/ghi. Mặc định là
`<repo>/data/source_files`. Thư mục này nằm ngoài các static/public files và Git.
Storage local cần filesystem hỗ trợ hard link để lưu file bất biến.

Tên file storage dùng UUID phiên bản và đuôi `.pdf`/`.txt`. Cả hai backend đều giữ
file bất biến. Nếu transaction upload/thay file thất bại, backend rollback DB và
thử dọn file vừa tạo. Khi dọn lỗi, log ghi UUID để đối chiếu sau. Nguồn URL lưu
link gốc trong citation.

Khi mở, API kiểm tra hash và kích thước (tối đa 10 MiB). Thiếu/hỏng bytes trả
503 an toàn, không trả bytes lỗi hoặc đường dẫn storage.

### Cấu hình Supabase Storage

1. Trong cùng project Supabase với DB, tạo bucket **private** `rag-source-files`.
   Backend kiểm tra bucket là private khi khởi tạo client. Giữ bucket ở chế độ
   private và giới hạn quyền đọc/ghi object cho backend.
2. Tạo một Supabase secret key (`sb_secret_...`) riêng cho backend. Dùng cấu hình
   sau trong backend `.env` hoặc Render Environment. Giữ secret trong backend.

```dotenv
SUPABASE_URL=https://your-project.supabase.co
RAG_SOURCE_FILE_BUCKET=rag-source-files
SUPABASE_STORAGE_SECRET_KEY=sb_secret_replace-with-your-server-key
```

3. Nếu DB đã có phiên bản file, chuyển dữ liệu theo hướng dẫn dưới đây. Sau đó
   đặt `RAG_SOURCE_FILE_STORAGE=supabase` cho các backend dùng chung DB. API mở
   file vẫn kiểm tra quyền như trước và trả bytes qua backend.

### Chuyển các phiên bản cũ

Chạy trên máy có file gốc theo UUID và `DATABASE_URL` trỏ đúng project. Tạm dừng
thay đổi nguồn trên các backend dùng chung DB trong lúc copy và chuyển cấu hình
để DB và bucket khớp nhau. Giữ bản sao thư mục gốc trong lúc kiểm tra bản deploy.

```powershell
cd backend
uv run --locked python ../scripts/migrate_source_files.py
```

Lần đầu là dry-run. Script đọc phiên bản từ DB rồi xác minh kích thước và SHA-256
của object trên bucket hoặc file local tại `RAG_SOURCE_FILE_DIR`. Khi báo
`Blocked: 0` và có mục `Ready`, chạy copy rồi xác minh lại:

```powershell
uv run --locked python ../scripts/migrate_source_files.py --apply
uv run --locked python ../scripts/migrate_source_files.py
```

Lần `--apply` chỉ copy file local đúng hash dưới key đã định và đọc lại từ bucket
để đối chiếu.
Chạy lại an toàn khi các object đã copy đúng. Script đọc DB và giữ các file local.
Phiên bản `blocked` cần bổ sung đúng file hoặc xử lý lỗi trước khi chuyển cấu
hình. Sau khi `Blocked: 0` và `Ready: 0`, bật Supabase Storage rồi kiểm tra mở một
citation cũ và một citation mới trên bản deploy, kể cả sau restart hoặc redeploy.

## Quyền mở và xóa nguồn

`GET /source-files/{version_id}` yêu cầu Bearer token:

- Admin được mở phiên bản đã lưu.
- User thường chỉ được mở khi message **assistant** trong hội thoại họ sở hữu
  có citation khớp cả version ID và document ID. Citation trong message user
  không cấp quyền.
- Không có quyền hoặc version không tồn tại đều trả 404; chưa đăng nhập trả 401.

Response dùng MIME PDF/TXT, tên an toàn `source.pdf`/`source.txt`,
`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.

Trong **Quản lý tài liệu**, Admin chọn **Tải tệp gốc** ngay dưới tên nguồn PDF/TXT
hoặc trong menu thao tác của nguồn.
`GET /admin/knowledge-sources/{source_id}/file` tải phiên bản khớp với nội dung
hiện tại và dùng tên file của tài liệu.

Xóa nguồn qua API hiện có xóa các version DB và thu hồi quyền mở tất cả bản cũ,
rồi dọn bytes sau commit. Nếu commit thất bại, bản gốc vẫn còn và vẫn mở được.
Nếu dọn storage lỗi sau commit, ghi log để vận hành dọn file mồ côi; API không
phục vụ file đó vì version DB đã bị xóa. Câu trả lời/citation cũ vẫn nằm trong
history, nhưng mở original sau xóa trả 404.

## Tương thích citation cũ

Các field mới là tùy chọn. Citation cũ chưa có version ID vẫn hiển thị filename,
trang/đoạn như trước; panel báo chưa lưu file gốc và không tạo nút mở. Không suy
đoán original từ filename hoặc tự lấy phiên bản mới nhất. Thay lại một file cũ
với bytes không đổi có thể bổ sung version cho chunks thiếu ID mà không embedding
lại; citation đã lưu trước đó vẫn giữ nguyên.

Người dùng có thể nhấp `[n]` trong câu trả lời hoặc ở **Nguồn tham chiếu**. Frontend
đọc file qua API có Bearer token. PDF mở ở trang được dẫn qua `#page=N` và TXT mở
để đọc trong tab mới. **Tải tệp gốc** xuất hiện dưới nguồn trích dẫn trong câu
trả lời và trong bảng **Nguồn tham khảo** khi có phiên bản tệp. Trích dẫn đã lưu
mở và tải đúng phiên bản tương ứng. Nguồn website mở liên kết gốc.

## Migration và kiểm thử

Migration `c2a1e8d4f6b0` nối `f9d4b2c7e501`, thêm bảng phiên bản, cột nullable
trên chunks và FK `ON DELETE SET NULL`. Giữ nguyên toàn bộ migration cũ và nội
dung migration c2 có sẵn. Chưa áp dụng migration lên DB thật.

```powershell
cd backend
python -m unittest discover -s tests -p test_source_files.py -v
python -m unittest discover -s tests -p test_source_file_versions_integration.py -v
python -m unittest discover -s tests -p test_ocr_source_file_versions.py -v
cd ../frontend
npm ci
npm run test:source-files
npm run test:chat
npm run build
npm run lint
```

Test tích hợp dùng DB SQLite và storage tạm, mock embedding/query/generation và
retrieval ranking. Upload, extraction PDF/TXT, mapping citation, persistence,
HTTP history và kiểm tra quyền chạy code thật. Fixture SQLite thay JSONB/VECTOR
và toán tử JSONB containment bằng biểu diễn tương đương chỉ trong test. Test unit
kiểm tra thêm query PostgreSQL `@>`; migration PostgreSQL được sinh SQL offline.
Không gọi Gemini, URL thật hay DB đang dùng. Chưa kiểm chứng migration và JSONB
trên PostgreSQL thật. Hai test OCR/storage giữ ngoài PR OCR được tái sử dụng ở
`test_ocr_source_file_versions.py`.
