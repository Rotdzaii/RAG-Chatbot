# Smoke test hỏi đáp nhiều tài liệu

Năm câu hỏi kiểm tra môn học của hai ngành, so sánh hai tiêu chí, hỏi ba ngành, trả lời một phần và kiểm kê kho. Mỗi ca có ý cần đạt, trang và đoạn đối chiếu, cùng các kết luận thiếu căn cứ cần phát hiện. Xem [bộ câu hỏi](../evals/smoke/multidocument.json).

## Luồng hỏi đáp và giới hạn

- Bước xử lý câu hỏi dùng lịch sử để làm rõ câu tiếp nối, ưu tiên ngành người dùng vừa nêu và hỏi lại khi chưa rõ ngành đang được nhắc tới. Câu hỏi nhiều ngành được tách theo ngành và theo tiêu chí so sánh, giữ điều kiện như kỳ nhập học và khóa.
- Truy xuất chỉ xét tài liệu đang sử dụng, đúng ngành và bộ lọc. Hệ thống chọn bằng chứng theo từng ngành và tiêu chí rồi gộp đoạn trùng. Mỗi ô chỉ được trích dẫn từ các đoạn đã chọn cho chính ngành và tiêu chí đó. Ô thiếu bằng chứng được báo riêng.
- Tiêu chí mã ngành kiểm tra nhãn, mã và kỳ nhập học khi truy vấn nêu rõ một kỳ. Tiêu chí mở vẫn phụ thuộc truy xuất ngữ nghĩa và bước sinh câu trả lời. Ngưỡng cosine distance 0.30, tối đa 10 ứng viên mỗi lượt truy xuất theo ngành và tiêu chí, và tối đa 5 đoạn trong context là cấu hình mặc định hiện hành. Chưa có đánh giá xác định các giá trị tối ưu.
- Kiểm kê đọc nội dung đoạn mở đầu của từng tài liệu đang sử dụng và gộp các khai báo cùng ngành. Nếu có tài liệu chưa nhận diện được ngành, hệ thống liệt kê phần đã xác minh và để ngỏ tổng số.

## Kết quả live đã xác minh

Lần chạy riêng `three-majors` (`single-df737b5d6a544e07bcbb86ebc140562e`) ghi nhận 1 ca hoàn tất và 0 lỗi. Ca này trả lời được hai ngành.

| Ngành | Kết quả | Bằng chứng |
| --- | --- | --- |
| Marketing | `7340115 [1]` | PDF, `chunk_index=1`. Đoạn đứng hạng 3 với distance khoảng 0.269252. Hai đoạn trước bị loại vì thiếu bằng chứng cho tiêu chí. PDF trùng tên mẫu, phiên bản chưa xác minh được bằng SHA-256. |
| Kỹ thuật phần mềm | `7480103 [2]` | PDF, `chunk_index=1`. PDF trong kho khớp SHA-256 với bản mẫu. |
| Tài chính – Ngân hàng | Chưa đủ thông tin | Runner ghi `no_identified_document` và không tìm thấy PDF mẫu khớp theo tên hoặc SHA-256 trong kho đang sử dụng. |

## Dry-run bằng PowerShell

Chạy từ **thư mục gốc của worktree chính**. Ví dụ dưới đây chọn `three-majors` và `inventory`. Để chỉ chạy một ca, dùng `$caseArgs = @('--case-id', 'three-majors')`. Để chạy cả năm, dùng `$caseArgs = @()`. Dry-run chỉ đọc các PDF mà các ca đã chọn tham chiếu, kiểm tra từng trích đoạn trên đúng trang và tính SHA-256. Hai artifact dùng chung một thư mục mới cho lần chạy này.

~~~powershell
$repo = (Get-Location).Path
$wt = Join-Path $repo '.worktrees\rag-multidocument-qa'
$python = Join-Path $repo 'backend\.venv\Scripts\python.exe'
$runner = Join-Path $wt 'scripts\run_multidocument_smoke.py'
$samples = Join-Path $repo 'data\sources'
$runDir = Join-Path $wt ('data\rag_runs\multidocument-smoke\' + [guid]::NewGuid().ToString('N'))
$caseArgs = @('--case-id', 'three-majors', '--case-id', 'inventory')
& $python -B $runner --dry-run @caseArgs --samples-dir $samples --output (Join-Path $runDir 'dry.json')
if ($LASTEXITCODE -ne 0) { throw 'Dry-run thất bại. Kiểm tra đường dẫn và phiên bản các PDF mẫu.' }
~~~

## Chạy Gemini thật

Sau khi đọc `dry.json`, dùng cùng cửa sổ PowerShell. Thư mục làm việc `backend` của worktree chính cung cấp cấu hình DB và Gemini hiện có. Runner gọi trực tiếp `answer_question` của nhánh tính năng trong một giao dịch PostgreSQL chỉ đọc. Bộ tiêu chí chấm nằm ngoài prompt gửi cho Gemini. Nghiệm thu HTTP/SSE và giao diện cần kiểm tra riêng.

~~~powershell
Push-Location (Join-Path $repo 'backend')
try {
    & $python -B $runner --live @caseArgs --samples-dir $samples --output (Join-Path $runDir 'live.json')
    if ($LASTEXITCODE -ne 0) { throw 'Live smoke chưa hoàn tất. Kiểm tra đầu ra và live.json nếu đã tạo.' }
} finally {
    Pop-Location
}
~~~

## Đọc kết quả

- `status` ghi `completed`, `error` hoặc `not_run` cho từng ca. Ca hoàn tất có thể chỉ có bằng chứng cho một phần câu hỏi. Runner dừng ở lỗi đầu và ghi giai đoạn cùng metadata provider nếu có.
- Trong `live.json`, `samples.<mẫu>.active_corpus` ghi kết quả đối chiếu với PDF đang bật. `matched` là trùng SHA-256, kể cả khi tệp đổi tên. `version_unverified` là cùng tên nhưng kho thiếu hash. `different_version` là cùng tên nhưng khác hash. `missing` là không tìm thấy PDF theo hash hoặc tên. Mảng `documents` cho biết từng bản đối chiếu khi có nhiều tệp cùng tên.
- Với `three-majors`, mở `diagnostics.plan` để xem câu tách và tổng ngân sách. Trong `diagnostics.searches`, chọn ngành Marketing và tiêu chí mã ngành. `subquestion` là câu con do bước xử lý câu hỏi trả về, `query` là chuỗi thực sự được nhúng. `candidate_limit` là giới hạn SQL cho từng lượt truy xuất, mặc định 10 khi hỏi theo ngành. `context_budget` là số đoạn tối đa ngành được đưa vào context sau khi gộp trùng giữa các tiêu chí. `no_identified_document` cho biết không có tài liệu được nhận diện cho ngành đó.
- Tìm PDF Marketing và `chunk_index = 1` trong `candidates`. So `cosine_distance` của chính lượt đó với `max_distance`. `rank` là thứ tự kiểm kê theo distance, dùng ID để phân giải đồng hạng. `retrieved_rank` là thứ tự truy xuất thực tế. `above_threshold` là vượt ngưỡng. `outside_retrieval_budget` là qua ngưỡng nhưng nằm ngoài tập ứng viên. `criterion_not_supported` là đã truy xuất nhưng thiếu trường mã ngành hợp lệ hoặc thiếu kỳ nhập học phù hợp khi câu hỏi yêu cầu. `outside_context_budget` là đủ điều kiện chọn nhưng hết chỗ khi ghép tiêu chí. `selected` đi kèm số đoạn trong context. Nếu không có ứng viên mang ID đó, kiểm tra phạm vi tài liệu và vector trước khi kết luận về hạng.
- Để so cùng một chunk ở hai câu hỏi trên cùng ảnh chụp của kho, dùng `$caseArgs = @('--case-id', 'comparison', '--case-id', 'three-majors')`. Đối chiếu chuỗi `query` và distance từng lượt. Kết quả chạy lại mô tả lần chạy mới vì Gemini có thể tách câu khác lần trước.
- Mỗi câu con được quan sát bằng một lần đọc SQL bổ sung trong cùng giao dịch, dùng lại vector truy vấn. Số ứng viên ghi vào artifact phụ thuộc kích thước kho. Mảng `context` vẫn chỉ chứa các đoạn thực sự đưa vào trả lời.
- Với từng ô trả lời, tra số trong `cited_indices` và `context[].citation`. Đọc `filename`, `page_start`, `page_end` và `content` để kiểm tra đúng ngành, tiêu chí, khóa hoặc kỳ nhập học. Các đoạn trong `context` có thể gồm cả ứng viên không được trích.
- Với câu học phí năm 2027, kiểm tra câu trả lời có giữ phần Marketing và nói rõ giới hạn của bản giới thiệu 2026. Với `inventory`, đối chiếu `diagnostics.inventory` theo `document_id` với `active_documents`. Mỗi dòng ghi nội dung chunk đầu, trang, tên ngành nhận diện và loại khai báo hoặc lý do chưa xác định. Ví dụ, `unrecognized_declaration` là có nội dung nhưng thiếu khai báo phù hợp, còn `missing_opening_chunk` là tài liệu thiếu chunk đầu. Nhiều khai báo cùng ngành chỉ đóng góp một ngành vào kết quả. Một dòng chưa xác định là đủ để hệ thống để ngỏ tổng số.
- Dry-run xác minh trích đoạn mẫu. Việc Gemini tách câu, chọn nguồn và diễn giải đúng cần được kiểm tra từ `live.json`. Runner dùng lại bộ ghi artifact của benchmark và lưu kết quả smoke độc lập theo kho hiện hành.
