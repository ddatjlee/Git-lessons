import requests
import os
import json
import logging
import glob
import time
import re
from queue import Queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Thiết lập logging để hiển thị trên terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Đường dẫn thư mục
LABEL_DIR = "label"
OUTPUT_DIR = "Output"
PROCESSED_DIR = "label_processed"  # Thư mục lưu trữ file đã xử lý

# Đảm bảo các thư mục tồn tại
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
if not os.path.exists(PROCESSED_DIR):
    os.makedirs(PROCESSED_DIR)

# URL API Gemini
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=AIzaSyAijRlcEXfQLWGI_NDWWghCktcErNc3l0Q"

# Prompt để gửi đến Gemini
PROMPT = """
You are an AI assistant specialized in analyzing shipping labels from various courier services.

Please extract the following key information from the label and return it in proper JSON format:
1. tracking_number – The shipment tracking number (usually a long alphanumeric string like SPXVN056647140793 or 851485198118).
2. order_id – The customer’s order ID (usually labeled as "Order ID", "Mã đơn hàng", etc.).
3. sender_address – The sender’s address (often appears after keywords like "From", "Từ", or "Sender").
4. recipient_address – The receiver’s address (often appears after keywords like "To", "Đến", or "Receiver").

If any information is missing or unclear, use the value "Not found".

Respond with a valid and clean JSON object only, with no additional text.

Example format:
{
  "tracking_number": "...",
  "order_id": "...",
  "sender_address": "...",
  "recipient_address": "..."
}
"""

# Hàng đợi để lưu các file mới
file_queue = Queue()

# Hàm trích xuất JSON từ khối Markdown
def extract_json_from_markdown(text):
    try:
        match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if not match:
            logging.error(f"Không tìm thấy khối JSON trong Markdown: {text}")
            return None
        
        json_str = match.group(1).strip()
        json_result = json.loads(json_str)
        return json_result
    except json.JSONDecodeError as e:
        logging.error(f"Không thể phân tích JSON từ Markdown: {text}")
        logging.error(f"Lỗi phân tích JSON: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Lỗi khi trích xuất JSON từ Markdown: {str(e)}")
        return None

# Hàm gửi yêu cầu đến API Gemini
def call_gemini_api(base64_string):
    try:
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64_string
                            }
                        }
                    ]
                }
            ]
        }

        response = requests.post(GEMINI_API_URL, json=payload)
        if response.status_code != 200:
            logging.error(f"Lỗi từ API Gemini: {response.status_code} - {response.text}")
            return None

        result = response.json()
        logging.info(f"Phản hồi từ API Gemini: {json.dumps(result, indent=2)}")

        if "candidates" not in result or not result["candidates"]:
            logging.error(f"Phản hồi không hợp lệ từ API Gemini: {result}")
            return None

        content = result["candidates"][0]["content"]["parts"][0]["text"]
        json_result = extract_json_from_markdown(content)
        return json_result

    except Exception as e:
        logging.error(f"Lỗi khi gọi API Gemini: {str(e)}")
        return None

# Class xử lý sự kiện khi có file mới trong thư mục
class LabelFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".txt"):
            logging.info(f"Phát hiện file mới: {event.src_path}")
            file_queue.put(event.src_path)

# Hàm xử lý file từ hàng đợi
def process_files():
    while True:
        if file_queue.empty():
            time.sleep(1)  # Chờ 1 giây nếu không có file mới
            continue

        label_file = file_queue.get()
        file_name = os.path.basename(label_file)

        try:
            # Đọc nội dung base64 từ file
            with open(label_file, "r", encoding="utf-8") as f:
                base64_string = f.read().strip()

            # Gửi yêu cầu đến API Gemini
            logging.info(f"Xử lý file: {label_file}")
            result = call_gemini_api(base64_string)
            if not result:
                logging.error(f"Không thể lấy kết quả từ API Gemini cho file {label_file}")
                continue

            # Trích xuất tracking_number từ kết quả JSON
            tracking_number = result.get("tracking_number", "Not found")
            if tracking_number == "Not found":
                logging.error(f"Không tìm thấy tracking_number trong kết quả của file {label_file}")
                continue

            # Lưu kết quả JSON vào thư mục Output
            output_file = os.path.join(OUTPUT_DIR, f"{tracking_number}.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logging.info(f"Đã lưu kết quả vào file: {output_file}")

            # Di chuyển file gốc sang thư mục label_processed
            processed_file = os.path.join(PROCESSED_DIR, file_name)
            os.rename(label_file, processed_file)
            logging.info(f"Đã di chuyển file gốc sang: {processed_file}")

        except Exception as e:
            logging.error(f"Lỗi khi xử lý file {label_file}: {str(e)}")

# Hàm chính
def main():
    try:
        logging.info("Bắt đầu chạy script label-extract...")

        # Khởi tạo observer để theo dõi thư mục label
        event_handler = LabelFileHandler()
        observer = Observer()
        observer.schedule(event_handler, LABEL_DIR, recursive=False)
        observer.start()
        logging.info("Bắt đầu theo dõi thư mục label...")

        # Xử lý các file hiện có trong thư mục label
        label_files = glob.glob(os.path.join(LABEL_DIR, "*.txt"))
        for label_file in label_files:
            file_queue.put(label_file)

        # Xử lý file từ hàng đợi
        process_files()

    except KeyboardInterrupt:
        logging.info("Dừng script bởi người dùng.")
        observer.stop()
    except Exception as e:
        logging.error(f"Lỗi trong quá trình chạy script: {str(e)}")
        observer.stop()

    observer.join()

if __name__ == "__main__":
    main()