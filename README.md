Backend giữ `PyPDFLoader`/pypdf để lấy text có sẵn; chỉ trang không có text mới
được render và OCR bằng Tesseract `vie+eng`. Hỗ trợ PDF scan và PDF hỗn hợp,
giữ số trang và dùng chung một bộ chunk/vector. Xem [cài đặt OCR](docs/pdf-ocr.md).

## Cấu hình model chat

Backend đọc hai biến từ môi trường hoặc `backend/.env` qua `Settings`:

| Biến | Công đoạn | Mặc định khi không override |
|---|---|---|
| `RAG_QUERY_MODEL` | Xử lý/làm rõ/viết lại câu hỏi | `gemini-3.6-flash` |
| `RAG_GENERATION_MODEL` | Sinh đáp án từ ngữ cảnh | `gemini-3.6-flash` |

Mỗi biến nhận `gemini-3.6-flash` hoặc `gemini-3.8-flash`. Biến môi trường của
process ưu tiên hơn `.env`; khởi động lại backend sau khi thay đổi. Để dùng 3.8
cho cả hai công đoạn, đặt trong `backend/.env`:

```dotenv
RAG_QUERY_MODEL=gemini-3.8-flash
RAG_GENERATION_MODEL=gemini-3.8-flash
```

Embedding vẫn là `gemini-embedding-001`, 768 chiều. Các constant, snapshot và cấu
hình benchmark cũ giữ nguyên 3.8. Runner benchmark live dùng chung luồng chat:
khi chạy lại benchmark cũ, đặt rõ cả hai biến trên thành `gemini-3.8-flash` trong
môi trường chạy runner để giữ model cũ; nếu bỏ override, runtime sẽ dùng 3.6.
Metadata benchmark cũ không tự đổi theo hai biến này.

Kiểm tra offline cấu hình và lựa chọn model tại cả hai provider, không gọi Gemini:

```powershell
cd backend
python -m unittest discover -s tests -p test_chat_model_config.py -v
```
