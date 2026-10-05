# P2.3 — Audit ranh giới chunk (offline)

Snapshot: `software_p2_20261006.json`, SHA-256
`a63d20c231e4950683bd109a97101d018510c2fe3577a0d5c5836a5010a59aec`.
Snapshot này có 5 document, 34 chunk; cả 34 embedding đều hiện diện và có 768 chiều.
Không thay thế snapshot/manifest P0 bằng snapshot này.

| Nguồn | Chunk | Ranh giới bắt đầu giữa từ | Mẫu số |
| --- | ---: | ---: | ---: |
| Marketing PDF | 17 | 10 | 16 |
| Kỹ thuật phần mềm PDF | 13 | 6 | 12 |
| Ba TXT | 4 | Không chấm | Không chấm |

Một ranh giới được tính là giữa từ khi ký tự ngay trước điểm bắt đầu và ký tự
đầu chunk mới đều là chữ/số. Vị trí bắt đầu được tìm trong phần overlap chính
xác giữa hai chunk liên tiếp; đây là số liệu của **chunk hiện đang lưu**, không
phải kết quả của bản sửa. Cả hai PDF có thể nối lại từ các phần overlap khớp
chính xác (16/16 và 12/12). Nối từ chunk đã `strip` chỉ dùng để thử candidate;
không thay thế text gốc của PDF cho việc re-index hoặc chứng minh page locator.
Hai chunk trong TXT Thiết kế công nghiệp không có overlap khớp, nên không thể
suy ra ranh giới từ snapshot này.

Các dấu hiệu dữ liệu khác:

- Chuỗi menu `Trang chủ Sinh viên Nhân viên Cựu sinh viên` xuất hiện trong 11
  chunk Marketing và 10 chunk Kỹ thuật phần mềm. Overlap có thể làm tăng số lần
  xuất hiện tính trên chunk; cần so với từng trang gốc trước khi viết cleaner.
- Chunk 0 của `industrial_design_overview.txt` là `Hôm nay trời mưa`. Đây là dữ
  liệu test có sẵn; không xóa tự động khỏi database trong đợt audit này.
- `content_hash` của bốn nguồn cũ là `null`; PDF Kỹ thuật phần mềm mới có hash.
  Không tự điền hash khi không còn bytes gốc đáng tin cậy.
- Snapshot schema 1.0 không xuất `page_start/page_end`, nên không chấm được độ
  chính xác locator trang từ artifact này. Kiểm tra SQL live về khoảng trang
  của PDF Kỹ thuật phần mềm là một bằng chứng riêng.

Candidate `chunk_text_with_offsets(..., align_to_words=True)` chọn khoảng trắng
gần giới hạn 1.000 ký tự và gần điểm bắt đầu overlap 150 ký tự, giữ offset về
text đầu vào. Khi không có khoảng trắng gần đó, candidate dùng ranh giới cũ để
luôn tiến lên. Trên text **dựng lại từ snapshot**, candidate vẫn tạo 17 và 13
chunk và có 0 ranh giới bắt đầu giữa từ ở cả hai PDF. Đây là phép đo hình thức,
chưa chứng minh retrieval/answer tốt hơn.

Ingestion mặc định tiếp tục dùng fixed window cũ. Trước khi bật candidate cho
nguồn mới hoặc re-index nguồn cũ, cần giữ provenance của chunking/index version,
đo retrieval trên cùng case đã duyệt, và chạy gate nhỏ với PDF thật. Không trộn
vector cũ và mới dưới cùng cấu hình được công bố. Cleaning header/footer và
loại bỏ dữ liệu test thuộc quyết định dữ liệu riêng, không nằm trong candidate.
