# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng**, chỉ làm metric phụ (non-blocking), kèm rubric v1.1 bên dưới |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ, R dưới sàn; exit 1) | **loại** khỏi gate; phần "đúng số tiền" chuyển sang grader code |

Ma trận nhầm lẫn (FAIL = positive, vì việc của judge là *tìm* lỗi):

| | tp | fp | fn | tn | Tỉ lệ FAIL quan sát → Rogan-Gladen |
|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 → 0.30 (người: 30/100) |
| helpful | 9 | 0 | 21 | 70 | 0.09 → 0.30 (người: 30/100) |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách khiếu nại; judge coi suồng sã là thân thiện. Rubric: bắt buộc xưng "LogiX" / "anh/chị". |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Gọi khách là "bạn"; cùng lỗi xưng hô như #1. |
| 3 | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge bị "Dạ, vui lòng" ở đầu câu đánh lừa và bỏ qua giọng ra lệnh phía sau. Rubric: chấm cả câu, liệt kê cụm từ ra lệnh / gạt khách. |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi", nhưng rubric không yêu cầu xin lỗi khi yêu cầu đã được giải quyết. Rubric: ghi rõ xin lỗi là tùy chọn. |
| 5 | tone H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Style guide CS LogiX cho phép từ "refund"; judge phạt mọi từ tiếng Anh. Rubric: thêm whitelist thuật ngữ. |
| 6 | tone H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Câu lịch sự nhưng hứa ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải lỗi tone: không giao cho judge tone mà dùng grader code (reply ↔ ledger, như FM-08). |
| 7 | tone H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | Emoji cười trong ngữ cảnh khiếu nại. Rubric: cấm emoji trong reply CS. |
| 8 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Người đọc nhầm ticket. Sửa nhãn người ở lần gán nhãn sau; CSV công khai giữ nguyên vì test tham chiếu (κ = 0.757) dựa trên nó. |
| 9 | tone H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | Người (tạm) | Lặp "Dạ" do gõ nhầm, không phải thái độ. Rubric: lỗi gõ nhỏ không làm hỏng tone; nếu muốn bắt thì dùng lint code. |
| 10 | tone H-094 "Da, LogiX da hoan 40.000đ… xin loi vi su bat tien." | PASS | FAIL | Người | Mất dấu tiếng Việt, đọc như dịch máy. Rubric: thiếu dấu = FAIL; kiểm thêm bằng code (tỉ lệ ký tự có dấu). |
| 11 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." | PASS | FAIL | Người | Ledger ghi 40.000đ. Judge chỉ đọc reply, không có ledger nên không thể biết số sai. |
| 12 | helpful HL-016 (3 câu xin lỗi + "đã hoàn 55.000đ" cho O-404) | PASS | FAIL | Người | Ledger 35.000đ. Reply dài, nhiều xin lỗi và judge cho PASS: thiên vị độ dài/lịch sự. 13/18 FN sai số tiền có dạng này. |
| 13 | helpful HL-043 (xin lỗi dài + "đã hoàn 35.000đ" cho O-202) | PASS | FAIL | Người | Ledger 20.000đ: đúng mẫu FM-08 (misreport). |
| 14 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả hay số tiền, khách không biết bước tiếp theo. Rubric helpful phải bắt buộc nêu kết quả cụ thể (cùng mẫu: HL-091, HL-097). |
| 15 | helpful HL-020 "Dạ, LogiX đã hoàn 90.000đ cho đơn O-303 ạ." | PASS | FAIL | Người | Ledger 120.000đ (reply báo *thấp hơn*): judge sai theo cả hai chiều số tiền, nên không phải "judge khắt khe với số lớn". |

## Kết luận
- **Loại `helpful` khỏi gate.** Recall = 0.30: judge bỏ sót 21/30 reply mà người chấm FAIL (fn = 21, fp = 0). Precision = 1.0 trông đẹp nhưng chỉ vì judge hầu như không bao giờ nói FAIL: 9 lần FAIL đều là reply cụt rõ ràng ("Bạn gửi lại thông tin đi.", "Đơn … không được hoàn."). Trong 21 FN có 18 reply **nêu số tiền khác ledger**. Đây là thông tin judge không có trong input, nên sửa prompt cũng không cứu được. Kiểm tra này phải là grader code so số tiền trong reply với `snapshot.refund_vnd` (metric FM-08 ở M3). Gate dùng một judge như vậy sẽ cho qua đúng loại lỗi tốn tiền nhất.
- **Rogan-Gladen không cứu được `helpful`.** Tỉ lệ hiệu chỉnh 0.09 → 0.30 khớp tỉ lệ thật *trên tổng thể*, nhưng gate cần biết *item nào* fail để chạy paired bootstrap theo item. Với sensitivity 0.3, mỗi FAIL thật chỉ có 30% cơ hội bị thấy, và hệ số nhân 1/0.3 khuếch đại nhiễu lên ~3 lần.
- **`tone_ok` dùng được** (κ = 0.757 > 0.6) nhưng chỉ làm metric phụ, không blocking. 9/10 bất đồng là judge sai theo 3 kiểu có thể sửa bằng rubric: (a) bị cụm lịch sự bề mặt đánh lừa ("Dạ", "vui lòng") → bỏ sót xưng hô suồng sã, ra lệnh, emoji, mất dấu; (b) phạt sai thứ rubric không cấm (thiếu xin lỗi, từ "refund"); (c) chấm cả nội dung (hứa hoàn thêm), vốn là việc của grader code.
- **Rubric tone v1.1:** xưng "LogiX"/"anh/chị", cấm "em/bạn/nha"; cấm câu ra lệnh / gạt khách; cấm emoji; thiếu dấu tiếng Việt = FAIL; xin lỗi là tùy chọn; whitelist "refund, ship, voucher"; lỗi gõ lặp từ không tính; không chấm số tiền hay cam kết (đã có grader code). Sau khi sửa rubric phải calibrate lại trên nhãn mới.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí, 30 FAIL), nên khoảng tin cậy của κ còn rộng. Cần nhãn người mới (held-out, ≥2 người gán, đo κ giữa người với người) trước khi tin tone judge trên traffic thật. Nhãn H-081 sai cho thấy chính nhãn người cũng có nhiễu.
