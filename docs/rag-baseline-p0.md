# RAG baseline P0

## 1. Phạm vi và trạng thái đánh giá

Baseline này chốt kết quả của một lần chạy live trên bộ pilot gồm 10 case Marketing, gắn với đúng manifest và snapshot nêu bên dưới. Bộ pilot phục vụ đánh giá kỹ thuật, không phải xác nhận học vụ chính thức và chưa đại diện cho chất lượng trên toàn bộ corpus hoặc toàn bộ loại câu hỏi.

Các nhận xét về nội dung câu trả lời trong tài liệu này là **đánh giá hỗ trợ bởi AI** dựa trên live output và rubric đã duyệt. Chúng không thay thế xác nhận của người duyệt. Trạng thái trong live output được giữ nguyên:

- `groundedness=pending_human_review`;
- `task_completion=pending_human_review`;
- `safety=pending_human_review`;
- `citation_support=pending_human_review`.

Không có điểm chất lượng tổng hợp được tạo. Live output cũng ghi `quality_scores_computed=false`.

## 2. Định danh run

| Thuộc tính | Giá trị |
|---|---|
| Run ID | `44f39278-0787-457d-b6ad-977c93e7a6d5` |
| Thời điểm tạo | `2026-10-04T03:23:23.724893+00:00` |
| Chế độ | `live` |
| Manifest fingerprint | `fb184d25c49f67ba60d5c66c61e3887c743d2964bf9230fa0e9f216a289e8c54` |
| Snapshot fingerprint | `3ff169ac745ae557b502d0cfea8a03d9f6c61b4334c6d63d2969c61fc017fbff` |
| Case được chọn | 10/10 |
| Case bị loại | 0 |

Nguồn kết quả: `data/rag_runs/marketing_p0_live.json`.

## 3. Cấu hình pipeline được ghi trong run

| Giai đoạn | Cấu hình |
|---|---|
| PDF extraction | `langchain_community.document_loaders.PyPDFLoader`, `mode=page`, `extract_images=false`; `langchain-community=0.4.2`, `pypdf=6.18.1` |
| TXT extraction | `utf-8-sig` |
| Chunking | Cửa sổ ký tự cố định, `chunk_size=1000`, `overlap=150` |
| Embedding | Gemini `gemini-embedding-001`, 768 chiều, L2 normalization |
| Embedding provenance lưu trong DB | Model/version `unknown`; schema hiện chưa lưu provenance này |
| Query processing | Không dùng history cho RAG; không query rewriting; `rewritten_query=null` |
| Retrieval | Cosine distance, ngưỡng tối đa `0.3`, `top_k=5` |
| Generation | Gemini `gemini-3.8-flash`; temperature `unknown` |
| System instruction | SHA-256 `f20b4e67ef8f351cd7397621a89763af154bea8e2817410af4c93c600d12b378` |
| Generation provenance lưu cùng dữ liệu | Model/version `unknown` |
| Entrypoint | `rag.qa.answer_question` |
| Execution policy | `history_used=false`, không persistence hội thoại, không retrieval lần hai để quan sát |

Tên model trong bảng là cấu hình được runner ghi nhận. Với embedding và generation, model/version thực sự gắn với dữ liệu đã lưu chưa có provenance trong schema để xác minh độc lập.

## 4. Kết quả retrieval

Retrieval được áp dụng cho 6 case và không áp dụng cho 4 case còn lại.

| Metric | Kết quả |
|---|---:|
| Evidence-hit@k | 4/6 (`0.6667`) |
| Recall@k macro | `0.6667` |
| MRR@k | `0.5833` |
| All-evidence-hit@k | `0.6667` |

Hai lỗi retrieval nổi bật:

- `MKT-P0-001` không retrieve PDF chunk 1 (`chunk_index=1`, chunk ID `a07cea80-79b4-47c3-87c0-febdf7bb366c`) chứa danh sách bốn chuyên ngành.
- `MKT-P0-005`, biến thể có lỗi gõ, cũng không retrieve chunk này.

Các metric trên chỉ dùng 6 case có `retrieval=applicable`. Bốn case `not_applicable` không nằm trong mẫu số.

## 5. Nhận xét theo case

Các nhận xét trong mục này là AI-assisted và vẫn chờ human review.

| Case | Nhận xét |
|---|---|
| `MKT-P0-001` | Không retrieve PDF chunk 1 chứa danh sách chuyên ngành; câu trả lời vì vậy không cung cấp đủ bốn tên theo rubric. |
| `MKT-P0-002` | Trả lời đúng thời gian 3,5 năm theo evidence. |
| `MKT-P0-003` | Trả lời đúng mã ngành và hình thức học theo evidence. |
| `MKT-P0-004` | Trả lời đúng các lĩnh vực Marketing theo evidence FAQ. |
| `MKT-P0-005` | Không retrieve PDF chunk 1 chứa danh sách chuyên ngành; lỗi gõ chưa được xử lý đủ tốt ở retrieval. |
| `MKT-P0-006` | Trả lời đúng thời gian Marketing, nhưng run ghi `history_used=false`; kết quả này không chứng minh khả năng multi-turn vì câu hỏi hiện tại vẫn có thể tình cờ retrieve đúng evidence mà không dùng history. |
| `MKT-P0-007` | Trả no-context. Pipeline chưa dùng history nên chưa hoàn thành yêu cầu giải thích giới hạn giữa thời gian chung của ngành và thời gian từng chuyên ngành. |
| `MKT-P0-008` | Tự chọn Marketing thay vì hỏi người dùng đang nói đến ngành nào; không đạt rubric clarification. |
| `MKT-P0-009` | Từ chối trả lời có/không là có căn cứ vì evidence chưa đủ. Tuy nhiên câu trả lời chứa citation `[13]` trong khi chỉ có 5 sources, nên citation này không hợp lệ và vẫn cần human review về citation support. |
| `MKT-P0-010` | Từ chối câu hỏi quicksort đúng theo rubric ngoài phạm vi. |

## 6. Latency

| Case | Latency |
|---|---:|
| `MKT-P0-001` | 26,956 giây |
| `MKT-P0-002` | 9,951 giây |
| `MKT-P0-003` | 4,196 giây |
| `MKT-P0-004` | 6,057 giây |
| `MKT-P0-005` | 40,563 giây |
| `MKT-P0-006` | 5,881 giây |
| `MKT-P0-007` | 1,161 giây |
| `MKT-P0-008` | 24,853 giây |
| `MKT-P0-009` | 9,571 giây |
| `MKT-P0-010` | 1,200 giây |

Tổng thời gian đo theo từng case là 130,389 giây; trung bình 13,039 giây/case, trung vị 7,814 giây, nhỏ nhất 1,161 giây và lớn nhất 40,563 giây. Đây là số liệu từ một lần chạy duy nhất, chưa đủ để mô tả phân phối latency, độ ổn định hoặc percentile vận hành.

## 7. Giới hạn của baseline

- Chỉ có 10 case trong một miền Marketing và trên một snapshot corpus.
- Chỉ có một lần live run; chưa đo biến thiên do retrieval, model hoặc hạ tầng provider.
- Nhận xét answer quality chưa được người duyệt xác nhận; bốn tiêu chí chất lượng vẫn là `pending_human_review`.
- P0 không dùng history và không rewrite query, nên không đo được năng lực multi-turn thực tế.
- Case retrieval không áp dụng không được dùng để suy ra Recall@k hoặc MRR.
- Provenance model/version thực sự của embeddings và generation chưa được lưu cùng dữ liệu.
- Citation `[13]` ở case 09 cho thấy cần kiểm tra tính hợp lệ của citation độc lập với việc câu trả lời có từ chối đúng hay không.
- Kết quả không phải ngưỡng nghiệm thu production và không tạo điểm chất lượng tổng hợp.

## 8. Ưu tiên tiếp theo

1. **P1 — History và clarification:** dùng history có kiểm soát để giải nghĩa follow-up; phân loại câu mơ hồ và hỏi làm rõ thay vì tự chọn chủ thể.
2. **P3 — Retrieval:** tập trung vào lỗi miss ở case 01 và 05, sau đó dùng bộ đánh giá để quyết định có cần cải thiện query normalization, hybrid retrieval hoặc reranking hay không.
3. **P4 — Citation:** kiểm tra index citation nằm trong phạm vi sources, đánh giá citation support và ngăn citation không hợp lệ như `[13]` khi chỉ có 5 sources.

Thứ tự trên có thể được điều chỉnh nếu P1 cho thấy retrieval input thay đổi đáng kể; khi đó cần chạy lại cùng manifest/snapshot để tách tác động query processing khỏi retrieval.
