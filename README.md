# BTVN — API Gateway với FastAPI

User Service (:8001), Order Service (:8002), API Gateway (:8000), MinIO (:9000; Console :9001).

## Khởi động

Yêu cầu Docker Desktop chạy Linux containers và Python 3.12/3.13. MinIO được build từ mã nguồn chính thức (tag cố định) vì image nhị phân cũ không còn truy cập được; lần build đầu cần Internet và có thể mất vài phút.

```powershell
Copy-Item .env.example .env
docker compose up -d --build
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Swagger tại http://localhost:8000/docs. MinIO Console tại http://localhost:9001, tài khoản trong `.env`. Bucket private `avatars` được tạo tự động; ảnh lưu trong Docker volume.

## JWT, routing và aggregation

Script offline cấp token demo; hệ thống thực tế cần nhà cung cấp danh tính có xác thực tài khoản.

```powershell
$env:JWT_SECRET = ((Get-Content .env | Where-Object { $_ -like 'JWT_SECRET=*' }) -split '=', 2)[1]
$token = .\.venv\Scripts\python scripts/issue_token.py --user-id 1
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://localhost:8000/users/1 -Headers $headers
Invoke-RestMethod http://localhost:8000/orders -Headers $headers
Invoke-RestMethod http://localhost:8000/dashboard -Headers $headers | ConvertTo-Json -Depth 6
```

`/users/me` cũng đọc hồ sơ. `/dashboard` gọi song song hai service và tổng hợp user, orders, order_count, total_amount. User 1 có 2 đơn, tổng 1.000.000; user 2 có 1 đơn, tổng 3.500.000. Gateway chỉ cho truy cập dữ liệu chủ JWT. `/orders` lấy ID từ token. JWT kiểm tra HS256, issuer, audience, subject, thời điểm cấp, hạn dùng. Token sai/thiếu/hết hạn trả 401; hồ sơ người khác trả 403; user không có trả 404. Lỗi upstream trả 502, timeout trả 504.

## Upload avatar (Valet Key)

```powershell
$grant = Invoke-RestMethod http://localhost:8000/users/me/avatar-upload-url `
  -Method Post -Headers $headers -ContentType 'application/json' `
  -Body '{"content_type":"image/png"}'
Invoke-WebRequest -Uri $grant.upload_url -Method Put -InFile 'C:\path\avatar.png' -ContentType 'image/png'
$grant.object_key
```

Thay đường dẫn ảnh bằng file thật. Client PUT trực tiếp vào MinIO; gateway chỉ cấp URL ký SigV4. URL giới hạn đúng object UUID dưới thư mục user, đúng Content-Type, **hết hạn sau 300 giây**. Kiểm tra object trong Console; dùng lại URL sau 5 phút sẽ bị từ chối. URL có thể dùng lại trước khi hết hạn. Content-Type được ký nhưng chưa kiểm tra byte ảnh hay giới hạn dung lượng. User/order là dữ liệu mẫu trong bộ nhớ; bài tập chưa cập nhật avatar vào hồ sơ.

`MINIO_PUBLIC_URL` phải là địa chỉ client truy cập được. Không thay hostname trong URL sau khi ký.

## Rate limit và đo độ trễ

Sliding window toàn gateway: tối đa **10 request trong bất kỳ 1 giây**, kể cả request lỗi và docs; `/health` miễn giới hạn. Vượt ngưỡng trả 429 và `Retry-After: 1`. Gửi 11 request đồng thời sau khi chờ cửa sổ cũ kết thúc để kiểm tra.

Chỉ chạy **1 worker/replica** vì bộ đếm ở bộ nhớ; cần Redis atomic khi scale. Cổng service bind loopback để đo trực tiếp, phải bỏ port mapping 8001/8002 khi triển khai để tránh bỏ qua gateway.

```powershell
.\.venv\Scripts\python scripts/benchmark.py --token $token --samples 50
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python scripts/check_live.py --token $token
```

Benchmark so cùng `GET /users/1` trực tiếp và qua gateway, có warm-up, đảo thứ tự mỗi vòng, nghỉ 150 ms để tránh rate limit. Xuất mean/median/p95, chênh lệch mean và mẫu gốc vào `benchmark.json`. Chi phí gateway gồm HTTP hop, JWT, xử lý proxy; kết quả phụ thuộc tải máy và có thể âm do nhiễu. Header `X-Gateway-Time-Ms` đo thời gian phía gateway; script đo round-trip phía client. Không so `/dashboard` với một request user vì khác công việc.

Lần đo thực tế trên máy local (50 mẫu, ba tiến trình Uvicorn, Docker đang build nền): mean trực tiếp 1,62 ms, qua gateway 5,43 ms, chênh lệch 3,81 ms. Đây là kết quả tham khảo có tải nền, không phải cam kết hiệu năng.

Test dùng mock HTTP kiểm tra routing, JWT, quyền truy cập, aggregation, rate limit, URL ký 300 giây và lỗi upstream; không thay thế kiểm thử MinIO thật.

Đã kiểm chứng: 5/5 test tự động pass trên Python 3.13; script live pass trên Docker cho dashboard, JWT, PUT ảnh vào MinIO, bucket private và giới hạn 10 request/giây. Script live dùng token user 1.

```powershell
docker compose ps
docker compose logs gateway
docker compose down
```

`/health` là liveness. Secret mẫu chỉ dành cho local; thay khi triển khai, dùng HTTPS và không commit `.env`.

Tham khảo: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Boto3 pre-signed URLs](https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html).
