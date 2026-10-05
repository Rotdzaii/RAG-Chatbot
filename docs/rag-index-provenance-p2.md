# P2.4 — Provenance của cấu hình index

Migration `b6c8d0e2f4a1` thêm `embedding_profile` và `chunking_profile` nullable
vào `documents`. Row cũ vẫn `null`; không backfill theo cấu hình code hiện tại
vì không thể chứng minh model/loader đã dùng khi tạo từng vector. Ingestion mới
ghi cả hai profile trong cùng transaction tạo document và chunks.

- Embedding profile hiện tại: `gemini-embedding-001:768:l2:v1`. Đây là version
  **nội bộ** của cấu hình model, dimension và chuẩn hóa L2; không chứng minh
  revision phía Google vì API không cung cấp revision đã dùng cho mỗi vector.
- Chunking profile mặc định: `fixed-character-window:1000:150:v1`. Candidate
  word-alignment ở P2.3 chưa được dùng khi ingest và không mang profile này.
- Retrieval chỉ so vector từ document có embedding profile khớp với query.
  Riêng khi cấu hình vẫn là baseline, các row `null` cũ được tiếp tục phục vụ
  theo **giả định tương thích** để không ngắt chatbot. Nếu cấu hình embedding
  thay đổi, row `null` bị loại ngay; cần re-index/duyệt provenance trước khi
  chấp nhận chúng với profile mới. Profile khác hiện tại cũng bị loại.
- Đổi chunking không nhất thiết khiến vector không tương thích; retrieval
  chỉ lọc theo embedding profile. Chunking profile phục vụ đánh giá và re-index.

Snapshot schema 1.0 vẫn dùng cho pilot P0/P1: chưa xuất hai field mới, nên
không thể dùng snapshot cũ để xác nhận profile từng document. Exporter ghi
cấu hình retrieval mới vào pipeline config, khiến gate P1 phát hiện thay đổi
cấu hình khi đem so với baseline cũ. Không sửa fingerprint/manifest cũ.

Sau migration, admin có thể kiểm tra phân bố provenance bằng câu lệnh đọc:

```sql
SELECT COALESCE(embedding_profile, '<legacy-unknown>') AS embedding_profile,
       COALESCE(chunking_profile, '<legacy-unknown>') AS chunking_profile,
       COUNT(*) AS document_count
FROM documents
GROUP BY embedding_profile, chunking_profile
ORDER BY document_count DESC;
```

Trước khi bật candidate P2.3 hoặc đổi model, cần chốt profile mới, quy trình
re-index/activation nguyên tử và bộ evaluation trên corpus mới. Khi thay đổi
normalization hoặc cấu hình extraction/chunking, phải review và bump ID nội bộ;
profile hiện tại không tự phát hiện thay đổi ngầm ở provider. Bước này chưa gọi
DB thật, không re-index, và chưa xác minh provenance của tài liệu legacy.
