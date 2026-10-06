# P6 — kiểm kê corpus và gói duyệt case (06/10/2026)

Đây là kiểm tra **offline** trên snapshot người dùng đã xuất:
`data/rag_snapshots/software_p2_20261006.json`, SHA-256
`a63d20c231e4950683bd109a97101d018510c2fe3577a0d5c5836a5010a59aec`.
Không có DB/provider call trong lượt kiểm tra này. Snapshot gồm 5 documents,
34 chunks, 34/34 có embedding 768 chiều. Snapshot schema 1.0 không lưu giá trị
vector đầy đủ hoặc embedding profile từng document; chiều vector không chứng
minh model/version thực tế.

## Corpus trước khi chốt nghiệm thu

| Nguồn | Chunks | SHA-256 bytes trong DB | Việc cần quyết định |
| --- | ---: | --- | --- |
| `marketing_vlu_web_2026-10-01.pdf` | 17 | `null` (legacy) | Xác minh URL/ngày hiệu lực và provenance; tránh gọi 17-chunk re-index chỉ để điền hash khi quota còn hạn chế. |
| `software_engineering_vlu_web_2026-10-06.pdf` | 13 | Có | Duyệt nguồn/ngày hiệu lực và evidence. |
| `marketing_overview.txt` | 1 | `null` | Bản demo; quyết định giữ trong corpus nghiệm thu hay loại khỏi corpus chốt. |
| `finance_overview.txt` | 1 | `null` | Bản demo; quyết định giữ hay loại. |
| `industrial_design_overview.txt` | 2 | `null` | Chunk 0 vẫn chứa câu thử **“Hôm nay trời mưa”**; cần xử lý trước nghiệm thu chính thức. |

Không tự xóa nguồn hoặc sửa DB từ báo cáo này. Khi corpus thay đổi, export lại
snapshot và **mọi manifest** phải được đối chiếu với fingerprint mới. Nếu chỉ
thay đổi metadata/config mà nội dung evidence giữ nguyên, validator vẫn đòi
fingerprint đúng; reviewer phải xác nhận lại trước khi chuyển sang `approved`.

## Tình trạng manifest hiện tại

- `evals/cases/marketing_p0.json`: 10/10 `approved` **chỉ trên** snapshot cũ
  `3ff169ac...`. Đối chiếu với snapshot 5 nguồn, validator chỉ báo mismatch
  fingerprint; không báo lỗi liên kết document/chunk hay quote. Không chuyển
  approval sang snapshot mới tự động.
- `evals/cases/software_p3_draft.json`: 10/10 `pending_review`, validator đạt
  trên snapshot này. Chưa case nào được scoring.
- P6 preflight trên hai manifest hiện tại trả `blocked` đúng thiết kế; không
  có quality score tổng hợp.

## Gói duyệt 20 case sau khi chốt corpus

`PDF:đoạn` dưới đây lấy từ snapshot chunks, **không phải số trang PDF**.
Reviewer mở quote đầy đủ, required facts/behaviors và forbidden claims trong
manifest, kiểm tra nguồn gốc/ngày hiệu lực rồi ghi `answerability`, lý do duyệt,
reviewer và thời điểm. Các ô hành vi không có supporting evidence vẫn phải
được đánh giá đúng theo rubric, không mặc định là retrieval zero-hit.

| Case | Nội dung cần xác nhận | Evidence chính |
| --- | --- | --- |
| MKT-P0-001 | Đúng bốn chuyên ngành, không thêm ngành khác. | Marketing PDF:1 |
| MKT-P0-002 | Mục thời gian 3,5 năm; không tự hòa giải với tiêu đề “Năm 4”. | Marketing PDF:1 |
| MKT-P0-003 | Mã 7340115 và học toàn thời gian. | Marketing PDF:1 |
| MKT-P0-004 | FAQ về lĩnh vực học, không biến thành danh sách môn bắt buộc. | Marketing PDF:13 |
| MKT-P0-005 | Hai lỗi gõ nhưng cùng evidence với case 001. | Marketing PDF:1 |
| MKT-P0-006 | History chỉ xác định chủ thể là Marketing; answer dựa vào PDF. | Marketing PDF:1 |
| MKT-P0-007 | Phân biệt thời gian chung với thời gian từng chuyên ngành; không suy đoán. | Hành vi, không chấm retrieval |
| MKT-P0-008 | Hỏi rõ ngành khi thiếu chủ thể. | Hành vi, không chấm retrieval |
| MKT-P0-009 | Không suy từ FAQ ngành khác sang chính sách hai văn bằng Marketing. | Hành vi, không chấm retrieval |
| MKT-P0-010 | Yêu cầu quicksort ngoài phạm vi chatbot học vụ. | Hành vi, không chấm retrieval |
| SWE-P3-001 | Thời gian chung 4 năm, có citation. | Software PDF:1 |
| SWE-P3-002 | Ba định hướng gồm VR/AR, AI và ERP; phân biệt định hướng với chuyên ngành chính thức nếu nguồn diễn đạt khác. | Software PDF:1 |
| SWE-P3-003 | Trả nội dung FAQ, không lấy mỗi nhãn câu hỏi. | Software PDF:11 |
| SWE-P3-004 | Môn năm nhất chỉ là ví dụ từ nguồn. | Software PDF:5 |
| SWE-P3-005 | “Kỹ sư phát triển game” là hướng nghề nghiệp được nhắc tới. | Software PDF:3 |
| SWE-P3-006 | So sánh 4 năm và 3,5 năm; cần cả hai nguồn, không khẳng định thời gian riêng từng chuyên ngành. | Software PDF:1; Marketing PDF:1 |
| SWE-P3-007 | Lỗi gõ “phần mền”, vẫn hiểu Kỹ thuật phần mềm. | Software PDF:1 |
| SWE-P3-008 | Follow-up dùng history để hiểu đúng ngành; history không là chứng cứ học vụ. | Software PDF:1 |
| SWE-P3-009 | Hỏi rõ ngành, không tự chọn một trong hai. | Hành vi, không chấm retrieval |
| SWE-P3-010 | Không lấy khoảng học phí tham khảo để bịa mức chính xác năm 2027. | Hành vi, không chấm retrieval |

## Thứ tự thực hiện

1. Nhóm dữ liệu quyết định phạm vi nguồn được nghiệm thu và xử lý câu thử ở
   Industrial Design. Ghi nguồn nào được giữ; không dùng tên file demo làm
   xác nhận học vụ.
2. Export snapshot mới sau khi corpus/cấu hình ổn định; lưu SHA-256 và kiểm tra
   100% embedding dimension/non-null. Kiểm tra provenance DB riêng vì snapshot
   1.0 không export profile từng nguồn.
3. Tạo manifest P6 từ snapshot **đó**; mọi case bắt đầu `pending_review`.
   Reviewer duyệt evidence và hành vi theo bảng; chỉ `approved` được scoring.
4. Chạy preflight, rồi lifecycle live nhỏ và full evaluation khi quota sẵn.
   Rate-limit/incomplete run không đại diện cho kết quả toàn bộ pilot.

Sau bước 2, chạy từ `backend` để chuẩn bị hai bản nháp mà không mang approval
cũ sang snapshot mới:

```powershell
uv run --locked python ../scripts/prepare_rag_eval_review.py ../evals/cases/marketing_p0.json --snapshot ../data/rag_snapshots/p6_final.json --snapshot-ref data/rag_snapshots/p6_final.json --output ../evals/cases/marketing_p6_review.json
uv run --locked python ../scripts/prepare_rag_eval_review.py ../evals/cases/software_p3_draft.json --snapshot ../data/rag_snapshots/p6_final.json --snapshot-ref data/rag_snapshots/p6_final.json --output ../evals/cases/software_p6_review.json
```

Script chỉ chấp nhận nếu **mọi** document/chunk ID và evidence quote còn khớp;
nếu không, sửa evidence dựa trên nguồn mới rồi yêu cầu reviewer duyệt lại.
`phase=P0.2` giữ theo contract validator hiện có, dù file được dùng cho P6.
Không commit/chấm điểm bản nháp như thể đã được phê duyệt.
