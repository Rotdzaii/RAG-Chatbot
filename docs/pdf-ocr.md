# PDF OCR fallback

`PyPDFLoader` vẫn đọc text theo trang. Chỉ trang có text rỗng/whitespace được
PDFium render (mục tiêu 300 DPI, tối đa khoảng 20 triệu pixel/trang), rồi gửi
PNG qua stdin cho Tesseract và nhận UTF-8 qua stdout với ngôn ngữ `vie+eng`.
Trang có text được giữ nguyên; không OCR cả tài liệu. Trang render trắng hoàn
toàn được bỏ qua. Trang có nội dung nhưng OCR không đọc được chữ làm nhập liệu
thất bại, tránh lưu tài liệu thiếu trang mà không báo lỗi.

Không phát hiện phần ảnh scan trên một trang đã có text (kể cả chỉ một header).
Không tự xoay/deskew, không bảo đảm giữ bố cục bảng hoặc đọc chữ viết tay.
Ảnh mờ, nền nhiễu và độ phân giải thấp có thể cần làm sạch từ phía nguồn.

## Cài đặt

Python >=3.12, tại thư mục repository:

```powershell
uv sync --project backend
```

Dependency Python mới: `pypdfium2` (PDFium binary đi kèm wheel được hỗ trợ),
`Pillow`. Không cần Poppler, Ghostscript hoặc dịch vụ OCR bên ngoài.

Cài Tesseract 5 trên Windows theo liên kết installer UB Mannheim trong
[hướng dẫn chính thức](https://tesseract-ocr.github.io/tessdoc/Installation.html).
Chọn cả Vietnamese (`vie`) và English (`eng`); nếu thiếu, đặt
`vie.traineddata`/`eng.traineddata` từ
[tessdata_fast chính thức](https://github.com/tesseract-ocr/tessdata_fast)
vào thư mục `tessdata` của Tesseract. Không cần cài system engine cho PDF chỉ có
text, nhưng mọi môi trường nhận scan phải có đủ hai bộ ngôn ngữ.

Linux Debian/Ubuntu:

```sh
sudo apt-get install tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng
```

Kiểm tra bằng `tesseract --version` và `tesseract --list-langs` (phải có `vie`,
`eng`). Nếu executable không ở PATH, đặt trong `backend/.env`:

```dotenv
RAG_TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe
RAG_OCR_TIMEOUT_SECONDS=60
```

Có thể đặt biến môi trường Tesseract `TESSDATA_PREFIX` tới thư mục traineddata
nếu dùng vị trí tùy chỉnh. Tham khảo
[CLI chính thức](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).
Timeout áp dụng riêng từng lần gọi engine; không phải timeout toàn tài liệu.
Các tác vụ fallback OCR trong cùng process được tuần tự hóa bằng lock vì
PDFium không an toàn khi gọi đồng thời từ nhiều thread.

## Chạy và hành vi API

Khởi động backend như trước (`cd backend`, `uv run uvicorn main:app --reload`).
Admin upload multipart PDF qua `POST /documents`, hoặc nhập URL PDF hợp lệ qua
`POST /admin/knowledge-sources/url`; cả hai tự dùng fallback này. Các giới hạn
URL/MIME/kích thước hiện có vẫn áp dụng. Thay file/refresh cũng dùng cùng extractor.

Thiếu renderer/Pillow/executable hoặc `vie`/`eng`: HTTP 503 với thông báo OCR.
Engine lỗi, timeout hoặc render lỗi: HTTP 503; không trả raw stderr hay đường
dẫn nội bộ. Trang không trắng nhưng OCR trả rỗng: HTTP 400 khi upload, 422 khi
nhập URL/cập nhật. PDF trắng hoàn toàn: lỗi `No text could be extracted`.
Không embedding/ghi DB nếu trích xuất thất bại; cập nhật giữ chunk cũ.

Text OCR thay phần text trống tại đúng vị trí trang trước khi tính offsets;
`page_start/page_end`, document ID và URL đi qua pipeline hiện có.
OCR dùng các model Document/Chunk hiện có, không cần migration mới và không có
bảng/chunk/vector riêng. Không tạo TXT trung gian. PNG giữ trong RAM; PDF tạm
của loader vẫn được xóa trong `finally`.

Extraction profile được tăng trong `CHUNKING_PROFILE` (hiện dùng chung mã cho
extraction/chunking). Nguồn cũ không tự re-index. Khi admin thay file/refresh,
profile cũ sẽ buộc dựng lại chunk, kể cả bytes không đổi; nên chạy cập nhật có
chủ đích. Hash vẫn tính trên bytes gốc, không chống trùng theo text OCR.

## Kiểm thử

```powershell
cd backend
.venv/Scripts/python.exe -m unittest discover -s tests -p test_ocr.py -v
.venv/Scripts/python.exe -m unittest discover -s tests -p test_extraction.py -v
.venv/Scripts/python.exe -m unittest discover -s tests -p test_document_upload.py -v
.venv/Scripts/python.exe -m unittest discover -s tests -p test_p6_http_contract.py -v
```

Tests OCR render PDF có ảnh thật và mock tiến trình Tesseract để kiểm tra tiếng
Việt/Anh, thứ tự trang, lỗi, cleanup và luồng HTTP upload/URL qua ingestion thật.
Xác thực, embedding và DB session được mock: kiểm tra OCR trước khi lưu một bộ
chunk; khi OCR lỗi thì không tạo document/chunk, không embedding hoặc ghi DB.
Các test không gọi Gemini hay DB thật.
Để xác minh chất lượng engine thật, cần cài Tesseract với `vie+eng` và dùng PDF
scan đại diện. Test mock không chứng minh độ chính xác OCR trên dữ liệu thật.
