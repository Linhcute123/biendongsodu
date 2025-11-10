# Bot Thông Báo Saldo (Phiên bản Vũ Trụ)

Đây là hướng dẫn cập nhật để deploy bot lên Render, bao gồm cả việc **lưu trữ dữ liệu vĩnh viễn** và **chạy 24/7** trên gói Free.

## Chuẩn Bị

Bạn cần chuẩn bị 3 thông tin:
1.  **Telegram Bot Token** (Lấy từ `@BotFather`)
2.  **Telegram Chat ID** (Lấy từ `@userinfobot`)
3.  **Mật Khẩu Admin** (Bạn tự nghĩ ra)

## Hướng Dẫn Deploy Lên Render

1.  **Tạo Repository GitHub:**
    * Tạo một repository **Private** (Riêng tư) mới trên GitHub.
    * Upload 3 file `app.py`, `requirements.txt` và `README.md` vào repository.

2.  **Tạo Web Service trên Render:**
    * Trên Dashboard của Render, chọn **New +** -> **Web Service**.
    * Kết nối tài khoản GitHub và chọn repository của bạn.

3.  **Thêm Đĩa Lưu Tr trữ (BƯỚC QUAN TRỌNG NHẤT):**
    * Trước khi deploy, hãy vào dịch vụ của bạn.
    * Trong menu bên trái, chọn **Disks**.
    * Click **New Disk**.
    * **Name:** `data`
    * **Mount Path:** `/data` (BẮT BUỘC ĐIỀN CHÍNH XÁC NHƯ VẬY)
    * **Size:** `1 GB` (là đủ).
    * Click **Create Disk**.
    * **Lưu ý:** Việc thêm Disk này là **miễn phí**.

4.  **Cấu Hình Dịch Vụ:**
    * **Name:** `saldo-bot`
    * **Region:** `Singapore`
    * **Branch:** `main`
    * **Build Command:** `pip install -r requirements.txt`
    * **Start Command:** `python app.py`

5.  **Thêm Biến Môi Trường:**
    * Kéo xuống mục **Environment** -> **Add Environment Variable**.
    * Thêm 2 biến sau:
        * **Key:** `ADMIN_PASSWORD`
          **Value:** `matkhauradenho123` (Mật khẩu của bạn)
        * **Key:** `PYTHON_VERSION`
          **Value:** `3.10` (hoặc 3.11, 3.12)

6.  **Deploy:**
    * Click **Create Web Service**.
    * Đợi vài phút để Render build và chạy.

## LÀM SAO ĐỂ BOT CHẠY 24/7 (Không bị "Ngủ")

Gói Free của Render sẽ tự động "ngủ" (tắt máy chủ) sau 15 phút không có ai truy cập.

**Giải pháp:** Dùng một dịch vụ bên ngoài để "ping" vào web của bạn 5 phút một lần.

1.  **Lấy URL Web của bạn:**
    * Sau khi deploy thành công, Render sẽ cho bạn 1 URL, ví dụ: `https://saldo-bot.onrender.com`

2.  **Sử dụng Dịch Vụ Cron Job (Miễn phí):**
    * Đăng ký một tài khoản tại [https://cron-job.org/](https://cron-job.org/).
    * Tạo một "Cronjob" mới.
    * **Title:** `Đánh thức Bot Render`
    * **URL:** Dán URL của bạn vào (ví dụ: `https://saldo-bot.onrender.com`)
    * **Schedule (Lịch chạy):** Chọn "Every 5 minutes" (Mỗi 5 phút).
    * Bấm **Create**.

Xong! Dịch vụ này sẽ giữ cho bot của bạn luôn "thức" và chạy 24/7.
