"""
Elektrik fiyatlarını web scraping ile çeken servis
Türkiye (EPİAŞ) ve Romanya (OPCOM) için elektrik fiyatlarını otomatik olarak günceller
"""

import json
import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
import re
import time
import os

# Logging ayarları
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ElectricityPriceScraper:
    def __init__(self):
        self.prices_file = "./prices.json"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        # SSL sertifika doğrulamasını devre dışı bırak
        self.session.verify = False
        # SSL uyarılarını sustur
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
    def load_current_prices(self) -> Dict[str, Any]:
        """Mevcut fiyat dosyasını yükle"""
        try:
            if os.path.exists(self.prices_file):
                with open(self.prices_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                # Varsayılan fiyat yapısı
                return {
                    "TR": {
                        "base_price": 75.0,
                        "daily_pattern": {
                            "00": 0.85, "01": 0.80, "02": 0.78, "03": 0.76, "04": 0.75, "05": 0.77,
                            "06": 0.85, "07": 0.95, "08": 1.05, "09": 1.12, "10": 1.18, "11": 1.22,
                            "12": 1.25, "13": 1.23, "14": 1.20, "15": 1.18, "16": 1.15, "17": 1.12,
                            "18": 1.10, "19": 1.15, "20": 1.20, "21": 1.10, "22": 1.00, "23": 0.90
                        },
                        "weekly_multiplier": {
                            "monday": 1.05, "tuesday": 1.08, "wednesday": 1.12, "thursday": 1.10,
                            "friday": 1.15, "saturday": 0.95, "sunday": 0.85
                        }
                    },
                    "RO": {
                        "base_price": 82.0,
                        "daily_pattern": {
                            "00": 0.86, "01": 0.83, "02": 0.80, "03": 0.78, "04": 0.77, "05": 0.78,
                            "06": 0.84, "07": 0.94, "08": 1.01, "09": 1.06, "10": 1.09, "11": 1.12,
                            "12": 1.13, "13": 1.14, "14": 1.13, "15": 1.11, "16": 1.09, "17": 1.07,
                            "18": 1.06, "19": 1.08, "20": 1.11, "21": 1.06, "22": 0.97, "23": 0.88
                        },
                        "weekly_multiplier": {
                            "monday": 1.03, "tuesday": 1.06, "wednesday": 1.09, "thursday": 1.08,
                            "friday": 1.12, "saturday": 0.92, "sunday": 0.88
                        }
                    }
                }
        except Exception as e:
            logger.error(f"Fiyat dosyası yüklenirken hata: {e}")
            return {}

    def save_prices(self, prices: Dict[str, Any]) -> bool:
        """Fiyatları dosyaya kaydet"""
        try:
            with open(self.prices_file, 'w', encoding='utf-8') as f:
                json.dump(prices, f, indent=2, ensure_ascii=False)
            logger.info("Fiyatlar başarıyla kaydedildi")
            return True
        except Exception as e:
            logger.error(f"Fiyat kaydetme hatası: {e}")
            return False

    def scrape_turkey_prices(self) -> float:
        """Türkiye elektrik fiyatlarını Encazip.com'dan çek"""
        try:
            # Encazip.com elektrik fiyatları sayfası
            url = "https://www.encazip.com/elektrik-fiyatlari"
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Sayfa içeriğini al
            text_content = soup.get_text()
            
            # Mesken elektrik fiyatlarını bul
            # "2.5904TL/kWh" veya "3.6266TL/kWh" formatındaki fiyatları ara
            price_patterns = [
                r'(\d+[.,]\d+)TL/kWh',  # 2.5904TL/kWh formatı
                r'(\d+[.,]\d+)\s*TL/kWh',  # 2.5904 TL/kWh formatı
                r'fiyat[ı]?\s+(\d+[.,]\d+)\s*TL',  # "fiyatı 2.59 TL" formatı
                r'(\d+[.,]\d+)\s*TL.*kWh'  # "2.59 TL kWh" formatı
            ]
            
            found_prices = []
            
            for pattern in price_patterns:
                matches = re.findall(pattern, text_content, re.IGNORECASE)
                for match in matches:
                    try:
                        price = float(match.replace(',', '.'))
                        # Makul fiyat aralığı kontrolü (TL/kWh için)
                        if 1.0 <= price <= 10.0:
                            found_prices.append(price)
                    except ValueError:
                        continue
            
            if found_prices:
                # En yaygın fiyatı al (mesken için genellikle düşük kademe)
                avg_price = sum(found_prices) / len(found_prices)
                # kWh'den MWh'ye çevir (1 MWh = 1000 kWh)
                mwh_price = avg_price * 1000
                
                logger.info(f"Türkiye fiyatı güncellendi: {avg_price} TL/kWh ({mwh_price} TL/MWh)")
                logger.info(f"Bulunan fiyatlar: {found_prices}")
                return mwh_price
            
            # Alternatif: Spesifik metin arama
            # "3.11TL" gibi belirli fiyatları ara
            alt_patterns = [
                r'evler için.*?(\d+[.,]\d+)\s*TL',
                r'mesken.*?(\d+[.,]\d+)\s*TL',
                r'(\d+[.,]\d+)\s*TL.*evler'
            ]
            
            for pattern in alt_patterns:
                matches = re.findall(pattern, text_content, re.IGNORECASE)
                for match in matches:
                    try:
                        price = float(match.replace(',', '.'))
                        if 1.0 <= price <= 10.0:
                            mwh_price = price * 1000
                            logger.info(f"Türkiye fiyatı (alternatif) güncellendi: {price} TL/kWh ({mwh_price} TL/MWh)")
                            return mwh_price
                    except ValueError:
                        continue
                        
        except Exception as e:
            logger.error(f"Türkiye fiyat çekme hatası: {e}")
        
        return None

    def scrape_romania_prices(self) -> float:
        """Romanya elektrik fiyatlarını OPCOM'dan çek"""
        try:
            # OPCOM - Romanya Elektrik Piyasası
            url = "https://www.opcom.ro/pp/rapoarte/rapoarte_piata_pentru_ziua_urmatoare.php"
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Fiyat tablosunu bul
            tables = soup.find_all('table')
            
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        # RON/MWh formatındaki sayıları bul
                        price_match = re.search(r'(\d+[.,]\d+)', text)
                        if price_match:
                            price_str = price_match.group(1).replace(',', '.')
                            price = float(price_str)
                            if 200 <= price <= 600:  # RON için makul fiyat aralığı
                                logger.info(f"Romanya fiyatı güncellendi: {price} RON/MWh")
                                return price
                                
        except Exception as e:
            logger.error(f"Romanya fiyat çekme hatası: {e}")
        
        return None

    def update_prices(self) -> bool:
        """Elektrik fiyatlarını güncelle"""
        logger.info("Elektrik fiyatları güncelleniyor...")
        
        current_prices = self.load_current_prices()
        updated = False
        
        # Türkiye fiyatlarını güncelle
        tr_price = self.scrape_turkey_prices()
        if tr_price:
            current_prices["TR"]["base_price"] = tr_price
            updated = True
            
        # Romanya fiyatlarını güncelle
        ro_price = self.scrape_romania_prices()
        if ro_price:
            current_prices["RO"]["base_price"] = ro_price
            updated = True
        
        # Güncelleme zamanını ekle
        current_prices["last_updated"] = datetime.now().isoformat()
        
        if updated:
            success = self.save_prices(current_prices)
            if success:
                logger.info("Fiyat güncellemesi başarılı")
                return True
        else:
            logger.warning("Hiçbir fiyat güncellenemedi")
            
        return False

    def get_fallback_prices(self) -> Dict[str, float]:
        """Web scraping başarısız olursa kullanılacak yedek fiyatlar"""
        # Geçmiş verilere dayalı ortalama fiyatlar
        return {
            "TR": 85.0,  # TL/MWh
            "RO": 320.0  # RON/MWh
        }

    def update_with_fallback(self) -> bool:
        """Yedek fiyatlarla güncelle"""
        try:
            current_prices = self.load_current_prices()
            fallback_prices = self.get_fallback_prices()
            
            # Sadece çok eski fiyatları güncelle
            last_updated = current_prices.get("last_updated")
            if last_updated:
                last_update_time = datetime.fromisoformat(last_updated)
                if datetime.now() - last_update_time < timedelta(days=7):
                    logger.info("Mevcut fiyatlar yeterince güncel")
                    return False
            
            current_prices["TR"]["base_price"] = fallback_prices["TR"]
            current_prices["RO"]["base_price"] = fallback_prices["RO"]
            current_prices["last_updated"] = datetime.now().isoformat()
            current_prices["updated_with_fallback"] = True
            
            return self.save_prices(current_prices)
            
        except Exception as e:
            logger.error(f"Yedek fiyat güncelleme hatası: {e}")
            return False

# Scraper instance'ı
scraper = ElectricityPriceScraper()

def update_electricity_prices():
    """Elektrik fiyatlarını güncelleme fonksiyonu"""
    success = scraper.update_prices()
    if not success:
        logger.info("Web scraping başarısız, yedek fiyatlar deneniyor...")
        scraper.update_with_fallback()
    return success

if __name__ == "__main__":
    # Test için direkt çalıştırma
    update_electricity_prices()
