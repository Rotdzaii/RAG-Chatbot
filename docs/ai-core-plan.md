# Kế hoạch phát triển AI core

## 1. Mục đích và phạm vi

Tài liệu này chuyển kết quả rà soát AI core hiện tại thành một kế hoạch triển khai và nghiệm thu có thể kiểm chứng. Mục tiêu là cải thiện RAG theo từng bước nhỏ, giữ nguyên stack nền tảng:

- FastAPI cho API và dependency/authentication;
- LangChain cho orchestration;
- Gemini cho embedding và generation;
- PostgreSQL/pgvector cho lưu trữ và vector retrieval.

Tài liệu chỉ mô tả kế hoạch. Nó không thay đổi implementation, dependency, database hoặc dữ liệu hiện tại.

Ba nguồn sau được dùng làm **tham khảo thiết kế**, không phải dependency bắt buộc của dự án:

- [Microsoft: Design and develop a RAG solution](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide): tách pipeline dữ liệu và pipeline truy vấn, đánh giá từng pha trước khi tối ưu toàn luồng.
- [Azure Search OpenAI Demo: Customizing the chat app](https://github.com/Azure-Samples/azure-search-openai-demo/blob/main/docs/customization.md): tham khảo mô hình query rewriting → search → answer và đưa lịch sử phù hợp vào bước trả lời.
- [LangSmith: Evaluate a RAG application](https://docs.langchain.com/langsmith/evaluate-rag-tutorial): tham khảo cách tách correctness, answer relevance, groundedness và retrieval relevance.

Các dự án tham khảo sử dụng Azure AI Search, Azure/OpenAI, Quart hoặc LangSmith. Kế hoạch này chỉ tiếp thu quy trình, ranh giới module và cách đánh giá; **không yêu cầu thay PostgreSQL/pgvector, Gemini, FastAPI hay cài LangSmith/Azure SDK**. Bộ đánh giá ban đầu nên chạy được bằng dữ liệu cục bộ và test runner hiện có. LangSmith chỉ là một lựa chọn về sau nếu nhóm cần quản lý dataset/experiment tập trung.

## 2. Trạng thái và mức độ bằng chứng

Tài liệu phân biệt bốn mức sau:

1. **Có trong code**: đã tìm thấy implementation trong repository.
2. **Có mock/unit test**: contract hoặc nhánh lỗi đã được test với mock/fake; không đồng nghĩa đã chạy thành công với dịch vụ thật.
3. **Đã kiểm chứng thực tế**: có quan sát thủ công trên corpus/dịch vụ thật do nhóm dự án cung cấp.
4. **Chưa có bằng chứng**: chưa có test hoặc quan sát đủ để kết luận chất lượng/thành công end-to-end.

### 2.1. Bằng chứng thực tế đã được cung cấp

| Bằng chứng | Trạng thái | Giới hạn của kết luận |
|---|---|---|
| `marketing_vlu_web_2026-10-01.pdf` trích xuất được 14.076 ký tự | Đã kiểm chứng thực tế | Chứng minh một PDF cụ thể đọc được; chưa đại diện cho PDF scan, bảng, nhiều cột hoặc font đặc biệt. |
| `POST /documents` trả 17 chunks | Đã kiểm chứng thực tế | Chứng minh luồng upload của tài liệu này tạo chunk; chưa đánh giá ranh giới/chất lượng từng chunk. |
| Đã xem text chunks trong database | Đã kiểm chứng thực tế | Chứng minh text được persist; chưa chứng minh mọi metadata, vector và nguồn đều đúng. |
| Câu hỏi về bốn chuyên ngành và thời gian 3,5 năm trả lời đúng; answer và citation đã được đối chiếu với text của chunk 1 từ PDF | Đã kiểm chứng thực tế | Là một positive case đã đối chiếu evidence; chưa chứng minh chất lượng retrieval, generation hoặc citation trên toàn bộ tập câu hỏi. |
| Follow-up “Từng chuyên ngành đều là 3.5 năm hay sao?” trả `no-context` | Đã kiểm chứng thực tế | Đây chỉ là quan sát đầu ra của một lượt chạy; tự nó không chứng minh nguyên nhân và không cho phép suy ra rằng từng chuyên ngành đều kéo dài 3,5 năm. |
| `qa.answer_question()` chỉ đưa câu hỏi hiện tại vào pipeline; luồng `/questions` không nạp message cũ để rewrite/retrieve/generate | Xác nhận từ code | Đây là bằng chứng riêng cho kết luận history chưa tham gia RAG; persistence conversation/message vẫn đang hoạt động. |
| Chưa nhận bảng xác nhận embedding của PDF đủ 768 chiều | Chưa có bằng chứng | Unit test kiểm tra dimension bằng mock, nhưng chưa có bằng chứng DB/thực tế cho toàn bộ 17 chunk của PDF này. |

## 3. Hiện trạng kiến trúc

### 3.1. Pipeline dữ liệu hiện tại

`POST /documents` → `extract_text()` → `chunk_text()` → `embed_documents()` → lưu `Document` và `Chunk`.

- PDF/TXT extraction: `backend/rag/extraction.py`.
- Chunking: `backend/rag/chunking.py`.
- Orchestration ingestion: `backend/rag/ingestion.py`.
- Embedding: `backend/rag/embeddings.py`.
- Models và metadata: `backend/rag/models.py`.
- Upload API: `backend/rag/router.py`.

### 3.2. Pipeline hỏi đáp hiện tại

`POST /questions` → xác thực/ownership → embed câu hỏi → cosine retrieval có threshold → format context → Gemini generation → lưu lượt hỏi/đáp.

- Retrieval: `backend/rag/retrieval.py` và `backend/rag/langchain_retriever.py`.
- Generation chain: `backend/rag/langchain_pipeline.py`.
- Mapping answer/source: `backend/rag/qa.py`.
- API, persistence và transaction: `backend/rag/router.py`.
- Conversation CRUD/history: `backend/rag/conversations.py` và `backend/rag/conversation_router.py`.

### 3.3. Lưu lịch sử không phải multi-turn RAG

Conversation và message hiện đã được lưu theo tài khoản. Tuy nhiên, `answer_question()` chỉ chuyển câu hỏi hiện tại vào RAG pipeline. Message trước đó không được dùng để:

- xác định chủ thể của câu follow-up;
- viết lại câu hỏi thành truy vấn độc lập;
- chọn lịch sử liên quan;
- tạo retrieval query;
- tạo context cho generation.

Vì vậy, `conversation_id` hiện chỉ quyết định **nơi lưu lượt hỏi/đáp**, không làm câu trả lời có tính hội thoại. Multi-turn chỉ hoàn thành khi lịch sử được chọn có chủ đích, được dùng để rewrite/clarify query, và hành vi đó có test/evaluation riêng.

## 4. Ma trận yêu cầu

Thứ tự triển khai dùng các pha:

- **P0**: baseline đánh giá nhỏ.
- **P1**: multi-turn và làm rõ câu hỏi.
- **P2**: chất lượng ingestion, cleaning và metadata.
- **P3**: retrieval.
- **P4**: generation và citation.
- **P5**: vòng đời nguồn.
- **P6**: nghiệm thu toàn luồng.

| Mã | Hành vi yêu cầu | Module hiện có | Phần thiếu | Test cần có | Điều kiện hoàn thành | Thứ tự |
|---|---|---|---|---|---|---|
| **RAG-01** | Nhận nguồn PDF, TXT và URL; trích xuất text an toàn, có nguồn gốc rõ ràng. | `extraction.extract_text`, `ingestion.ingest_document`, `router.upload_document`; `Document.source_type/source_url` đã có trong model; PDF dùng `PyPDFLoader`, TXT dùng UTF-8-sig. | Core còn thiếu URL fetch/extract/allowlist/timeout/redirect/content-type policy và source metadata đầy đủ. OCR PDF scan là mở rộng, không chặn bản đầu. | Unit test PDF/TXT đã có; thêm URL hợp lệ, redirect, timeout, MIME sai, private/local address, nội dung trống, cleanup; integration test từng loại nguồn đến DB. OCR có test riêng nếu được ưu tiên sau. | Core: PDF/TXT/URL text-based tạo document/chunk có provenance; URL fetch không truy cập địa chỉ cấm; lỗi không để dữ liệu dở dang; tài liệu đại diện được kiểm tra thủ công. | **P2**, sau P0; URL cần policy bảo mật được chốt trước implementation. |
| **RAG-02** | Làm sạch text, chunk theo cấu trúc phù hợp, gắn metadata và tạo embedding đồng nhất. | `chunking.chunk_text` dùng cửa sổ 1.000 ký tự/overlap 150; `embeddings.py` dùng `gemini-embedding-001`, 768 chiều, L2 normalize; models có category/audience/hash/ngày hiệu lực. | Core thiếu cleaning policy, locator trang/đoạn, embedding version và điền metadata. Layout/table phức tạp, semantic chunking nâng cao và batching lớn là mở rộng có điều kiện. Chưa xác nhận thực tế 17 vector đều 768 chiều. | Snapshot extraction/chunk đã duyệt; invariant locator; kiểm tra DB dimension/non-null cho mọi chunk; test Unicode/whitespace; regression theo snapshot hash. Test layout/table chỉ thêm khi phạm vi mở rộng được duyệt. | Core: chunk đủ truy vết về snapshot, metadata tối thiểu đầy đủ, 100% vector corpus baseline đúng dimension/model version; thay đổi chunking có báo cáo retrieval. | **P2**, sau P0; phải ổn định metadata tối thiểu trước P3/P5. |
| **RAG-03** | Trả top-k đoạn liên quan với threshold và filter phù hợp; không trả context nhiễu khi không có bằng chứng. | `retrieval.retrieve_chunks`; cosine distance ≤ `0.30`, order tăng dần, `top_k` 1–20; LangChain retriever map metadata. | Core thiếu hiệu chỉnh threshold và filter cần thiết. ANN index, lexical/hybrid/reranking/diversity là mở rộng được quyết định bằng evaluation và quy mô thực tế. | Dataset retrieval được review; Recall@k, MRR, evidence-hit, false-positive/no-hit; integration test PostgreSQL/pgvector; filter/effective-date tests; latency theo corpus đại diện. | Baseline và candidate được so trên cùng dataset/config; threshold đạt tiêu chí đã chốt; filter đúng. Chỉ thêm ANN/hybrid/reranking khi số liệu chứng minh nhu cầu. | **P3**, sau P0 và metadata tối thiểu P2. |
| **RAG-04** | Sinh câu trả lời chỉ dựa trên context, đúng ngôn ngữ, hữu ích và không thêm sự kiện không có nguồn. | `langchain_pipeline.SYSTEM_INSTRUCTION`, `_format_documents`, `_require_answer`; `qa.answer_question`. | Chưa có output schema, context/token budget, post-generation grounding check, cấu hình generation được version hóa hoặc kiểm soát claim. | Test prompt/context; groundedness, answer relevance; correctness chỉ với reference answer do người duyệt; adversarial prompt-injection; lặp nhiều lần để đo độ ổn định. | Không có claim trọng yếu ngoài evidence trong bộ nghiệm thu; prompt/model/config được ghi cùng run; regression không làm giảm metric vượt ngưỡng đã duyệt. | **P4**, sau retrieval P3 đủ ổn định. |
| **RAG-05** | Citation trong câu trả lời phải trỏ đúng nguồn và đoạn hỗ trợ claim; source payload có provenance đủ dùng. | Context được đánh số; `QuestionSource` trả document/chunk/filename/distance; assistant message lưu citations theo thứ tự retrieval. | Không parse/validate `[n]`; đang trả tất cả retrieved sources thay vì nguồn thực sự được cite; thiếu page/section/snippet/URL; chưa kiểm tra claim–evidence. | Citation index validity; cited-source precision/coverage; test citation thiếu, thừa, `[99]`; human review claim–evidence; locator test sau khi bổ sung metadata. | Mọi citation index hợp lệ; claim cần nguồn có evidence tương ứng; UI/API mở đúng source locator; không quảng bá retrieved chunk không được dùng như citation. | **P4**, phụ thuộc RAG-02 metadata và RAG-04 output contract. |
| **RAG-06** | Follow-up dùng lịch sử đúng conversation để tạo truy vấn độc lập và trả lời có ngữ cảnh, không trộn tài khoản/cuộc trò chuyện. | Conversation/message persistence và ownership đã có; message được đọc theo thời gian. | Core thiếu query rewriting và chọn một cửa sổ history có giới hạn. History summary/history dài là mở rộng, không chặn multi-turn tối thiểu. | Follow-up có đại từ/chủ thể ẩn; đổi chủ đề; conversation/account isolation; rewrite unit tests; retrieval eval trên rewritten query; case “Từng chuyên ngành…” phải không suy diễn. Test summary chỉ cần khi mở rộng. | Rewritten query bảo toàn ý định và chỉ dùng history cùng conversation; tăng retrieval evidence-hit cho follow-up; không làm giảm câu độc lập; trace cho biết standalone query nhưng không lộ nội dung nhạy cảm. | **P1**, ngay sau P0; kết quả có thể yêu cầu bổ sung P2/P3 trước khi chốt. |
| **RAG-07** | Khi thiếu căn cứ, không gọi hoặc không cho model bịa; trả thông báo nhất quán và có thể yêu cầu bổ sung thông tin. | `NO_CONTEXT_MESSAGE`; nhánh zero-result bỏ qua model; threshold retrieval hiện có. | Có chunk nhưng không đủ vẫn phụ thuộc prompt; chưa phân loại insufficient/ambiguous/out-of-scope; chưa đo false refusal và false answer. | Answerable vs unanswerable dataset; near-miss; outdated/conflicting sources; chunk liên quan nhưng thiếu đáp án; test model không được gọi ở nhánh deterministic. | Không trả lời khẳng định khi evidence thiếu; tỷ lệ false answer/false refusal đạt ngưỡng đã duyệt; reason code nội bộ đủ quan sát mà không lộ dữ liệu. | **P1** cho quy tắc clarify/no-context, hoàn thiện ở **P4** sau retrieval. |
| **RAG-08** | Nhận biết câu mơ hồ và hỏi lại ngắn gọn thay vì retrieval/generation dựa trên giả định. | Chưa có module chuyên biệt; prompt hiện chỉ yêu cầu từ chối khi context không đủ. | Thiếu ambiguity detection, clarification contract/state và cách nối câu trả lời làm rõ vào câu hỏi gốc. | Câu thiếu chủ thể, thuật ngữ nhiều nghĩa, không có history, có history đủ rõ, thay đổi chủ đề; test không search khi bắt buộc clarify; test resume sau clarification. | Câu đủ rõ đi thẳng retrieval; câu mơ hồ hỏi đúng một điểm cần thiết; câu trả lời làm rõ tạo standalone query có thể audit; không suy đoán K32. | **P1**, thiết kế cùng RAG-06/RAG-07. |
| **RAG-09** | Cập nhật, xóa và re-index nguồn một cách atomic, có provenance và không để chunk/vector cũ. | Schema có `source_url`, `content_hash`, `last_checked_at`, ngày hiệu lực; admin API hiện đọc/list metadata; cascade document→chunk đã có ở model/migration. | Core thiếu API/workflow update, delete, re-index, hash policy và transaction thay thế tối thiểu. Scheduler, job infrastructure, concurrent worker và audit workflow nâng cao là mở rộng. | Unchanged hash skip; changed content re-index; failure giữ bản đang phục vụ; delete cascade; source URL uniqueness; retrieval không thấy chunk cũ. Test concurrency/job chỉ thêm khi có infrastructure tương ứng. | Core: update/delete/re-index chạy đồng bộ hoặc theo cơ chế tối thiểu, atomic trong transaction; lỗi giữ bản tốt; xóa sạch chunk; response báo document/chunk/vector mới. | **P5**, phụ thuộc metadata/version P2 và retrieval contract P3; nghiệm thu ở P6. |

### 4.1. Core tối thiểu và mở rộng có điều kiện

| Thuộc core tối thiểu | Mở rộng có điều kiện, không chặn core |
|---|---|
| PDF/TXT có text và URL text-based; provenance tối thiểu | OCR cho PDF scan; phân tích layout/bảng/nhiều cột phức tạp |
| Cleaning xác định được, chunk locator tối thiểu, metadata nguồn, embedding version/dimension | Semantic/layout-aware chunking nâng cao; embedding batch infrastructure ở quy mô lớn |
| Vector retrieval, threshold được đo, filter cần thiết cho phạm vi/hiệu lực | ANN index, hybrid search, reranking, MMR; chỉ làm khi evaluation/quy mô chứng minh nhu cầu |
| Multi-turn với history window giới hạn, query rewriting và clarification | History summary, long-term memory và chiến lược nén lịch sử dài |
| Grounded answer, no-evidence behavior và citation validation | Grader tự động nâng cao hoặc nền tảng experiment bên ngoài |
| Update, delete và re-index atomic theo thiết kế tối thiểu | Scheduler, job queue, worker orchestration, dashboard và audit workflow nâng cao |

Một hạng mục ở cột mở rộng chỉ được đưa vào đường găng khi corpus, tải thực tế, yêu cầu vận hành hoặc kết quả evaluation cho thấy core không đạt tiêu chí.

## 5. Chi tiết theo thứ tự triển khai

### P0 — Baseline đánh giá nhỏ

Mục tiêu đầu tiên không phải thay thuật toán mà là đo nguyên trạng pipeline hiện tại trên corpus đã xác minh. **P0 không yêu cầu và không giả định có query rewriting.**

1. Tạo manifest case có ba trường độc lập: `query_type`, `answerability` và `review_status`; lưu câu hỏi, history, source/evidence dự kiến và điều kiện fail.
2. Khi chưa duyệt, `review_status=pending_review` và `answerability=unknown`. Không tự động đổi case thành `unanswerable` chỉ vì retrieval trả zero hit hoặc chưa tìm thấy evidence.
3. Chỉ case `review_status=approved` mới tham gia scoring. Báo cáo phải nêu tổng số case, số được chấm và số bị loại theo lý do/trạng thái.
4. Validator offline đối chiếu evidence quote/span với **snapshot extracted text và snapshot chunks**, không đối chiếu trực tiếp bytes PDF. Snapshot lưu provenance và SHA-256 của chính snapshot.
5. P0 gửi nguyên câu hỏi hiện tại vào pipeline. `rewritten_query` luôn có thể là `null`; mọi metric riêng cho rewriting/P1 được ghi `not_applicable`, không tính là 0 hoặc fail.
6. Ghi fingerprint cho snapshot corpus, chunk config, embedding model/dimension, retrieval threshold/top-k, generation model và prompt version.
7. Runner retrieval lưu top-k source/chunk/distance để tính các metric đã định nghĩa ở mục 7.2.
8. Runner answer lưu answer, retrieved context và citation để review. Groundedness/relevance có thể chấm không cần reference answer; correctness chỉ bật sau khi chuyên gia duyệt reference answer.
9. Baseline đầu tiên phải giữ nguyên thuật toán hiện tại để tạo mốc so sánh.

Đây là cách áp dụng quy trình đánh giá theo pha của Microsoft và cách tách evaluator của LangChain mà không bắt buộc dùng Azure AI Search hoặc LangSmith.

### P1 — Multi-turn, query rewriting và làm rõ

Luồng đề xuất:

1. Tải một cửa sổ message thuộc đúng `conversation_id` và authenticated user.
2. Phân loại câu hiện tại thành `standalone`, `needs_rewrite` hoặc `needs_clarification`.
3. Với follow-up đủ thông tin, tạo standalone retrieval query từ history và câu hiện tại.
4. Với câu mơ hồ, trả clarification question; chưa retrieval khi thiếu dữ kiện thiết yếu.
5. Retrieval dùng standalone query; generation nhận câu hỏi gốc, context truy xuất và phần history tối thiểu cần thiết.
6. Lưu/audit loại quyết định, nhưng không log toàn bộ history hoặc token.

Thiết kế này tham khảo chuỗi query rewriting → search → answer của Azure sample. Không sao chép dependency OpenAI/Azure Search; implementation vẫn dùng LangChain, Gemini và pgvector.

### P2 — Chất lượng ingestion và metadata

- Chốt cleaning policy cho Unicode, whitespace, header/footer lặp và ký tự điều khiển.
- Đo fixed-window hiện tại trước khi cân nhắc sentence/heading-aware chunking; layout/table phức tạp không thuộc bản core đầu.
- Giữ page number và section locator xuyên suốt extraction → chunk → citation.
- Điền và validate source type, source URL, content hash, category, audience, ngày xuất bản/hiệu lực.
- Gắn embedding model/version/dimension hoặc index version đủ để tránh trộn vector không tương thích.
- Xác minh toàn bộ 17 chunk của PDF baseline có vector không null, đúng 768 chiều trước khi coi ingestion end-to-end đã đạt.

### P3 — Retrieval

- Hiệu chỉnh `top_k` và threshold trên dataset P0.
- Thêm filter chỉ khi metadata đã đáng tin cậy, ưu tiên ngày hiệu lực và phạm vi tài liệu.
- Đo latency bằng PostgreSQL/pgvector thật trên kích thước corpus đại diện.
- Chỉ thử full-text/hybrid, reranking, MMR, ANN hoặc adjacent chunks dưới dạng candidate experiment khi baseline/quy mô cho thấy nhu cầu.
- Chỉ nhận candidate nếu cải thiện metric đã chốt với chi phí/latency chấp nhận được.

**Hybrid và reranking không phải mặc định của roadmap.** Dù Azure sample thường dùng hybrid + semantic reranking, dự án chỉ áp dụng nếu baseline cho thấy vector-only bỏ sót evidence hoặc xếp hạng kém.

### P4 — Grounded generation và citation

- Chốt output contract có answer, cited indices và trạng thái đủ/thiếu căn cứ.
- Validate citation index và chỉ trả nguồn thực sự được viện dẫn.
- Gắn source locator từ metadata thay vì chỉ filename/chunk index.
- Đánh giá riêng answer relevance, groundedness, citation correctness và correctness có human reference.
- Version prompt/model/config để có thể so sánh regression.

### P5 — Vòng đời nguồn

- Dùng content hash để phân biệt unchanged/changed.
- Core dùng thiết kế tối thiểu atomic: tạo/thay thế document và chunks trong một transaction, chỉ commit sau khi extraction, chunking và embedding hoàn tất; lỗi phải giữ bản đang phục vụ.
- Xóa/cập nhật/re-index là core, phải giới hạn quyền admin và không để chunk/vector cũ.
- URL ingestion cần SSRF policy, allowlist hoặc quy tắc mạng rõ ràng trước khi mở endpoint.
- Scheduler, job queue, worker và audit workflow nâng cao là mở rộng vận hành, không chặn core.

### P6 — Nghiệm thu toàn luồng

Nghiệm thu tối thiểu gồm:

- PDF, TXT và URL đại diện;
- vector dimension/model version được xác nhận;
- retrieval baseline và candidate comparison;
- standalone, follow-up, clarification và no-evidence;
- grounded answer và citation locator;
- update/delete/re-index;
- authentication/ownership isolation;
- lỗi provider/database và khả năng phục hồi;
- latency và trace tối thiểu trong môi trường staging.

## 6. Dependency và điều kiện đổi thứ tự

Thứ tự mặc định là:

> baseline đánh giá nhỏ → multi-turn/làm rõ → ingestion/metadata → retrieval → generation/citation → vòng đời nguồn → nghiệm thu toàn luồng

Có thể điều chỉnh khi:

- **P0 phát hiện evidence không thể định vị theo chunk hiện tại**: đưa page/section metadata tối thiểu của P2 lên trước khi đo citation.
- **P1 không cải thiện follow-up vì retrieval kém ngay cả với standalone query đúng**: tạm dừng multi-turn và xử lý P3.
- **Corpus có tài liệu hết hiệu lực hoặc xung đột**: đưa metadata ngày hiệu lực/filter của P2/P3 lên trước generation.
- **URL là nguồn bắt buộc cho corpus nghiệm thu**: chốt security/fetch policy của RAG-01 trước baseline mở rộng, nhưng vẫn dùng corpus file hiện tại cho baseline đầu tiên.
- **Baseline vector-only đạt yêu cầu**: không triển khai hybrid/reranking.
- **Baseline cho thấy answer sai dù context đúng**: ưu tiên P4; nếu context sai/thiếu thì ưu tiên P2/P3.

Nguyên tắc là sửa đúng điểm lỗi: query rewrite, retrieval và generation phải có artifact/metric riêng để tránh thay prompt nhằm che lỗi retrieval hoặc đổi retrieval khi model đã nhận context đúng.

## 7. Kế hoạch evaluation

### 7.1. Dataset và review

Mỗi case nên có schema tối thiểu:

```json
{
  "id": "EVAL-001",
  "query_type": "standalone | paraphrase | typo | follow_up | ambiguous | out_of_scope",
  "answerability": "unknown | answerable | partially_answerable | unanswerable",
  "review_status": "pending_review | approved | rejected",
  "question": "...",
  "history": [],
  "rewritten_query": null,
  "expected_sources": [],
  "evidence": [],
  "expected_behavior": "...",
  "fail_if": ["..."],
  "reviewer": null,
  "reviewed_at": null,
  "snapshot_provenance": null,
  "snapshot_sha256": null
}
```

Ba trường trạng thái có ý nghĩa riêng:

- `query_type` mô tả hình thức/ngữ cảnh của truy vấn, không nói corpus có trả lời được hay không.
- `answerability` mô tả khả năng trả lời dựa trên snapshot corpus đã duyệt. Case chưa duyệt luôn là `unknown`; chỉ reviewer mới được đổi sang giá trị khác.
- `review_status` quyết định case có được chấm hay không. Chỉ `approved` tham gia scoring; `pending_review` và `rejected` vẫn có thể chạy dry-run nhưng phải bị loại khỏi mẫu số.

Trong P0, `rewritten_query` là `null` vì pipeline hiện tại không rewrite. Metric query rewriting được ghi `not_applicable`. Từ P1, cùng case có thể lưu thêm rewritten query thực tế và điểm rewrite mà không làm thay đổi baseline P0.

Không dùng output hiện tại của Gemini làm ground truth. Evidence phải được trích từ snapshot text/chunks và được người có trách nhiệm nội dung duyệt. Reference answer, nếu cần cho correctness, chỉ được thêm sau bước này.

#### Snapshot evidence và provenance

Validator không tìm quote trong bytes PDF. Nó đối chiếu evidence với hai artifact sau do ingestion/extraction tạo ra:

- snapshot extracted text;
- snapshot danh sách chunks theo đúng thứ tự và nội dung đã index.

Mỗi snapshot phải ghi tối thiểu filename/source identifier, document ID nếu có, thời điểm tạo snapshot, extractor/loader version, cleaning/chunk configuration và SHA-256 tính trên nội dung snapshot đã canonicalize. Mỗi evidence entry tham chiếu snapshot hash, chunk index và quote/span. Nếu snapshot đổi, case phải quay lại `pending_review`; không được tiếp tục dùng approval của snapshot cũ.

### 7.2. Metric theo lớp

| Lớp | Artifact | Metric/kiểm tra ban đầu |
|---|---|---|
| Ingestion | extracted text, chunk, metadata, vector | coverage, chunk count, locator validity, vector non-null/dimension, snapshot review |
| Query processing | original question, selected history, rewritten query hoặc clarification | P0: `not_applicable`; P1: query-type accuracy, rewrite preserves meaning, clarification appropriateness |
| Retrieval | top-k chunks và distances | Recall@k, MRR, evidence-hit, irrelevant-context rate, no-hit behavior, latency |
| Generation | answer + retrieved context | groundedness, relevance, refusal correctness; correctness chỉ có human reference |
| Citation | claims + cited chunks | index validity, citation precision/coverage, locator correctness |
| End-to-end | request/response + trace | task success, ownership, error behavior, latency và regression |

Quy ước mẫu số và metric retrieval:

- **Tập đủ điều kiện retrieval (`E`)**: các case `review_status=approved` có `answerability` là `answerable` hoặc `partially_answerable` và có ít nhất một evidence group đã duyệt. Case `pending_review`, `rejected`, `answerability=unknown`, hoặc không có evidence group bị loại khỏi `E` và phải được báo số lượng/lý do.
- **Evidence group**: một đơn vị bằng chứng bắt buộc. Một group có thể có nhiều chunk tương đương chấp nhận được; hit khi top-k chứa ít nhất một chunk trong group. Câu cần nhiều bằng chứng có nhiều group riêng.
- **Recall@k của một case**: số evidence group bắt buộc được hit trong top-k chia cho tổng số evidence group bắt buộc của case. Recall@k toàn bộ là macro-average trên `E`, để mỗi câu có trọng số như nhau.
- **MRR@k của một case**: `1/rank` của chunk đầu tiên trong top-k khớp bất kỳ evidence group nào; bằng 0 nếu không có hit. MRR@k là trung bình trên `E`. MRR chỉ đo vị trí hit đầu tiên, không chứng minh câu nhiều bằng chứng đã đủ; phải đọc cùng Recall@k.
- **Evidence-hit@k**: tỷ lệ case trong `E` có ít nhất một evidence group được hit trong top-k. Báo thêm **all-evidence-hit@k**: tỷ lệ case trong `E` mà mọi evidence group bắt buộc đều được hit.
- **No-hit rate** được báo riêng theo `query_type` và `answerability`, không dùng thay Recall@k.

`unanswerable` không đồng nghĩa `zero-hit`: một câu không có đáp án đầy đủ vẫn có thể retrieve context liên quan, và một câu answerable bị zero-hit là lỗi retrieval. Case `unanswerable`/`out_of_scope` được đánh giá bằng refusal/groundedness và tỷ lệ context nhiễu riêng, không đưa vào mẫu số Recall@k/MRR/evidence-hit trừ khi reviewer định nghĩa evidence group cho một mục tiêu retrieval cụ thể.

LLM-as-judge chỉ là tín hiệu hỗ trợ, không thay review của con người cho các claim học vụ quan trọng. Mọi evaluator dùng model phải được version hóa và kiểm tra mẫu thủ công để phát hiện grader bias.

### 7.3. Mười tình huống đánh giá bản nháp

Tất cả case dưới đây có `review_status=pending_review` và `answerability=unknown`. Chúng chỉ trở thành dữ liệu scoring sau khi evidence trong snapshot Marketing được duyệt. P0 chạy nguyên câu hỏi; `rewritten_query=null` và metric P1 là `not_applicable`.

| ID | Query type | Answerability / review | Câu hỏi và history | Bằng chứng cần xác minh trong snapshot | Hành vi kỳ vọng | Fail nếu |
|---|---|---|---|---|---|---|
| **EVAL-001** | `standalone` | `unknown` / `pending_review` | **Q:** “Ngành Marketing có những chuyên ngành nào?”; **History:** không có. | Quote/span trong snapshot chunk đã liệt kê chuyên ngành; reviewer xác nhận số lượng và mọi tên mục. | Retrieve đúng evidence group; answer chỉ nêu các mục đã duyệt; citation trỏ đúng chunk. | Thiếu/thêm mục, citation sai hoặc thêm mô tả không có evidence. |
| **EVAL-002** | `paraphrase` | `unknown` / `pending_review` | **Q:** “Marketing ở Văn Lang chia thành các hướng chuyên sâu nào?”; **History:** không có. | Cùng evidence group với EVAL-001; reviewer xác nhận “hướng chuyên sâu” có tương đương “chuyên ngành” trong tài liệu hay không. | Nếu tương đương được duyệt, retrieve cùng evidence và trả đúng phạm vi; nếu không, yêu cầu làm rõ. | Tự coi hai thuật ngữ tương đương trước review hoặc tạo thêm hướng học. |
| **EVAL-003** | `typo` | `unknown` / `pending_review` | **Q:** “Nganh Marketting co nhung chuyen nganh nao?”; **History:** không có. | Cùng evidence group với EVAL-001; reviewer xác nhận đây là biến thể lỗi gõ/không dấu hợp lệ. | Retrieval chịu được lỗi gõ ở mức tiêu chí được duyệt và answer vẫn grounded. | Sửa sai ý định, retrieve nguồn không liên quan hoặc bịa danh sách khi không có hit. |
| **EVAL-004** | `standalone` | `unknown` / `pending_review` | **Q:** “Thời gian đào tạo của ngành Marketing là bao lâu?”; **History:** không có. | Quote/span trong snapshot nêu thời gian của toàn ngành/chương trình và phạm vi câu đó. | Trả đúng phạm vi evidence và cite đúng chunk. | Biến thời gian toàn ngành thành cam kết riêng cho từng chuyên ngành hoặc tự thêm điều kiện. |
| **EVAL-005** | `paraphrase` | `unknown` / `pending_review` | **Q:** “Học Marketing tại Văn Lang mất mấy năm?”; **History:** không có. | Cùng evidence group thời gian với EVAL-004; reviewer xác nhận paraphrase không đổi phạm vi. | Retrieve đúng đoạn thời gian và trả lời không mở rộng quá evidence. | Trả thời gian không có trong snapshot hoặc gán cho từng chuyên ngành. |
| **EVAL-006** | `standalone` | `unknown` / `pending_review` | **Q:** “Ngành Marketing có mấy chuyên ngành và thời gian đào tạo là bao lâu?”; **History:** không có. | Hai evidence group: danh sách/số chuyên ngành và thời gian toàn ngành; đối chiếu với chunk 1 đã quan sát nhưng vẫn cần approval snapshot. | Top-k phải phủ đủ các evidence group đã được reviewer đánh dấu bắt buộc; answer phân biệt rõ hai claim và cite phù hợp. | Chỉ hit/trả một nửa câu hỏi, citation không hỗ trợ claim, hoặc suy ra thời gian riêng cho từng chuyên ngành. |
| **EVAL-007** | `follow_up` | `unknown` / `pending_review` | **History:** user hỏi EVAL-006 và assistant trả lời từ snapshot; **Q:** “Từng chuyên ngành đều là 3.5 năm hay sao?” | Reviewer xác định snapshot có nói rõ thời gian của từng chuyên ngành hay chỉ nêu thời gian toàn ngành. | P0 ghi nhận nguyên trạng với `rewritten_query=null`; khi chấm hành vi nội dung, chỉ được khẳng định điều evidence nói rõ. P1 sau này đo rewrite riêng. | Suy ra thời gian từng chuyên ngành từ thời gian toàn ngành hoặc coi no-context quan sát được là bằng chứng nội dung. |
| **EVAL-008** | `follow_up` | `unknown` / `pending_review` | **History:** user hỏi “Ngành Marketing có những chuyên ngành nào?”; **Q:** “Còn thời gian đào tạo thì sao?” | Evidence group về thời gian Marketing; reviewer xác nhận history đủ để giải nghĩa chủ thể. | P0 đo pipeline hiện tại, không yêu cầu rewrite; P1 kỳ vọng nối đúng chủ thể Marketing mà không thêm facts. | P0 runner tự rewrite ngầm; hoặc answer dùng sai ngành/claim không có evidence. |
| **EVAL-009** | `ambiguous` | `unknown` / `pending_review` | **Q:** “Ngành này có những chuyên ngành nào?”; **History:** không có. | Không gán evidence nội dung trước review; reviewer xác nhận thiếu chủ thể và rubric clarification. | Không tự chọn Marketing; hành vi đích là hỏi rõ ngành. P0 chỉ ghi nhận output hiện tại và metric P1 là `not_applicable`. | Tự giả định ngành Marketing hoặc ngành khác rồi trả lời như sự thật. |
| **EVAL-010** | `out_of_scope` | `unknown` / `pending_review` | **Q:** “Thời tiết ngày mai ở Thành phố Hồ Chí Minh như thế nào?”; **History:** không có. | Reviewer xác nhận câu ngoài phạm vi trợ lý và snapshot Marketing không có evidence trả lời; không cần tạo đáp án thời tiết. | Không dùng context Marketing để trả lời và không bịa thông tin; trả phản hồi ngoài phạm vi/thiếu căn cứ phù hợp. | Trả dự báo thời tiết, gọi nguồn ngoài thiết kế hoặc gắn citation Marketing không liên quan. |

Các case học phí, điều kiện tốt nghiệp và xung đột/hiệu lực giữa nhiều nguồn được chuyển sang **evaluation backlog**. Chúng chỉ được đưa vào manifest chính khi đã có snapshot corpus tương ứng và reviewer xác nhận evidence/answerability; không dùng sự vắng mặt chưa kiểm chứng để gán `unanswerable`.

Ở trạng thái tài liệu hiện tại, cả 10 case đều bị loại khỏi scoring vì chưa được duyệt; báo cáo khởi tạo phải ghi `total_cases=10`, `scored_cases=0`, `excluded_cases=10` thay vì phát sinh điểm số giả.

### 7.4. Gate cho baseline đầu tiên

Baseline P0 chỉ được coi là sẵn sàng khi:

- manifest tách `query_type`, `answerability` và `review_status`; mọi case chưa duyệt có `answerability=unknown`;
- evidence quote/span của case approved khớp snapshot text/chunks bằng validator offline;
- provenance và SHA-256 của snapshot được lưu; approval bị vô hiệu khi snapshot thay đổi;
- chỉ case approved được chấm; báo cáo nêu `total_cases`, `scored_cases`, `excluded_cases` và phân rã lý do loại;
- corpus/config có fingerprint dựa trên snapshot và cấu hình;
- runner P0 lưu `rewritten_query=null`, retrieved chunks, answer và citations; metric P1 ghi `not_applicable`;
- báo cáo metric ghi rõ tập đủ điều kiện/mẫu số, kể cả số case nhiều evidence group;
- báo cáo phân biệt lỗi extraction, query processing, retrieval, generation và citation.

### 7.5. P0.1 — Export và kiểm tra snapshot offline

P0.1 chỉ xuất `documents`/`chunks` và kiểm tra tính toàn vẹn; chưa chạy câu hỏi, chưa rewrite và chưa tạo/approve evidence case. Chạy từ thư mục `backend` để tái sử dụng `backend/.env` và kết nối hiện có:

```powershell
cd backend
uv run --no-sync python ../scripts/export_rag_snapshot.py --output ../data/rag_snapshots/current.json
uv run --no-sync python ../scripts/validate_rag_snapshot.py ../data/rag_snapshots/current.json
```

Nếu chủ động thay snapshot đã có, thêm `--overwrite` vào lệnh export. Output dưới `data/rag_snapshots/` đã nằm trong quy tắc ignore `data/*`; không tự đưa snapshot/run output chưa duyệt vào Git.

Snapshot chứa metadata nguồn, ID/content của chunk và trạng thái/dimension embedding, không chứa vector đầy đủ, credentials, token, `DATABASE_URL` hoặc dữ liệu tài khoản. Fingerprint SHA-256 chỉ tính trên payload canonical; `exported_at` không làm đổi fingerprint. Model cấu hình trong code được ghi tách khỏi provenance model/version lưu trong DB; khi schema không lưu provenance đó, giá trị là `unknown`.

### 7.6. P0.2 — Manifest Marketing draft

P0.2 gắn 10 tình huống Marketing bản nháp với một fingerprint snapshot cụ thể và kiểm tra offline rằng evidence quote nằm đúng document/chunk. Bước này chỉ tạo dữ liệu chờ người có thẩm quyền review: mọi case vẫn `pending_review`, `answerability=unknown`, không có case được chấm điểm và không chạy hỏi đáp/query rewriting.

### 7.7. P0.3 — Baseline runner

P0.3 tạo run artifact có fingerprint/config, chỉ chạy live với case đã `approved` và giữ nguyên pipeline single-turn hiện tại (`history_used=false`, `rewritten_query=null`). Dry-run chỉ validate và báo case được chọn/bị loại, không kết nối database hoặc Gemini:

```powershell
cd backend
uv run --no-sync python ../scripts/run_rag_baseline.py ../evals/cases/marketing_p0.json --snapshot ../data/rag_snapshots/current.json --output ../data/rag_runs/marketing_p0_dry.json --dry-run
```

Bỏ `--dry-run` để chạy live sau khi có case approved. Trước lượt live đầu tiên, runner so fingerprint corpus/config đang phục vụ với snapshot và dừng nếu khác. Run output nằm dưới `data/rag_runs/`, đã được quy tắc `data/*` loại khỏi Git; file có sẵn không bị ghi đè nếu không truyền `--overwrite`.

### 7.8. P1.2 — Runner đánh giá multi-turn

Runner P1 truyền nguyên câu hỏi và history fixture đã duyệt vào `rag.qa.answer_question`, ghi action `search|clarify`, standalone query thực tế, latency query processing và kết quả retrieval/generation của chính lượt gọi đó. Runner không tạo conversation/message và không gọi rewrite hoặc retrieval lần hai chỉ để quan sát.

Chạy dry-run offline từ thư mục `backend`:

```powershell
uv run --no-sync python ../scripts/run_rag_multiturn_eval.py ../evals/cases/marketing_p0.json --snapshot ../data/rag_snapshots/current.json --output ../data/rag_runs/marketing_p1_dry.json --dry-run
```

Sau khi kiểm tra dry-run, bỏ `--dry-run` và dùng tên output mới để chạy live:

```powershell
uv run --no-sync python ../scripts/run_rag_multiturn_eval.py ../evals/cases/marketing_p0.json --snapshot ../data/rag_snapshots/current.json --output ../data/rag_runs/marketing_p1_live.json
```

Trước live run, P1 so SHA-256 canonical của `documents+chunks` giữa database và snapshot, đồng thời so riêng cấu hình extraction/chunking/embedding/retrieval với P0. Full snapshot fingerprint vẫn được ghi để truy vết nhưng không được dùng thay corpus fingerprint vì query-processing config đã thay đổi ở P1. Kiểm tra corpus chỉ xác nhận metadata `embedding_present` và `embedding_dimension`; snapshot không chứa vector đầy đủ nên không xác minh được từng giá trị vector.

## 8. Xử lý lỗi

### 8.1. Hiện có

- Extraction dọn file tạm khi thành công/lỗi và không che lỗi hệ thống ngoài lỗi PDF hỏng đã biết.
- Ingestion rollback khi ghi database thất bại.
- `/questions` kiểm tra authentication/ownership trước RAG và rollback persistence khi lỗi.
- Nhánh không có context không gọi model.
- Unit tests dùng mock kiểm tra các nhánh provider/database/auth phổ biến.

### 8.2. Cần bổ sung

- Error taxonomy nội bộ: extraction, cleaning, embedding, retrieval, rewrite, generation, persistence và source lifecycle.
- Timeout/retry/backoff có giới hạn cho Gemini và URL fetch; không retry lỗi validation/quyền.
- Idempotency hoặc job identity cho ingestion/re-index.
- Atomic activation khi re-index để lỗi không xóa bản nguồn đang phục vụ.
- Reason code cho `no_context`, `needs_clarification`, `provider_unavailable` và `source_unavailable`; response công khai vẫn ngắn gọn và không lộ chi tiết.
- Test cancellation, timeout, partial batch embedding, concurrent re-index và rollback.

## 9. Observability

### 9.1. Hiện có

`backend/rag/tracing.py` có callback ghi stage, elapsed time, document count và loại exception khi `rag_trace_enabled` bật. Test hiện có xác nhận log không chứa question, context, answer hoặc secret.

### 9.2. Cần bổ sung

Mỗi request nên có correlation ID và các event/metric không chứa nội dung nhạy cảm:

- corpus/index/prompt/model version;
- conversation ID dạng hash hoặc ID nội bộ phù hợp chính sách log;
- classification: standalone/rewrite/clarify/no-context;
- số history message được chọn và token estimate;
- embedding, DB retrieval, generation và commit latency;
- top-k, threshold, số kết quả trước/sau filter và distribution distance đã làm tròn;
- model token usage/cost nếu provider trả về;
- citation count, invalid citation count;
- ingestion source type, byte/character/chunk count, vector dimension;
- retry/error class và final outcome.

Không log access token, API key, toàn bộ prompt, raw document, raw history hoặc answer mặc định. Full payload chỉ được giữ trong dataset đánh giá đã kiểm soát quyền và có mục đích rõ ràng.

## 10. Các quyết định còn mở

1. Ai là reviewer có thẩm quyền cho nội dung chương trình đào tạo/học vụ và reference answer?
2. Corpus chính thức gồm những file/URL nào, phiên bản và ngày hiệu lực ra sao?
3. URL ingestion được phép truy cập domain nào? Core dùng manual refresh; scheduler chỉ xem xét sau và không chặn nghiệm thu core.
4. Locator citation tối thiểu là page, section, chunk hay tổ hợp nào?
5. Ngưỡng chấp nhận cho Recall@k, MRR, false answer, false refusal, groundedness và latency là bao nhiêu?
6. History window của core tối đa bao nhiêu lượt/token? Summary lịch sử là mở rộng nếu cửa sổ giới hạn không đủ.
7. Query rewriting dùng Gemini riêng, cùng model generation, hay rule-based trước rồi mới gọi model?
8. Khi câu hỏi mơ hồ, API trả schema clarification riêng hay dùng answer có reason code?
9. Cách version embedding/chunking và migration/re-index khi model thay đổi.
10. Chính sách xử lý tài liệu xung đột, hết hiệu lực và nguồn không truy cập được.
11. Ở quy mô corpus nào số liệu latency mới biện minh cho ANN index? Exact cosine search vẫn là core mặc định cho đến khi có bằng chứng khác.
12. Có sử dụng LangSmith về sau hay duy trì runner/report nội bộ; quyết định này không chặn P0.
