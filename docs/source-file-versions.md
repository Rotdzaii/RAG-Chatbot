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

## Storage và rollback

Đặt `RAG_SOURCE_FILE_DIR` thành đường dẫn tuyệt đối tới thư mục riêng, bền vững,
backend có quyền đọc/ghi. Mặc định là `<repo>/data/source_files`. Thư mục này không
được phục vụ như static/public files và không được commit. Ví dụ `.env`:

```dotenv
RAG_SOURCE_FILE_DIR=C:/rag-data/source-files
```

Tên file storage chỉ dùng UUID và đuôi `.pdf`/`.txt`, không dùng filename upload.
Ghi file tạm, fsync rồi tạo hard link bất biến; filesystem cần hỗ trợ hard link.
Một UUID đã có không bị ghi đè. File tạm được dọn khi ghi lỗi. Nếu transaction
upload/thay file thất bại thì rollback DB và xóa bytes của phiên bản vừa tạo,
giữ nguyên các bản cũ. Không lưu original tải từ URL.

Khi mở, API kiểm tra hash và kích thước (tối đa 10 MiB). Thiếu/hỏng bytes trả
503 an toàn, không trả bytes lỗi hoặc đường dẫn storage.

## Quyền mở và xóa nguồn

`GET /source-files/{version_id}` yêu cầu Bearer token:

- Admin được mở phiên bản đã lưu.
- User thường chỉ được mở khi message **assistant** trong hội thoại họ sở hữu
  có citation khớp cả version ID và document ID. Citation trong message user
  không cấp quyền.
- Không có quyền hoặc version không tồn tại đều trả 404; chưa đăng nhập trả 401.

Response dùng MIME PDF/TXT, tên an toàn `source.pdf`/`source.txt`,
`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.

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

Frontend fetch bytes có Bearer, PDF mở Blob URL với `#page=N`, TXT tải xuống.
Các phiên bản của cùng document được giữ riêng; URL website giữ cách mở link cũ.
Nhánh này không thêm activation, scheduler, metadata filters hay giao diện Admin.

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
