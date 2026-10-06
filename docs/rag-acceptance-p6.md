# P6 — nghiệm thu AI core theo các cổng kiểm chứng

Mục tiêu: chốt code/corpus/cấu hình, chỉ gọi provider tại những điểm cần chứng
minh bằng dịch vụ thật. Mỗi artifact nằm trong `data/rag_runs/` (Git ignore),
không đưa credentials, câu hỏi riêng tư hoặc vector đầy đủ vào repo.

## Cổng 1: snapshot và case

Từ `backend` trong môi trường có `backend/.env`:

```powershell
uv run --locked --no-sync python ../scripts/export_rag_snapshot.py --output ../data/rag_snapshots/p6_final.json
uv run --locked --no-sync python ../scripts/validate_rag_snapshot.py ../data/rag_snapshots/p6_final.json
uv run --locked --no-sync python ../scripts/run_rag_p6_preflight.py --snapshot ../data/rag_snapshots/p6_final.json --manifest ../evals/cases/marketing_p0.json --manifest ../evals/cases/software_p3_draft.json --output ../data/rag_runs/p6_preflight.json
uv run --locked --no-sync python ../scripts/run_rag_p6_lifecycle.py --output ../data/rag_runs/p6_lifecycle_dry.json
```

Lệnh export đọc DB để tạo snapshot, không ghi DB hoặc gọi provider. Preflight
và lifecycle dry-run chỉ đọc JSON/chạy tại máy, không gọi DB/provider. Exit code
`2` và `status=blocked`
nghĩa là manifest sai fingerprint, evidence không khớp hoặc còn case chưa duyệt;
**không** phải lỗi Gemini. Snapshot mới sau khi thêm PDF Software có thể làm
manifest Marketing P0 cũ không khớp. Cần đối chiếu từng evidence/answerability,
chốt bộ case mới và duyệt lại trên snapshot cuối; không chỉ sửa fingerprint để
ép qua validator. Chỉ case `approved` được scoring. `ready_for_live_compatibility_check`
vẫn **chưa** xác minh DB hiện tại và chưa là điểm chất lượng.

Output có sẵn sẽ không bị ghi đè; đặt tên mới hoặc dùng `--overwrite` sau khi
đã lưu bản cần giữ.

## Cổng 2: vòng đời nguồn thử, live nhỏ

Chỉ chạy khi DB staging/corpus thử và quota embedding sẵn sàng:

```powershell
uv run --locked --no-sync python ../scripts/run_rag_p6_lifecycle.py --live --output ../data/rag_runs/p6_lifecycle_live.json
```

Script tạo một TXT có tên ngẫu nhiên, dùng **hai lượt batch embedding dự kiến**:
nạp mới và thay nội dung. Nó kiểm tra hash, profile, vector 768 chiều, bỏ qua
re-index khi không đổi, chunk cũ biến mất sau khi thay, lỗi embedding giả lập
giữ index đang phục vụ và xóa nguồn thử ở cuối. Không gọi chat model hoặc
question embedding. Kết quả `passed` chỉ chứng minh vòng đời TXT qua service
và DB; không chứng minh endpoint HTTP, URL/PDF hay chất lượng trả lời. Nếu
`cleanup_status=failed`, dùng `document_id` trong artifact để kiểm tra và dọn
nguồn thử theo quy trình admin; không tự xóa một ID khác.

## Cổng 3: tích hợp và chất lượng

| Hạng mục | Bằng chứng cần ghi | Trạng thái trước live |
| --- | --- | --- |
| PDF và URL đại diện | Upload/refresh qua admin API, page locator, hash/profile/vector và HTTP error mapping | Chờ kiểm chứng staging. |
| Auth và ownership | Admin mutation bị từ chối cho user thường; user A không đọc được hội thoại B | Unit tests hiện có; chờ smoke HTTP. |
| Retrieval | Baseline và candidate P3 trên **cùng** snapshot/case approved; Recall@k, MRR, evidence-hit, latency | Chờ corpus/case cuối. |
| Multi-turn | Standalone, follow-up, clarify, no-evidence; lỗi provider ghi đúng stage | Case 06–08 từng qua live gate; chờ regression sau freeze. |
| Generation và citation | Review groundedness, claim support, locator trang và index thực sự được viện dẫn | Chờ human review. |
| Phục hồi | DB/provider lỗi trả response an toàn; update lỗi không mất index cũ | Mock tests có; chờ smoke staging có kiểm soát. |

Sau khi chốt snapshot và case, chạy runner P1 trên tập đã duyệt với output mới.
Không dùng metric của run thiếu case/rate limit làm điểm toàn pilot. Mỗi answer
được người duyệt đánh dấu task completion, groundedness, citation support; chỉ
sau đó mới lập bảng so sánh P0/P1/P3. Ghi model/prompt/config, snapshot SHA-256,
ngày chạy và latency. Không đặt ngưỡng pass hoặc điểm tổng hợp khi nhóm chưa
duyệt rubric và giới hạn latency.

Gate hiện tại **không tự tuyên bố P6 hoàn tất**: P6 cần cả bằng chứng HTTP
PDF/URL, end-to-end query và human review theo bảng trên.
