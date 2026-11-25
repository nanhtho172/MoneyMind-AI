# MoneyMind AI

MoneyMind AI là hệ thống AI Agent hỗ trợ quản lý tài chính cá nhân, cho phép theo dõi thu chi, quản lý ngân sách và tương tác với trợ lý tài chính bằng tiếng Việt. Hệ thống kết hợp dữ liệu tài chính của người dùng với kho kiến thức RAG để hỗ trợ truy vấn và trả lời có nguồn tham khảo.

## 1. Chức năng chính

- Tổng quan thu nhập, chi tiêu, dòng tiền ròng và cơ cấu chi tiêu theo danh mục.
- Quản lý giao dịch, thiết lập ngân sách và cảnh báo khi sử dụng từ 80% hoặc chạm 100% hạn mức.
- Trợ lý AI hỗ trợ truy vấn dữ liệu tài chính, tạo và chỉnh sửa bản nháp giao dịch hoặc ngân sách qua hội thoại. Thao tác ghi qua Agent yêu cầu xác nhận của người dùng.
- Kho tài liệu hỗ trợ PDF có lớp văn bản, DOCX, TXT và Markdown; tự động trích xuất, chia đoạn, lập chỉ mục và truy xuất nguồn kiến thức.
- Xác thực tài khoản, lưu lịch sử hội thoại, guardrails, theo dõi hoạt động hệ thống và đánh giá Agent.

## 2. Công nghệ và cấu trúc dự án

- Frontend: React, TypeScript, Vite, Tailwind CSS, shadcn/ui và Recharts
- Backend: Python, FastAPI, SQLAlchemy và SQLite
- AI Agent: LangGraph, Groq API, GPT-OSS, Financial Tools và cơ chế xác nhận trước khi ghi dữ liệu
- RAG: ChromaDB và Sentence Transformers
- Observability và Evals: log JSON, trace ID, tích hợp LangSmith tùy chọn và bộ đánh giá trong `evaluation/`

```text
MoneyMindAI/
├── backend/              # API, Agent, nghiệp vụ tài chính và RAG
├── web/                  # Giao diện React chính
├── frontend/             # Giao diện Streamlit dự phòng (bản base)
├── evaluation/           
├── scripts/              # Khởi tạo dữ liệu và công cụ vận hành
├── data/                 # Dữ liệu runtime tại máy local
├── .streamlit/           # Cấu hình giao diện dự phòng
├── .env.example          
├── requirements.txt      # Thư viện Python chính
├── requirements-rag.txt  # Thư viện xử lý tài liệu và RAG
└── README.md
```

## 3. Hướng dẫn cài đặt
Mở thư mục gốc của dự án trong VS Code và sử dụng terminal Windows PowerShell. Cần kết nối Internet khi cài thư viện, tải embedding model lần đầu và gọi Groq API.

### 3.1. Chuẩn bị môi trường

- Python: khuyến nghị Python 3.11, tải tại [python.org](https://www.python.org/downloads/). SQLite đi kèm Python cần từ phiên bản 3.35 trở lên.
- Node.js: bắt buộc để cài thư viện và chạy giao diện React trên máy local. Tải [Node.js LTS](https://nodejs.org/en/download/) (khuyến nghị dòng 22 LTS từ 22.12 trở lên). Chọn Windows Installer (`.msi`) phù hợp kiến trúc máy, giữ tùy chọn cài npm và thêm vào PATH.

Sau khi cài, đóng và mở lại VS Code hoặc terminal, rồi kiểm tra:

```powershell
python --version
node --version
npm --version
```


### 3.2. Cài đặt thư viện

Tại thư mục gốc dự án, tạo môi trường Python ảo và cài đặt các thư viện cần thiết:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-rag.txt
```

Cài thư viện React theo lockfile của dự án:

```powershell
cd web
npm ci
cd ..
```

Chỉ cần thực hiện các bước cài đặt khi thiết lập lần đầu hoặc khi thư viện cần thiết thay đổi.

### 3.3. Cấu hình môi trường

Tạo file `.env` từ cấu hình mẫu nếu chưa có:

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    $secret = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content .env -Raw).Replace('replace_with_random_secret', $secret) |
        Set-Content .env -Encoding ascii
    Remove-Variable secret
}
```

Giữ nguyên `AUTH_SECRET_KEY` của môi trường đang sử dụng; nếu vẫn là giá trị mẫu, thay bằng secret ngẫu nhiên đủ mạnh.

Tạo API key tại [GroqCloud](https://console.groq.com/keys), sau đó mở `.env` và cập nhật các biến:

```dotenv
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
LLM_REASONING_EFFORT=low
LLM_API_KEY=YOUR_GROQ_API_KEY
```

Thay `YOUR_GROQ_API_KEY` bằng API key của bạn. Không đưa file `.env` hoặc API key lên GitHub.

Mức suy luận của GPT-OSS được điều chỉnh thông qua `LLM_REASONING_EFFORT`:

| Giá trị | Mục đích |
|---|---|
| `low` | Phản hồi nhanh, phù hợp các thao tác thông thường và demo. |
| `medium` | Cân bằng giữa độ sâu suy luận và thời gian phản hồi. |
| `high` | Dành nhiều tài nguyên suy luận hơn cho yêu cầu phức tạp; có thể tăng độ trễ và lượng token. |

Có thể thay `LLM_MODEL` bằng model Groq tương thích với adapter và Structured Outputs hiện tại. Sau khi thay API key, model hoặc mức suy luận, khởi động lại Backend. Mức suy luận cao hơn không bảo đảm mọi câu trả lời đều chính xác hơn.

### 3.4. Khởi tạo dữ liệu và embedding model

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_demo
.\.venv\Scripts\python.exe -m scripts.ingest_knowledge --download-model
```

Lệnh thứ nhất tạo tài khoản và dữ liệu demo. Lệnh thứ hai chuẩn bị embedding model cho RAG; cần Internet nếu model chưa được lưu tại máy. Kho tài liệu ban đầu có thể trống và được bổ sung thông qua giao diện.

## 4. Khởi động ứng dụng

Khởi động Backend và React trong hai terminal riêng biệt. Đây là cách chạy chính thức của dự án

### Terminal 1 — Backend

Tại thư mục gốc:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### Terminal 2 — React Frontend

Mở terminal mới tại thư mục gốc:

```powershell
cd web
npm run dev
```

| Dịch vụ | Địa chỉ mặc định |
|---|---|
| MoneyMind AI | http://localhost:5173 |
| FastAPI Swagger | http://127.0.0.1:8000/docs |
| Backend health check | http://127.0.0.1:8000/health |

Giữ hai terminal hoạt động trong suốt quá trình sử dụng. React gọi API thông qua Vite proxy tới Backend ở cổng 8000.

**Tài khoản demo:** `demo_a` hoặc `demo_b`, mật khẩu `demo1234`. Các tài khoản này chỉ dành cho môi trường thử nghiệm local.

**Lưu ý:** Streamlit chỉ là giao diện base dự phòng, chưa được chỉnh sửa UI/UX như React. Nếu cần kiểm tra khi React gặp lỗi, giữ Backend đang chạy và thực thi `.\.venv\Scripts\python.exe -m streamlit run frontend/app.py` tại thư mục gốc.

## 5. Sử dụng trợ lý AI và RAG

- Tạo giao dịch trực tiếp tại trang Giao dịch hoặc nhập câu như `Hôm nay tôi ăn trưa hết 60 nghìn` trong Chat AI. Kiểm tra bản nháp trước khi xác nhận.
- Truy vấn số liệu bằng các câu hỏi như `Tổng thu và tổng chi tháng này là bao nhiêu?`.
- Để sử dụng RAG, mở Kho tài liệu, tải lên tài liệu phù hợp, chờ trạng thái `Đã sẵn sàng`, sau đó đặt câu hỏi về nội dung trong Chat AI. Nguồn tham khảo được hiển thị khi có kết quả truy xuất phù hợp.

Kho tài liệu được dùng chung giữa các tài khoản đăng nhập; giao dịch, ngân sách và hội thoại được phân tách theo tài khoản. Chỉ tải lên tài liệu được phép chia sẻ và xử lý qua nhà cung cấp AI. PDF scan cần được OCR trước khi tải lên.

## 6. Build, đánh giá và giám sát

Build giao diện React từ thư mục `web/`:

```powershell
npm run build
```

Chạy bộ đánh giá AI Agent từ thư mục gốc dự án:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_all
```

Hệ thống hỗ trợ:

- **Evals:** Đánh giá khả năng xử lý yêu cầu và sử dụng công cụ của AI Agent. Kết quả được lưu tại `evaluation/results/`. Các bộ đánh giá RAG cần sử dụng kho tài liệu tương ứng với dữ liệu tham chiếu.
- **Observability:** Theo dõi hoạt động của hệ thống thông qua JSON log và trace ID. Có thể tích hợp LangSmith thông qua các biến cấu hình tương ứng trong `.env.example`.

Dữ liệu ứng dụng, chỉ mục ChromaDB, tài liệu tải lên và file `.env` được lưu cục bộ, không đi kèm repository.