# Audit & research: fullshot (so với GoFullPage)

Ngày: 2026-11-25 · Phiên bản: 0.1.0

## 1. GoFullPage hoạt động thế nào

**Bản mã nguồn mở gốc** ([mrcoles/full-page-screen-capture-chrome-extension](https://github.com/mrcoles/full-page-screen-capture-chrome-extension), giấy phép MIT, code từ năm 2012–2013) có các đặc điểm sau:

- Cuộn cả trang (`window.scrollTo`) theo từng khung màn hình. Mỗi bước chồng lên bước trước khoảng 200 px để xử lý header dính. Mỗi khung được chụp bằng `captureVisibleTab` rồi ghép lại trên canvas.
- Tỉ lệ pixel lấy từ kích thước ảnh chụp chia cho `innerWidth`. Ảnh đầu ra tính theo pixel thiết bị.
- Giới hạn canvas: cạnh dài 30.000 px, cạnh ngắn 8.000 px, tổng 240 triệu pixel. Trang vượt giới hạn bị cắt thành nhiều ảnh theo lưới **cố định**, không thông minh.
- **Không** xử lý khung cuộn bên trong, iframe hay phần tử fixed/sticky (header dính có thể bị lặp lại ở mỗi khung).
- **Không** có tính năng đóng dấu URL/ngày giờ. URL và thời điểm chỉ xuất hiện trong tên file.

Bản đang bán trên Chrome Web Store dùng một nhánh code riêng không công khai. Theo blog của họ:

- **Smart page splitting** (bản Premium): khi chia PDF thành trang, nó *"quét ngược lên từ mỗi chỗ ngắt trang để tìm điểm cắt sạch hơn"*. Mục đích chỉ là tránh cắt ngang dòng chữ, và nó *dễ lỗi khi gặp ảnh lớn nằm vắt qua chỗ ngắt*. Khổ giấy có: US Letter, Legal, A4, các bản Landscape, và Full Image.
- **Add URL and date/time** (bản Premium): đóng dấu URL và thời điểm chụp khi xuất PDF, với các định dạng Date, Date & Time, ISO hoặc None. Kiểu hiển thị gồm Mac OS X, Windows, URL on top, URL on bottom. Trong PDF, URL bấm được.

## 2. fullshot đã làm gì cho 2 tính năng này

| | GoFullPage | fullshot |
|---|---|---|
| Cách tìm điểm cắt | Chỉ dựa vào pixel | **Bố cục DOM** (hộp của từng dòng chữ, img/svg/video/canvas/pre/tr/figure/code…) cộng **pixel** làm phương án dự phòng |
| Ảnh lớn vắt qua chỗ ngắt | Dễ lỗi | Có chi phí riêng cho object. Nếu không tìm được chỗ sạch thì vẫn cắt gần mục tiêu, không bỏ trống nửa trang |
| Áp dụng cho | PDF | PDF **và** ảnh PNG/JPEG quá cao (khi cắt thành nhiều phần) |
| Tùy chỉnh | Bật/tắt | Bật/tắt, cộng `max_back` (được lùi lên tối đa bao nhiêu phần của một trang) |
| Kiểu đóng dấu | Mac / Windows / top / bottom | `browser` (khung trung tính, không bắt chước hệ điều hành nào) / `top` / `bottom` |
| Định dạng ngày | Date / Date & Time / ISO / None | Như GoFullPage, **cộng** mẫu strftime tùy ý, giờ địa phương kèm UTC offset, hoặc UTC |
| URL bấm được trong PDF | Có | Có |
| Metadata để làm bằng chứng | — | URL, tiêu đề và thời điểm nhúng vào PNG/JPEG/PDF, cộng file `.json` chứa SHA-256 của từng file |

Kết quả đo trên trang thật (khổ A4, viewport rộng 1280), tính số lần cắt ngang dòng chữ:

| Trang | Số trang PDF | Cắt cố định | Chỉ dùng pixel | DOM + pixel |
|---|---|---|---|---|
| docs.python.org/3/tutorial/classes.html | 10 | 7 | 2 | **0** |
| en.wikipedia.org/wiki/Screenshot | 3 | 1 | 2 | **0** |

## 3. Audit bảo mật (plugin cho agent)

Plugin này chạy trong agent, và agent có thể đọc nội dung không đáng tin (prompt injection), nên em rà theo hướng đó:

| Rủi ro | Xử lý |
|---|---|
| **SSRF**: agent bị dụ chụp `169.254.169.254`, `localhost:xxxx` hoặc dải mạng nội bộ | `FULLSHOT_BLOCK_PRIVATE=1` chặn cả URL ban đầu **lẫn** redirect và các request con (qua `page.route`). Biến này do người cài đặt, agent không tắt được qua tham số tool. Mặc định **tắt** để dev vẫn chụp được localhost. **Nên bật cho Hermes khi agent lướt web tự do.** |
| Đọc file cục bộ qua `file://` | Mặc định chặn. Phải đặt `FULLSHOT_ALLOW_FILE=1`. Agent không tự bật được. |
| `javascript:`, `data:` và các scheme khác | Bị từ chối. Chỉ cho http/https. |
| `cdp_url` trỏ tới máy khác (chiếm phiên trình duyệt từ xa) | Chỉ cho 127.0.0.1/localhost/::1. Muốn mở rộng phải đặt `FULLSHOT_ALLOW_REMOTE_CDP=1`. |
| Ghi đè file | Tên file luôn có timestamp và đuôi cố định (.png/.jpg/.pdf/.json). `output_dir` do agent chọn, nên vẫn ghi được vào bất kỳ thư mục nào agent có quyền. Đây là giới hạn đã biết. |
| Làm hỏng kênh MCP stdio | Mọi log và tiến trình `playwright install` đều chuyển sang stderr. |
| Trang lặp vô hạn hoặc treo | Giới hạn cao 60.000 CSS px, timeout điều hướng 45 giây, vòng cuộn lazy tối đa 20 giây. |
| Chuỗi cung ứng | Dùng các thư viện chính thống: playwright, pillow, reportlab (BSD), mcp. Tránh PyMuPDF vì giấy phép AGPL. Cài từ git có thể pin commit bằng `--ref <sha>` trong Hermes. |

## 4. Những gì đã kiểm chứng

- 16 unit test (splitter và các lớp bảo vệ): **pass**.
- Fixture bài báo dài (sticky header, banner cookie, ảnh): 12 trang A4. Đã xem bằng mắt: không cắt ngang chữ hay hình, header dính chỉ xuất hiện một lần, chỗ nối giữa các tile 4000 px không thấy vết.
- Fixture SPA (body không cuộn, khung `div` cuộn bên trong): chụp đủ 300 dòng đến "END OF LIST".
- Trang thật: Wikipedia, Hacker News, Python docs.
- MCP: client thật qua stdio, cả kiểu `python -m` lẫn đúng lệnh plugin (`uvx --from <root> fullshot-mcp`). Có 2 tool, trả về file kèm ảnh preview.
- Scale 2x, cắt ảnh thành nhiều phần (≤ 8000 px mỗi phần, đã tính cả thanh đóng dấu), khổ ngang, chụp theo selector, `--from-image`, và chặn SSRF.

## 5. Chưa kiểm chứng / giới hạn đã biết

- **Chưa cài thử trong Hermes thật**, vì máy này không có Hermes. Manifest viết theo spec Agent Plugins v1.0.0 và tài liệu Hermes, nhưng chưa chạy `hermes plugins validate`. Việc đầu tiên khi có Hermes là chạy `hermes plugins validate ./fullshot` và `hermes mcp test fullshot`.
- **Chưa cài thử qua `/plugin install` của Claude Code.** Lệnh khởi động MCP thì đã test.
- Mới test trên Windows. Font cho phần đóng dấu trên macOS/Linux có danh sách dự phòng nhưng chưa chạy thử.
- Đường dẫn dài trên Windows: nếu cài plugin vào một thư mục rất sâu thì `uv sync` có thể lỗi vượt 260 ký tự. Lệnh `uvx` mà plugin dùng cài vào cache của uv (đường dẫn ngắn) nên tránh được lỗi này, và đã test.
- Việc mở rộng khung cuộn bên trong là heuristic. Với vài layout lạ có thể làm vỡ bố cục, khi đó dùng `--no-expand`.
- iframe khác origin chạy ở process riêng có thể không mở rộng được. Khi đó nó được chụp đúng như đang hiển thị.
- Mỗi lần chụp mở một Chromium mới. Đơn giản và cô lập, nhưng chậm hơn tái sử dụng trình duyệt (khoảng 5–15 giây mỗi trang).
