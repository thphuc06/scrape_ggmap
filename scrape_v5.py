# -*- coding: utf-8 -*-
"""
Google Maps Scraper V5 - With Opening Hours Fix
- Fix address extraction (loại bỏ rating, category lẫn vào)
- Tối ưu lấy phone, website
- NEW: Lấy opening_hours chi tiết từ T2-CN
- Clean output
"""
import os
import sys
import csv
import json
import time
import random
import urllib.parse
import re
from typing import Optional, List, Tuple
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from fuzzywuzzy import fuzz
from unidecode import unidecode

# Fix encoding on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')


def normalize_place_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower()
    name = unidecode(name)
    name = re.sub(r'\s*-\s*chi nhanh.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*-\s*branch.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^\w\s]', ' ', name)
    name = ' '.join(name.split())
    return name


def extract_name_from_google_maps_url(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        match = re.search(r'/place/([^/@]+)', url)
        if match:
            encoded_name = match.group(1)
            decoded_name = urllib.parse.unquote(encoded_name)
            decoded_name = decoded_name.replace('+', ' ')
            return decoded_name
    except:
        pass
    return None


def clean_address(addr: str) -> Optional[str]:
    """Clean địa chỉ - loại bỏ rating, category, directions bị lẫn vào"""
    if not addr or len(addr) < 5:
        return None
    
    # Pattern KHÔNG hợp lệ
    invalid_patterns = [
        r'\d+[,.]?\d*\s*\(\d',      # 4,1(903 - rating
        r'·',                        # Google separator
        r'Điểm thu hút',
        r'Điểm mốc',
        r'Đường đi',
        r'Mở cửa',
        r'Đóng cửa',
        r'Sắp đóng',
        r'Sắp mở',
        r'\bsao\b',
        r'\bstar\b',
        r'Khách sạn nghỉ',
        r'Bể bơi',
        r'Wi-Fi',
        r'Được tài trợ',
        r'Của Agoda',
        r'Booking\.com',
        r'Đại lý du lịch',
        r'Công viên xe',
        r'Phòng cho thuê',
    ]
    
    for pattern in invalid_patterns:
        if re.search(pattern, addr, re.IGNORECASE):
            return None
    
    addr = re.sub(r'\s+', ' ', addr).strip()
    
    # Validate
    valid_keywords = [
        'đường', 'phố', 'quận', 'huyện', 'tỉnh', 'thành phố', 'tp',
        'phường', 'xã', 'thị trấn', 'ấp', 'thôn', 'số', 'ngõ', 'ngách',
        'street', 'road', 'district', 'city', 'province', 'ward',
        'việt nam', 'vietnam', 'vn', 'khánh hòa', 'nha trang',
    ]
    
    addr_lower = addr.lower()
    has_valid = any(kw in addr_lower for kw in valid_keywords)
    has_number = bool(re.search(r'\d', addr))
    
    if has_valid or (has_number and len(addr) > 15):
        return addr
    
    return None


def clean_website_url(url: str) -> Optional[str]:
    if not url:
        return None
    
    if "google.com/url" in url and "?q=" in url:
        try:
            match = re.search(r'[?&]q=([^&]+)', url)
            if match:
                return urllib.parse.unquote(match.group(1))
        except:
            pass
    
    if "google.com/maps" in url:
        return None
    
    return url


class GoogleMapsScraper:
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None

    def init_driver(self):
        if self.driver:
            return

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument(f'--user-agent={random.choice(self.USER_AGENTS)}')
        chrome_options.add_argument('--lang=vi')
        chrome_options.add_experimental_option('prefs', {'intl.accept_languages': 'vi,en'})

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.set_page_load_timeout(30)
        print("[OK] WebDriver initialized")

    def _get_address(self) -> Optional[str]:
        """Lấy địa chỉ - CHỈ từ nguồn đáng tin"""
        
        # Strategy 1: data-item-id='address'
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, "button[data-item-id='address']")
            aria = btn.get_attribute("aria-label")
            if aria:
                addr = aria.replace("Địa chỉ: ", "").replace("Address: ", "").strip()
                cleaned = clean_address(addr)
                if cleaned:
                    return cleaned
        except:
            pass
        
        # Strategy 2: aria-label bắt đầu "Địa chỉ:"
        try:
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[aria-label]")
            for btn in buttons:
                aria = btn.get_attribute("aria-label") or ""
                if aria.startswith("Địa chỉ:") or aria.startswith("Address:"):
                    addr = aria.split(":", 1)[-1].strip()
                    cleaned = clean_address(addr)
                    if cleaned:
                        return cleaned
        except:
            pass
        
        # Strategy 3: Tìm div.Io6YTe trong button address
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            for btn in soup.find_all('button', attrs={'data-item-id': True}):
                if 'address' in btn.get('data-item-id', '').lower():
                    text_div = btn.find('div', class_=lambda x: x and 'Io6YTe' in str(x))
                    if text_div:
                        addr = text_div.get_text(strip=True)
                        cleaned = clean_address(addr)
                        if cleaned:
                            return cleaned
        except:
            pass
        
        return None

    def _get_phone(self) -> Optional[str]:
        try:
            btns = self.driver.find_elements(By.CSS_SELECTOR, "button[data-item-id^='phone:tel:']")
            for btn in btns:
                data_id = btn.get_attribute("data-item-id")
                if data_id and "phone:tel:" in data_id:
                    phone = data_id.replace("phone:tel:", "").strip()
                    if phone and len(phone) >= 8:
                        return phone
        except:
            pass
        
        try:
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[aria-label]")
            for btn in buttons:
                aria = btn.get_attribute("aria-label") or ""
                if "Điện thoại:" in aria or "Phone:" in aria:
                    match = re.search(r'[\d\s\-\+\(\)]{8,}', aria)
                    if match:
                        return match.group(0).strip()
        except:
            pass
        
        try:
            links = self.driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
            for link in links:
                href = link.get_attribute("href")
                if href:
                    phone = href.replace("tel:", "").strip()
                    if len(phone) >= 8:
                        return phone
        except:
            pass
        
        return None

    def _get_website(self) -> Optional[str]:
        raw_url = None
        
        try:
            links = self.driver.find_elements(By.CSS_SELECTOR, "a[data-item-id='authority']")
            if links:
                raw_url = links[0].get_attribute("href")
        except:
            pass
        
        if not raw_url:
            try:
                links = self.driver.find_elements(By.CSS_SELECTOR, "a[aria-label*='website'], a[aria-label*='Trang web']")
                for link in links:
                    href = link.get_attribute("href")
                    if href and not href.startswith("tel:"):
                        raw_url = href
                        break
            except:
                pass
        
        return clean_website_url(raw_url)

    def _get_price_level(self) -> Optional[str]:
        try:
            spans = self.driver.find_elements(By.CSS_SELECTOR, "span[aria-label*='Price'], span[aria-label*='Giá']")
            for span in spans:
                aria = span.get_attribute("aria-label") or ""
                if "đánh giá" in aria.lower():
                    continue
                if "Price:" in aria:
                    return aria.split("Price:")[-1].strip()
                if "Giá:" in aria:
                    return aria.split("Giá:")[-1].strip()
        except:
            pass
        
        try:
            spans = self.driver.find_elements(By.TAG_NAME, "span")
            for span in spans:
                text = span.text.strip()
                if re.match(r'^[\$₫]{1,4}$', text):
                    return text
        except:
            pass
        
        return None

    def _get_about(self) -> Optional[List[str]]:
        """
        Lấy About section - trả về list tất cả features
        Format: ["Có: Picnic tables", "Không: Wheelchair accessible entrance", ...]
        """
        features = []
        seen = set()
        
        try:
            # Click tab About/Giới thiệu
            tabs = self.driver.find_elements(By.CSS_SELECTOR, "button[role='tab']")
            clicked = False
            for tab in tabs:
                tab_text = tab.text.lower()
                if any(x in tab_text for x in ["about", "giới thiệu", "thông tin"]):
                    tab.click()
                    time.sleep(2.5)
                    clicked = True
                    break
            
            if not clicked:
                return None
            
            # Scroll nhiều lần để load hết content
            try:
                scrollables = self.driver.find_elements(By.CSS_SELECTOR, "div[role='main'], div.m6QErb")
                for scrollable in scrollables:
                    for _ in range(5):
                        self.driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', scrollable)
                        time.sleep(0.3)
            except:
                pass
            
            # Helper function để parse và add feature
            def add_feature(aria: str):
                if not aria or len(aria) < 3:
                    return
                
                if len(aria) > 100: return 

                feature = None
                
                if aria.startswith("Có: "):
                    feature = "Có: " + aria[4:].strip()
                elif aria.startswith("Không: "):
                    feature = "Không: " + aria[7:].strip()
                elif aria.startswith("Có "):
                    feature = "Có: " + aria[3:].strip()
                elif aria.startswith("Không "):
                    feature = "Không: " + aria[6:].strip()
                elif aria.startswith("Chấp nhận "):
                    feature = "Có: " + aria[10:].strip()
                elif aria.startswith("Phù hợp "):
                    feature = "Có: " + aria 
                elif aria.startswith("Thích hợp "):
                    feature = "Có: " + aria
                elif aria.startswith("Yes: "):
                    feature = "Có: " + aria[5:].strip()
                elif aria.startswith("No: "):
                    feature = "Không: " + aria[4:].strip()
                elif aria.startswith("Has "):
                    feature = "Có: " + aria[4:].strip()
                elif aria.startswith("Doesn't have "):
                    feature = "Không: " + aria[13:].strip()
                elif aria.startswith("No "):
                    feature = "Không: " + aria[3:].strip()
                elif aria.startswith("Accepts "):
                    feature = "Có: " + aria[8:].strip()
                elif aria.startswith("Good for "):
                    feature = "Có: " + aria
                elif aria.startswith("Picnic"): 
                    feature = "Có: " + aria
                elif aria.startswith("Wifi"):
                    feature = "Có: " + aria
                elif aria.startswith("Toilet"):
                    feature = "Có: " + aria
                elif aria.startswith("Restroom"):
                    feature = "Có: " + aria
                elif aria.startswith("Parking"):
                    feature = "Có: " + aria
                elif aria.startswith("Wheelchair"):
                    feature = "Có: " + aria

                if feature and feature not in seen and len(feature) > 5:
                    seen.add(feature)
                    features.append(feature)
            
            # Strategy 1: Selenium
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, "[aria-label]")
                for elem in elements:
                    try:
                        aria = elem.get_attribute("aria-label")
                        add_feature(aria)
                    except:
                        continue
            except:
                pass
            
            # Strategy 2: BeautifulSoup
            try:
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                
                for elem in soup.find_all(attrs={'aria-label': True}):
                    aria = elem.get('aria-label', '')
                    add_feature(aria)
                
                for li in soup.find_all('li'):
                    aria = li.get('aria-label', '')
                    if aria:
                        add_feature(aria)
                    for child in li.find_all(['span', 'div']):
                        aria = child.get('aria-label', '')
                        if aria:
                            add_feature(aria)
                
                for item in soup.find_all(attrs={'role': 'listitem'}):
                    aria = item.get('aria-label', '')
                    if aria:
                        add_feature(aria)
                    for child in item.find_all(attrs={'aria-label': True}):
                        add_feature(child.get('aria-label', ''))
                
                for img in soup.find_all('img', attrs={'aria-label': True}):
                    aria = img.get('aria-label', '')
                    add_feature(aria)
                    
            except:
                pass
            
            # Strategy 3: Tìm theo pattern class
            try:
                feature_divs = self.driver.find_elements(By.CSS_SELECTOR, "div[class*='iNvpkc'], li[class*='hpLkke']")
                for div in feature_divs:
                    try:
                        aria = div.get_attribute("aria-label")
                        if aria:
                            add_feature(aria)
                        children = div.find_elements(By.CSS_SELECTOR, "[aria-label]")
                        for child in children:
                            add_feature(child.get_attribute("aria-label"))
                    except:
                        continue
            except:
                pass
            
        except Exception as e:
            print(f"   [WARNING] About error: {e}")
        
        return features if features else None

    def _get_comments(self, num: int = 3) -> List[dict]:
        """
        Lấy comments với full text (click "Thêm" để expand)
        """
        comments = []
        try:
            # Click tab Reviews/Đánh giá
            tabs = self.driver.find_elements(By.CSS_SELECTOR, "button[role='tab']")
            for tab in tabs:
                if any(x in tab.text.lower() for x in ["đánh giá", "review"]):
                    tab.click()
                    time.sleep(1.5)
                    break
            
            # Scroll để load reviews
            try:
                scrollable = self.driver.find_element(By.CSS_SELECTOR, "div[role='main']")
                for _ in range(3):
                    self.driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', scrollable)
                    time.sleep(0.5)
            except:
                pass
            
            # === CLICK TẤT CẢ NÚT "THÊM" ĐỂ EXPAND COMMENT ===
            try:
                # Tìm tất cả button "Thêm" / "More" trong reviews
                more_buttons = self.driver.find_elements(By.CSS_SELECTOR, 
                    "button.w8nwRe.kyuRq, button[aria-label='Xem thêm'], button[jsaction*='review.expandReview']")
                
                for btn in more_buttons:
                    try:
                        # Chỉ click nếu button visible và có text "Thêm" hoặc "More"
                        if btn.is_displayed():
                            btn_text = btn.text.strip().lower()
                            if btn_text in ['thêm', 'more', 'see more', 'xem thêm']:
                                btn.click()
                                time.sleep(0.3)
                    except:
                        continue
                
                # Fallback: Tìm theo class w8nwRe (Google Maps dùng class này cho "Thêm")
                more_buttons2 = self.driver.find_elements(By.CSS_SELECTOR, "button.w8nwRe")
                for btn in more_buttons2:
                    try:
                        if btn.is_displayed() and btn.text.strip().lower() in ['thêm', 'more']:
                            btn.click()
                            time.sleep(0.3)
                    except:
                        continue
                        
            except Exception as e:
                print(f"   [WARNING] Click 'Thêm' error: {e}")
            
            # Đợi content expand
            time.sleep(0.5)
            
            # Parse reviews sau khi đã expand
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            review_divs = soup.find_all('div', {'data-review-id': True})
            
            seen = set()
            for div in review_divs:
                rid = div.get('data-review-id')
                if rid and rid not in seen:
                    seen.add(rid)
                    try:
                        # Author
                        author_elem = div.find('div', class_=lambda x: x and 'd4r55' in str(x))
                        author = author_elem.text.strip() if author_elem else "Anonymous"
                        
                        # Rating
                        rating_elem = div.find('span', {'role': 'img', 'aria-label': True})
                        rating_text = rating_elem.get('aria-label', '') if rating_elem else ''
                        rating_match = re.search(r'(\d+)', rating_text)
                        rating = float(rating_match.group(1)) if rating_match else 0.0
                        
                        # Text - lấy từ span.wiI7pd (đã được expand)
                        text_elem = div.find('span', class_=lambda x: x and 'wiI7pd' in str(x))
                        text = text_elem.text.strip() if text_elem else ""
                        
                        # Date
                        time_elem = div.find('span', class_=lambda x: x and 'rsqaWe' in str(x))
                        date = None
                        if time_elem:
                            time_text = time_elem.text.strip()
                            date = self._convert_relative_date(time_text)
                        
                        if text and len(text) > 5:
                            comments.append({
                                "author": author,
                                "rating": rating,
                                "text": text,
                                "date": date
                            })
                        
                        if len(comments) >= num:
                            break
                    except:
                        continue
        except:
            pass
        
        return comments
    
    def _convert_relative_date(self, relative_time: str) -> Optional[str]:
        """Convert '3 tháng trước' -> '03/09/2024'"""
        if not relative_time:
            return None
        
        from datetime import timedelta
        now = datetime.now()
        text = relative_time.lower()
        
        try:
            num_match = re.search(r'(\d+)', text)
            num = int(num_match.group(1)) if num_match else 1
            
            if any(x in text for x in ['day', 'ngày', 'ngay']):
                date = now - timedelta(days=num)
            elif any(x in text for x in ['week', 'tuần', 'tuan']):
                date = now - timedelta(weeks=num)
            elif any(x in text for x in ['month', 'tháng', 'thang']):
                date = now - timedelta(days=num * 30)
            elif any(x in text for x in ['year', 'năm', 'nam']):
                date = now - timedelta(days=num * 365)
            else:
                return None
            
            return date.strftime("%d/%m/%Y")
        except:
            return None

    def _get_hours(self) -> Optional[dict]:
        """
        Lấy opening hours từ T2 - CN
        
        Returns:
            dict: {"Thứ Hai": "08:00-17:00", ...} hoặc None
        """
        result = {}
        
        try:
            # Step 1: Click button giờ mở cửa để mở dropdown
            try:
                hour_btn = self.driver.find_element(By.CSS_SELECTOR, "button[data-item-id='oh']")
                if hour_btn.get_attribute("aria-expanded") != "true":
                    hour_btn.click()
                    time.sleep(1.2)
            except:
                # Fallback: tìm button có chứa text giờ
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[aria-label*='Đang mở'], button[aria-label*='Đã đóng']")
                    for btn in buttons:
                        btn.click()
                        time.sleep(1.2)
                        break
                except:
                    pass
            
            # Step 2: Parse table giờ mở cửa
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Tìm table chứa giờ (class eK4R0e)
            table = soup.find('table', class_=lambda x: x and 'eK4R0e' in str(x))
            
            if table:
                rows = table.find_all('tr', class_=lambda x: x and 'y0skZc' in str(x))
                
                for row in rows:
                    # Lấy tên ngày từ td.ylH6lf
                    day_td = row.find('td', class_=lambda x: x and 'ylH6lf' in str(x))
                    
                    # Lấy giờ từ td.mxowUb
                    time_td = row.find('td', class_=lambda x: x and 'mxowUb' in str(x))
                    
                    if day_td and time_td:
                        day_name = day_td.get_text(strip=True)
                        
                        # Ưu tiên lấy từ aria-label
                        hours_text = time_td.get('aria-label', '')
                        
                        # Fallback: lấy từ li.G8aQO
                        if not hours_text:
                            li = time_td.find('li', class_=lambda x: x and 'G8aQO' in str(x))
                            if li:
                                hours_text = li.get_text(strip=True)
                        
                        # Fallback: lấy text trực tiếp
                        if not hours_text:
                            hours_text = time_td.get_text(strip=True)
                        
                        if day_name and hours_text:
                            # Clean format: "08:00 đến 17:00" -> "08:00-17:00"
                            hours_text = hours_text.replace(' đến ', '-').replace('đến', '-')
                            hours_text = hours_text.replace('–', '-')  # en-dash -> hyphen
                            result[day_name] = hours_text
            
            # Step 3: Fallback - Selenium trực tiếp nếu BeautifulSoup fail
            if not result:
                try:
                    rows = self.driver.find_elements(By.CSS_SELECTOR, "table.eK4R0e tr.y0skZc")
                    for row in rows:
                        day_td = row.find_element(By.CSS_SELECTOR, "td.ylH6lf")
                        time_td = row.find_element(By.CSS_SELECTOR, "td.mxowUb")
                        
                        day_name = day_td.text.strip()
                        hours_text = time_td.get_attribute("aria-label") or time_td.text.strip()
                        hours_text = hours_text.replace(' đến ', '-').replace('đến', '-').replace('–', '-')
                        
                        if day_name and hours_text:
                            result[day_name] = hours_text
                except:
                    pass
                    
        except Exception as e:
            print(f"   [WARNING] Hours error: {e}")
        
        return result if result else None

    def _get_images(self) -> List[str]:
        images = []
        try:
            tabs = self.driver.find_elements(By.CSS_SELECTOR, "button[role='tab']")
            for tab in tabs:
                if any(x in tab.text.lower() for x in ["photo", "hình", "ảnh"]):
                    tab.click()
                    time.sleep(1.5)
                    break
            
            for _ in range(2):
                self.driver.execute_script("window.scrollBy(0, 300)")
                time.sleep(0.3)
            
            imgs = self.driver.find_elements(By.TAG_NAME, "img")
            seen = set()
            
            for img in imgs:
                try:
                    src = img.get_attribute("src")
                    if src and ("googleusercontent.com" in src or "ggpht.com" in src) and "=w" in src:
                        if any(x in src for x in ["=w30", "=w48", "=w24", "=w32", "=w64", "=w36"]):
                            continue
                        
                        match = re.search(r'=w(\d+)', src)
                        if match and int(match.group(1)) >= 100:
                            base = src.split('=w')[0]
                            if base not in seen:
                                seen.add(base)
                                images.append(src)
                                if len(images) >= 3:
                                    break
                except:
                    continue
        except:
            pass
        
        return images

    def _get_rating(self) -> Tuple[Optional[float], Optional[int]]:
        rating = None
        count = None
        
        try:
            elem = self.driver.find_element(By.CSS_SELECTOR, "span[aria-label*='sao']")
            text = elem.get_attribute("aria-label")
            m = re.search(r'(\d+[,.]?\d*)\s*sao', text)
            if m:
                rating = float(m.group(1).replace(',', '.'))
            m = re.search(r'(\d+[\.,]?\d*)\s*đánh giá', text)
            if m:
                count = int(m.group(1).replace('.', '').replace(',', ''))
        except:
            pass
        
        if rating is None:
            try:
                elem = self.driver.find_element(By.CSS_SELECTOR, "span[aria-label*='star']")
                text = elem.get_attribute("aria-label")
                m = re.search(r'(\d+[,.]?\d*)\s*star', text)
                if m:
                    rating = float(m.group(1).replace(',', '.'))
                m = re.search(r'(\d+[\.,]?\d*)\s*review', text)
                if m:
                    count = int(m.group(1).replace('.', '').replace(',', ''))
            except:
                pass
        
        if rating is None:
            try:
                divs = self.driver.find_elements(By.CSS_SELECTOR, "div.fontDisplayLarge")
                for div in divs:
                    text = div.text.strip()
                    if re.match(r'^\d+[,.]?\d*$', text):
                        val = float(text.replace(',', '.'))
                        if 1.0 <= val <= 5.0:
                            rating = val
                            break
            except:
                pass
        
        if count is None:
            try:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in buttons:
                    m = re.search(r'\((\d{1,3}(?:[,\.]\d{3})*)\)', btn.text)
                    if m:
                        count = int(m.group(1).replace(',', '').replace('.', ''))
                        break
            except:
                pass
        
        return rating, count

    def _get_category(self) -> Optional[str]:
        try:
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[jsaction*='category']")
            for btn in buttons:
                text = btn.text.strip()
                if text and 3 < len(text) < 50:
                    return text
        except:
            pass
        
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, "button.DkEaL")
            return btn.text.strip()
        except:
            pass
        
        return None

    def scrape_place(self, name: str, address: str, lat: float, lon: float, num_reviews: int = 3) -> dict:
        if not self.driver:
            self.init_driver()

        result = {
            "name": name,
            "original_address": address,
            "new_address": None,
            "lat": lat,
            "lon": lon,
            "category": None,
            "about": None,
            "rating": None,
            "rating_count": None,
            "price_level": None,
            "images": [],
            "phone": None,
            "website": None,
            "google_maps_url": None,
            "opening_hours": None,
            "comments": [],
        }

        try:
            query = urllib.parse.quote(address)
            url = f"https://www.google.com/maps/search/{query}"

            print(f"   [SEARCH] {address[:50]}...")
            self.driver.get(url)
            time.sleep(4)

            current_url = self.driver.current_url
            result["google_maps_url"] = current_url

            # Handle chain/search
            if "/search/" in current_url or not re.search(r'/place/[^/]+/@', current_url):
                try:
                    wait = WebDriverWait(self.driver, 5)
                    links = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[href*='/place/']")))

                    if links:
                        best_score = 0
                        best_link = None
                        query_norm = normalize_place_name(name)

                        for link in links[:10]:
                            try:
                                href = link.get_attribute("href")
                                cand = extract_name_from_google_maps_url(href)
                                if cand:
                                    cand_norm = normalize_place_name(cand)
                                    score = max(fuzz.ratio(query_norm, cand_norm), fuzz.token_set_ratio(query_norm, cand_norm))
                                    if score > best_score:
                                        best_score = score
                                        best_link = link
                            except:
                                continue

                        if best_link and best_score >= 50:
                            best_link.click()
                            time.sleep(2.5)
                            result["google_maps_url"] = self.driver.current_url
                        elif links:
                            links[0].click()
                            time.sleep(2.5)
                            result["google_maps_url"] = self.driver.current_url
                except:
                    pass

            # === SCRAPE DATA TỪ TRANG CHÍNH ===
            
            rating, count = self._get_rating()
            result["rating"] = rating
            result["rating_count"] = count
            if rating:
                print(f"   [OK] Rating: {rating} ({count} reviews)")
            
            result["category"] = self._get_category()
            if result["category"]:
                print(f"   [OK] Category: {result['category']}")
            
            result["price_level"] = self._get_price_level()
            
            result["new_address"] = self._get_address()
            if result["new_address"]:
                print(f"   [OK] Address: {result['new_address'][:40]}...")
            
            result["phone"] = self._get_phone()
            if result["phone"]:
                print(f"   [OK] Phone: {result['phone']}")
            
            result["website"] = self._get_website()
            if result["website"]:
                print(f"   [OK] Website")
            
            # Opening hours - NEW!
            result["opening_hours"] = self._get_hours()
            if result["opening_hours"]:
                print(f"   [OK] Hours: {len(result['opening_hours'])} days")
            
            # === SCRAPE DATA TỪ TABS ===
            
            result["images"] = self._get_images()
            print(f"   [OK] Images: {len(result['images'])}")
            
            result["about"] = self._get_about()
            if result["about"]:
                print(f"   [OK] About: {len(result['about'])} features")
            
            result["comments"] = self._get_comments(num_reviews)
            print(f"   [OK] Comments: {len(result['comments'])}")

        except Exception as e:
            print(f"   [ERROR] {e}")

        return result

    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None


def scrape_csv_file(csv_file: str, output_file: str = None, headless: bool = True,
                    start_index: int = 0, end_index: int = None) -> List[dict]:
    if output_file is None:
        name = os.path.splitext(os.path.basename(csv_file))[0]
        if end_index is not None:
            output_file = os.path.join(os.path.dirname(csv_file), f"{name}_scraped_{start_index}_{end_index}.json")
        elif start_index > 0:
            output_file = os.path.join(os.path.dirname(csv_file), f"{name}_scraped_from_{start_index}.json")
        else:
            output_file = os.path.join(os.path.dirname(csv_file), f"{name}_scraped.json")

    print("=" * 70)
    print("GOOGLE MAPS SCRAPER V5 - WITH OPENING HOURS")
    print("=" * 70)
    print(f"Input: {csv_file}")
    print(f"Output: {output_file}")
    print(f"Range: {start_index} -> {end_index or 'END'}")
    print("=" * 70)

    places = []
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            places.append({
                'place_id': row['place_id'],
                'name': row['name'],
                'address': row['address'],
                'lat': float(row['lat']),
                'lon': float(row['lon']),
                'type': row['type']
            })

    if end_index is not None:
        places = places[start_index:end_index]
    else:
        places = places[start_index:]

    print(f"[OK] Loaded {len(places)} places\n")

    scraper = GoogleMapsScraper(headless=headless)
    data = []

    try:
        for i, p in enumerate(places, 1):
            print(f"\n[{start_index + i}/{start_index + len(places)}] {p['name']}")
            print("-" * 50)

            try:
                result = scraper.scrape_place(p['name'], p['address'], p['lat'], p['lon'])
                result['place_id'] = p['place_id']
                result['type'] = p['type']
                result['scraped_at'] = datetime.now().isoformat()
                data.append(result)

                if i % 10 == 0:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"\n[SAVE] {len(data)} places")
            except Exception as e:
                print(f"[ERROR] {e}")
                continue

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\n[SUCCESS] {len(data)}/{len(places)} places")
        print(f"Output: {output_file}")

        return data
    finally:
        scraper.close()


def merge_files(directory: str, output: str = None, pattern: str = "*_scraped_*.json"):
    import glob
    
    files = glob.glob(os.path.join(directory, pattern))
    if not files:
        print(f"No files found")
        return
    
    all_data = []
    for f in sorted(files):
        with open(f, 'r', encoding='utf-8') as file:
            all_data.extend(json.load(file))
            print(f"  {os.path.basename(f)}: {len(json.load(open(f, encoding='utf-8')))}")
    
    seen = set()
    unique = [x for x in all_data if x.get('place_id') not in seen and not seen.add(x.get('place_id'))]
    
    if output is None:
        output = os.path.join(directory, "merged.json")
    
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    
    print(f"\nMerged {len(unique)} places -> {output}")


def main():
    import sys
    
    csv_file = r"C:\HCMUS\ComputationalThinking\track-asia\test_museum.csv"  # CHANGE THIS
    
    if len(sys.argv) >= 2 and sys.argv[1] == 'merge':
        merge_files(sys.argv[2] if len(sys.argv) >= 3 else os.path.dirname(csv_file))
    elif len(sys.argv) >= 3:
        scrape_csv_file(csv_file, headless=True, start_index=int(sys.argv[1]), end_index=int(sys.argv[2]))
    elif len(sys.argv) == 2:
        scrape_csv_file(csv_file, headless=True, start_index=0, end_index=int(sys.argv[1]))
    else:
        scrape_csv_file(csv_file, headless=True)


if __name__ == "__main__":
    main()