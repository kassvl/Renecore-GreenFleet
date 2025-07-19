import os
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlmodel import Session, SQLModel, create_engine
from pydantic import BaseModel

from .models import Site, BatteryConfig, create_db_and_tables, get_engine
from .crud import (
    get_sites, get_site, create_site, update_site, 
    get_forecast, create_or_update_battery_config, get_battery_config
)
from .services import fetch_forecast, calc_power, calc_revenue, calc_co2, battery_dispatch
from .tasks import start_background_tasks  # , generate_pdf_report
from .ml_service import train_model, predict_next_week
from .scheduler import price_scheduler
from .price_scraper import update_electricity_prices

# Uluslararasılaştırma için metin sözlüğü
TEXTS = {
    "tr": {
        "welcome": "Renecore-GreenFleet API'sine Hoş Geldiniz",
        "site_not_found": "Saha bulunamadı",
        "invalid_type": "Geçersiz tahmin türü",
    },
    "en": {
        "welcome": "Welcome to Renecore-GreenFleet API",
        "site_not_found": "Site not found",
        "invalid_type": "Invalid forecast type",
    }
}

# Veritabanı bağlantısı
def get_db():
    engine = get_engine()
    with Session(engine) as session:
        yield session


# FastAPI uygulama yaşam döngüsü
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Başlangıçta veritabanı tablolarını oluştur
    create_db_and_tables()
    
    # Arka plan görevlerini başlat
    background_tasks = BackgroundTasks()
    start_background_tasks(background_tasks, get_db)
    
    # Elektrik fiyatı scheduler'ını başlat
    price_scheduler.start()
    
    yield
    
    # Uygulama kapanırken yapılacak işlemler
    price_scheduler.stop()


# FastAPI uygulaması oluştur
app = FastAPI(
    title="Renecore-GreenFleet API",
    description="Real-time renewable energy forecasting and revenue dashboard",
    version="1.0.0",
    lifespan=lifespan
)

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Geliştirme için tüm kaynaklara izin ver
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Veri modelleri
class SiteCreate(BaseModel):
    name: str
    country: str
    capacity_mw: float
    site_type: str
    latitude: float
    longitude: float


class SiteResponse(BaseModel):
    id: int
    name: str
    country: str
    capacity_mw: float
    site_type: str
    latitude: float
    longitude: float


class BatteryConfigCreate(BaseModel):
    capacity_mwh: float = 4.0
    power_mw: float = 1.0
    initial_soc: float = 0.5


# API rotaları
@app.get("/")
async def root():
    return {"message": TEXTS["en"]["welcome"]}


@app.get("/api/sites", response_model=List[SiteResponse])
async def read_sites(db: Session = Depends(get_db)):
    """Tüm sahaları listeler."""
    return await get_sites(db)


@app.post("/api/sites", response_model=SiteResponse)
async def create_new_site(site: SiteCreate, db: Session = Depends(get_db)):
    """Yeni bir saha oluşturur."""
    return await create_site(db, site.dict())


@app.get("/api/sites/{site_id}", response_model=SiteResponse)
async def read_site(site_id: int, db: Session = Depends(get_db)):
    """Belirli bir sahayı gösterir."""
    return await get_site(db, site_id)


@app.get("/api/forecast/{site_id}")
async def read_forecast(
    site_id: int, 
    type: str = Query(..., description="Forecast type: 'wind' or 'solar'"),
    battery: bool = Query(False, description="Include battery simulation"),
    db: Session = Depends(get_db)
):
    """Belirli bir saha için tahmin verilerini döndürür."""
    # Sahayı kontrol et
    site = await get_site(db, site_id)
    
    # Tahmin türünü kontrol et
    if type not in ["wind", "solar"]:
        raise HTTPException(status_code=400, detail=TEXTS["en"]["invalid_type"])
    
    # Veritabanından tahminleri al
    forecasts = await get_forecast(db, site_id)
    
    # Tahmin yoksa veya güncel değilse yeniden hesapla
    if not forecasts:
        # Tahmin verilerini çek
        forecast_df = await fetch_forecast(site.latitude, site.longitude)
        
        # Güç hesapla
        forecast_df = calc_power(forecast_df, site.capacity_mw, site.site_type)
        
        # Gelir hesapla
        forecast_df = calc_revenue(forecast_df, site.country)
        
        # CO₂ tasarrufu hesapla
        forecast_df = calc_co2(forecast_df, site.country)
        
        # Batarya simülasyonu isteniyorsa
        if battery:
            battery_config = await get_battery_config(db, site_id)
            
            if battery_config:
                forecast_df = battery_dispatch(
                    forecast_df,
                    battery_config.capacity_mwh,
                    battery_config.power_mw,
                    battery_config.initial_soc
                )
            else:
                # Varsayılan batarya konfigürasyonu ile simülasyon yap
                forecast_df = battery_dispatch(forecast_df)
        
        # DataFrame'i JSON'a dönüştür
        forecast_data = forecast_df.to_dict(orient="records")
        return {
            "site_id": site_id,
            "site_name": site.name,
            "country": site.country,
            "capacity_mw": site.capacity_mw,
            "site_type": site.site_type,
            "forecasts": forecast_data
        }
    
    # Veritabanından alınan tahminleri döndür
    forecast_data = [
        {
            "timestamp": f.timestamp.isoformat(),
            "wind_speed": f.wind_speed,
            "ghi": f.ghi,
            "power_mw": f.power_mw,
            "revenue_eur": f.revenue_eur,
            "co2_saved_kg": f.co2_saved_kg,
            "battery_soc": f.battery_soc if battery else None,
            "battery_power_mw": f.battery_power_mw if battery else None
        }
        for f in forecasts
    ]
    
    return {
        "site_id": site_id,
        "site_name": site.name,
        "country": site.country,
        "capacity_mw": site.capacity_mw,
        "site_type": site.site_type,
        "forecasts": forecast_data
    }


@app.post("/api/sites/{site_id}/battery")
async def configure_battery(
    site_id: int,
    config: BatteryConfigCreate,
    db: Session = Depends(get_db)
):
    """Bir saha için batarya konfigürasyonu oluşturur veya günceller."""
    # Sahayı kontrol et
    await get_site(db, site_id)
    
    # Batarya konfigürasyonunu oluştur veya güncelle
    battery_config = await create_or_update_battery_config(db, site_id, config.dict())
    
    return {
        "site_id": site_id,
        "capacity_mwh": battery_config.capacity_mwh,
        "power_mw": battery_config.power_mw,
        "initial_soc": battery_config.initial_soc
    }


# @app.get("/api/report")
# async def get_report(db: Session = Depends(get_db)):
#     """PDF raporu oluşturur ve indirir."""
#     report_path = await generate_pdf_report(db)
#     
#     return FileResponse(
#         path=report_path,
#         filename="renewable_energy_report.pdf",
#         media_type="application/pdf"
#     )


@app.post("/api/prices/update")
async def update_prices_manual():
    """Elektrik fiyatlarını manuel olarak günceller."""
    try:
        success = update_electricity_prices()
        if success:
            return {
                "status": "success",
                "message": "Elektrik fiyatları başarıyla güncellendi",
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "warning",
                "message": "Fiyat güncellemesi kısmen başarısız, yedek veriler kullanıldı",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fiyat güncelleme hatası: {str(e)}")


@app.get("/api/prices/current")
async def get_current_prices():
    """Mevcut elektrik fiyatlarını döndürür."""
    try:
        import json
        prices_file = "./prices.json"
        
        if os.path.exists(prices_file):
            with open(prices_file, 'r', encoding='utf-8') as f:
                prices = json.load(f)
            return {
                "status": "success",
                "prices": prices,
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=404, detail="Fiyat dosyası bulunamadı")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fiyat okuma hatası: {str(e)}")


@app.get("/api/prices/status")
async def get_price_update_status():
    """Fiyat güncelleme durumunu döndürür."""
    try:
        import json
        prices_file = "./prices.json"
        
        if os.path.exists(prices_file):
            with open(prices_file, 'r', encoding='utf-8') as f:
                prices = json.load(f)
            
            last_updated = prices.get("last_updated")
            is_fallback = prices.get("updated_with_fallback", False)
            
            return {
                "status": "success",
                "last_updated": last_updated,
                "is_fallback_data": is_fallback,
                "scheduler_running": price_scheduler.running,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "warning",
                "message": "Fiyat dosyası bulunamadı",
                "scheduler_running": price_scheduler.running,
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Durum sorgulama hatası: {str(e)}")


# ---------------- ML Endpoints ----------------

@app.post("/api/ml/{site_id}/train")
async def train_site_model(site_id: int, db: Session = Depends(get_db)):
    """Belirtilen saha için ML modelini eğitir."""
    try:
        result = train_model(db, site_id)
        return {
            "status": "success",
            "metrics": result["metrics"],
            "model_path": result["model_path"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ML eğitim hatası: {str(e)}")


@app.get("/api/ml/{site_id}/predict")
async def predict_site_next_week(site_id: int, db: Session = Depends(get_db)):
    """Eğitilmiş modeli kullanarak gelecek 7 günü tahmin eder."""
    try:
        forecast_df = predict_next_week(db, site_id)
        # Zaman damgasını ISO string'e çevir
        forecast_df["timestamp"] = forecast_df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return forecast_df.to_dict(orient="records")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Model bulunamadı. Önce /train çağırın.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ML tahmin hatası: {str(e)}")
