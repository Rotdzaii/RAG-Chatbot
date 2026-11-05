Backend giữ `PyPDFLoader`/pypdf để lấy text có sẵn; chỉ trang không có text mới
được render và OCR bằng Tesseract `vie+eng`. Hỗ trợ PDF scan và PDF hỗn hợp,
giữ số trang và dùng chung một bộ chunk/vector. Xem [cài đặt OCR](docs/pdf-ocr.md).
