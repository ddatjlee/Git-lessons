import requests
from bs4 import BeautifulSoup
import base64
import re
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

DOCUMENT_LIST_URL = "https://document-mgmt.eton.vn/document-list"
OUTPUT_DIR = "label"

# Đảm bảo thư mục tồn tại
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Thiết lập Selenium
chrome_options = Options()
chrome_options.add_argument("--headless")
driver = webdriver.Chrome(options=chrome_options)

# Hàm lấy danh sách record từ trang đầu tiên
def get_document_list(seen_urls):
    response = requests.get(DOCUMENT_LIST_URL)
    if response.status_code != 200:
        print(f"Không thể truy cập trang {DOCUMENT_LIST_URL}: {response.status_code}")
        return []
    
    # Phân tích HTML
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if not table:
        print("Không tìm thấy bảng chứa danh sách record")
        return []
    
    records = []
    rows = table.find_all("tr")[1:]
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        
        title_col = cols[1]
        title = title_col.text.strip()
        
        template_code = cols[3].text.strip()     
        # Bỏ qua record có Template Code chứa "Invoice", "AllShippingLabelA7", hoặc "ExportDocumentReport", hoặc "ShippingLabelB2CA7"
        if "Invoice" in template_code or "AllShippingLabelA7" in template_code or "ExportDocumentReport" in template_code or "ShippingLabelB2CA7" in template_code:
            print(f"Bỏ qua record: {title} (Template Code: {template_code})")
            link = title_col.find("a")
            if link:
                detail_url = link["href"]
                if not detail_url.startswith("http"):
                    detail_url = f"https://document-mgmt.eton.vn{detail_url}"
                seen_urls.add(detail_url)
            continue
        
        link = title_col.find("a")
        if not link:
            continue
        detail_url = link["href"]
        if not detail_url.startswith("http"):
            detail_url = f"https://document-mgmt.eton.vn{detail_url}"
        
        time_created = cols[2].text.strip()
        
        # Chỉ thêm record nếu chưa thấy trước đó
        if detail_url not in seen_urls:
            records.append({
                "title": title,
                "detail_url": detail_url,
                "time_created": time_created
            })
    
    return records

# Hàm lấy base64 của hình ảnh từ trang chi tiết bằng Selenium
def get_image_base64(detail_url):
    try:
        driver.get(detail_url)
        time.sleep(2)
        
        img_elements = driver.find_elements(By.TAG_NAME, "img")
        if not img_elements:
            print(f"Không tìm thấy thẻ <img> trong {detail_url}")
            return None
        
        img_element = img_elements[0]
        img_src = img_element.get_attribute("src")
        if not img_src:
            print(f"Không tìm thấy thuộc tính src trong thẻ <img> tại {detail_url}")
            return None
        
        if img_src.startswith("data:image"):
            base64_str = img_src.split(",")[1]
            return base64_str
        
        if not img_src.startswith("http"):
            img_src = f"https://document-mgmt.eton.vn{img_src}"
        img_response = requests.get(img_src)
        if img_response.status_code != 200:
            print(f"Không thể tải hình ảnh từ {img_src}: {img_response.status_code}")
            return None
        
        base64_str = base64.b64encode(img_response.content).decode("utf-8")
        return base64_str
    
    except Exception as e:
        print(f"Lỗi khi lấy hình ảnh từ {detail_url}: {str(e)}")
        return None

def main():
    try:
        seen_urls = set()
        initial_records = get_document_list(seen_urls)
        for record in initial_records:
            seen_urls.add(record["detail_url"])
        
        while True:
            print("Kiểm tra record mới")
            records = get_document_list(seen_urls)
            
            for record in records:
                title = record["title"]
                detail_url = record["detail_url"]
                time_created = record["time_created"]
                
                image_base64 = get_image_base64(detail_url)
                if not image_base64:
                    print(f"Không thể lấy base64 cho record: {title}")
                    seen_urls.add(detail_url)
                    continue
                
                file_name = f"{time_created}_{title}".replace(":", "-")
                file_name = re.sub(r'[<>:"/\\|?*]', '_', file_name)
                file_name = f"{file_name}.txt"
                file_path = os.path.join(OUTPUT_DIR, file_name)
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(image_base64)
                print(f"Đã lưu base64 {file_path}")
                
                # Lưu detail_url đã xử lý
                seen_urls.add(detail_url)
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("Dừng script")
    
    finally:
        driver.quit()

if __name__ == "__main__":
    main()