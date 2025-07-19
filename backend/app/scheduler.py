"""
Zamanlanmış görevler için scheduler
Elektrik fiyatlarını düzenli olarak günceller
"""

import schedule
import time
import threading
import logging
from datetime import datetime
from .price_scraper import update_electricity_prices

logger = logging.getLogger(__name__)

class PriceUpdateScheduler:
    def __init__(self):
        self.running = False
        self.thread = None
        
    def start(self):
        """Scheduler'ı başlat"""
        if self.running:
            logger.info("Scheduler zaten çalışıyor")
            return
            
        self.running = True
        
        # Günlük saat 06:00'da fiyatları güncelle
        schedule.every().day.at("06:00").do(self._update_prices_job)
        
        # Haftalık Pazartesi 08:00'da fiyatları güncelle
        schedule.every().monday.at("08:00").do(self._update_prices_job)
        
        # İlk başlatmada bir kez çalıştır
        self._update_prices_job()
        
        # Arka planda çalışacak thread başlat
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        
        logger.info("Fiyat güncelleme scheduler'ı başlatıldı")
        
    def stop(self):
        """Scheduler'ı durdur"""
        self.running = False
        schedule.clear()
        logger.info("Fiyat güncelleme scheduler'ı durduruldu")
        
    def _update_prices_job(self):
        """Fiyat güncelleme görevi"""
        try:
            logger.info(f"Zamanlanmış fiyat güncellemesi başlatılıyor: {datetime.now()}")
            success = update_electricity_prices()
            if success:
                logger.info("Zamanlanmış fiyat güncellemesi başarılı")
            else:
                logger.warning("Zamanlanmış fiyat güncellemesi başarısız")
        except Exception as e:
            logger.error(f"Zamanlanmış fiyat güncelleme hatası: {e}")
            
    def _run_scheduler(self):
        """Scheduler'ı sürekli çalıştır"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Her dakika kontrol et
            except Exception as e:
                logger.error(f"Scheduler hatası: {e}")
                time.sleep(60)
                
    def force_update(self):
        """Manuel fiyat güncellemesi"""
        logger.info("Manuel fiyat güncellemesi tetiklendi")
        return self._update_prices_job()

# Global scheduler instance
price_scheduler = PriceUpdateScheduler()
