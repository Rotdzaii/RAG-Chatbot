# Tiến trình chat qua SSE

Chat dùng `POST /questions/stream`, cùng body với `POST /questions` và thêm
`request_id` UUID. Xác thực Bearer, quyền hội thoại, model từ Settings, prompt,
retrieval và citation validation dùng luồng đã có trên develop. Endpoint JSON cũ
vẫn được giữ. Không thêm cuộc gọi model để ước lượng tiến trình.

Endpoint stream trả `text/event-stream` với ba loại event:

```text
event: progress
data: {"request_id":"…","stage":"query"}

event: result
data: {"request_id":"…","response":{"answer":"…","sources":[],"conversation_id":"…"}}

event: error
data: {"request_id":"…","status":503,"detail":"Question answering is unavailable"}
```

Stage là `query`, `retrieval`, `generation`, `validation`, phát tại ranh giới
thực hiện bước. Clarify bỏ retrieval/generation; không có ngữ cảnh thì bỏ
generation. Chỉ phát kết quả cuối sau validation và commit; không gửi token hay
đáp án nháp. Keep-alive là comment SSE, không thay đổi stage. Request/auth không
hợp lệ vẫn trả HTTP trước khi bắt đầu stream. Proxy cần tôn trọng các header
`Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`.

## Retry và hủy

Mỗi lượt giữ nguyên UUID khi thử lại. UUID5 và fingerprint payload được lưu qua
schema Conversation/Message hiện có: fingerprint nằm trong citations của message
user, còn citations assistant giữ nguyên contract. POST JSON cũ vẫn ghi citations
user là null. Không cần migration.

Khóa trong process và PostgreSQL advisory transaction lock tuần tự hóa retry
cùng user/request. Retry sau commit đọc kết quả cũ; cùng request ID nhưng payload
khác trả 409. Quyền sở hữu được kiểm tra trước khi phát lại kết quả.

Rời màn chat hủy fetch/reader và đánh dấu hủy ở backend. Checkpoint trước bước
tiếp theo và trước commit ngăn ghi dữ liệu khi đã nhận hủy. Provider đồng bộ đang
chạy không thể dừng ngay; nếu mất kết nối sát thời điểm commit, retry cùng UUID
lấy kết quả đã lưu. Đổi hội thoại giữ request vào đúng lượt/hội thoại gốc.

## Trạng thái chờ

Chữ “Đang…” đổi theo event thực tế; chấm pulse giữ nguyên khi đổi nhãn. Vệt sáng
CSS đi từ trái sang phải trên một lớp trang trí `aria-hidden`, còn chữ nền luôn
hiện đầy đủ. Màu chữ đậm giữ tương phản ngay ở đỉnh sáng. Thành công/lỗi gỡ cả hai
hiệu ứng chờ. `prefers-reduced-motion: reduce` tắt pulse, shimmer và fade; giữ
nhãn tĩnh. Chỉ câu trả lời vừa hoàn thành ở hội thoại đang mở được fade một lần.
Progress/answer không giành focus hoặc kéo xuống khi người dùng đang đọc phía trên.

## Kiểm tra offline

```powershell
cd backend
python -m unittest discover -s tests -p test_question_progress.py -v
cd ../frontend
npm ci
npm run test:chat
npm run build
npm run lint
```

Backend dùng SQLite tạm, model/retrieval giả và persistence thật. Browser test
dùng Playwright/Edge, Auth/API mock và SSE server HTTP cục bộ; chặn các địa chỉ
ngoài fixture. Ảnh kiểm tra mặc định ở `data/chat-progress-review/`, hoặc đặt
`CHAT_REVIEW_DIR`. Đây là kiểm thử offline; chưa kiểm chứng proxy hay advisory
lock PostgreSQL qua nhiều process, provider thật hoặc browser nối backend thật.

## Phạm vi tách từ working tree chính

Bản gốc tham chiếu các phần chưa merge: metadata filters, citation retry,
phiên bản file gốc và fixture/điều hướng Admin. Nhánh này chỉ lấy SSE, các hook
progress vào luồng QA hiện có và frontend/test chat độc lập. Những tính năng
trên không phải phụ thuộc của nhánh này và không nằm trong diff.
