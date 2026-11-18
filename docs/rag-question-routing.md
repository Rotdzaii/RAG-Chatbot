# Định tuyến câu hỏi

Gemini phân loại các phần trong cùng lượt xử lý câu hỏi đang có. Phần hỏi về VLU hoặc về tài liệu trong kho giữ luồng RAG, bao gồm câu nối tiếp, chuyển ngành, so sánh và kiểm kê. Nếu thiếu bằng chứng, hệ thống báo ngay trong phần nội bộ. Kiến thức chung có nhãn riêng và dùng Gemini với công cụ tìm kiếm tắt. Phần công khai cần cập nhật dùng Google Search grounding khi môi trường đã bật. Câu hỏi hỗn hợp có thể trả lời phần đủ dữ kiện và hỏi lại riêng phần còn thiếu.

Chỉ đoạn trích nguyên văn từ câu hỏi hiện tại được gửi sang luồng công khai. Nếu đoạn đó có tham chiếu nội bộ rõ ràng hoặc do model thêm nội dung, hệ thống yêu cầu làm rõ. Google Search nhận riêng đoạn công khai. Các chunk trong kho, câu trả lời nội bộ và lịch sử hội thoại nằm ngoài payload Search. Phần nội bộ của lượt hỗn hợp vẫn được dùng để giải nghĩa câu hỏi nối tiếp.

## Nguồn và lưu lịch sử

- Trích dẫn nội bộ giữ cấu trúc document/chunk cũ. Luồng RAG kiểm tra số trích dẫn trước khi ghép câu trả lời.
- HTTP và SSE gửi kết quả Google riêng trong `grounding`. Giao diện hiển thị nguyên văn kết quả, liên kết được xác minh từ metadata và Search Suggestions trong cùng một khối, đặt cạnh phần RAG. Văn bản Google được hiển thị dưới dạng văn bản thuần và chỉ liên kết từ metadata trở thành nguồn bấm được. Widget tĩnh giữ markup và CSS của Google trong Shadow DOM. Khi thiếu metadata, thiếu gợi ý hoặc widget không thể hiển thị an toàn, hệ thống báo chưa thể xác minh hoặc hiển thị kết quả. [Hướng dẫn Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search)
- Google có ngoại lệ tối đa hai năm cho văn bản kết quả khi lưu để người đặt câu hỏi xem lại lịch sử. Ứng dụng chọn thời hạn lưu bằng **0** cho cả văn bản grounding. URL, nhãn nguồn, Search Suggestions và metadata thô chỉ dùng trong lượt trực tiếp. HTTP và SSE trả kết quả trực tiếp với `Cache-Control: no-store`. Khi lưu, code chỉ ghi phần của ứng dụng, trích dẫn nội bộ và thông báo hết hạn. [Điều khoản Google Search grounding](https://ai.google.dev/gemini-api/terms#grounding-with-google-search)
- Đọc lịch sử hoặc phát lại cùng request ID trả bản ghi đã hết hạn và giữ chống lưu trùng. Với dữ liệu từ bản thử cũ có `kind: "web"`, truy cập của chủ sở hữu sẽ xóa văn bản grounding và nguồn web khỏi bản ghi, giữ nguyên phần nội bộ đứng trước và trích dẫn nội bộ. Dọn dữ liệu cũ diễn ra khi bản ghi được truy cập.
- SSE báo `web_search` khi bắt đầu gọi Search. Một lượt Search có timeout HTTP 12 giây và một lần gửi request cho Gemini. Google có thể thực hiện nhiều truy vấn trong request đó.

## Bật trên môi trường triển khai

Dùng cùng khóa Gemini và `RAG_GENERATION_MODEL` của môi trường. Google xác nhận Search grounding cho hai model hiện được cấu hình trong nhánh này. Adapter dùng các kiểu `GoogleSearch`, `GroundingMetadata` và `GroundingSupport` của SDK `google-genai 2.23.0` đã kiểm tra cục bộ. [Gemini 3.6 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash) · [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) · [GenerateContent API](https://ai.google.dev/api/generate-content#GroundingMetadata)

Để bật Search, đặt `RAG_GOOGLE_SEARCH_ENABLED=true` ở môi trường chạy backend sau khi xác nhận project Gemini API có billing và quyền dùng Google Search grounding. Khi biến chưa bật, câu hỏi cần cập nhật nhận thông báo chưa thể xác minh. Kiểm tra widget do SDK trả về trên môi trường triển khai trước khi bật cho người dùng. Renderer chỉ chấp nhận markup tĩnh, tài nguyên nội tuyến và liên kết Google Search trực tiếp.

Chạy `python -B -m unittest discover -s tests -p test_question_routing.py` từ `backend` để kiểm tra bằng SQLite và Gemini mock. Kiểm tra tải lại lịch sử và mở nguồn bằng `npm run test:source-files` từ `frontend`. Phân loại và tách phần phụ thuộc model, đặc biệt với câu ngầm định về kho hoặc câu có nhiều yêu cầu công khai cùng loại. Query plan giới hạn một lượt kiến thức chung, một lượt Search và một phần cần làm rõ. Kết quả mock xác minh hợp đồng SDK và ứng dụng. Quyền của project cùng chất lượng phân loại và metadata của lượt chạy thật cần được xác minh trên môi trường đã bật.
