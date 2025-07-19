from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlmodel import Session, select
from fastapi import HTTPException

from .models import Site, ForecastRecord, BatteryConfig

# CRUD işlemleri için yardımcı fonksiyonlar

async def get_sites(db: Session) -> List[Site]:
    """Tüm sahaları döndürür."""
    statement = select(Site)
    sites = db.exec(statement).all()
    return sites


async def get_site(db: Session, site_id: int) -> Site:
    """ID'ye göre sahayı döndürür."""
    site = db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def create_site(db: Session, site_data: Dict[str, Any]) -> Site:
    """Yeni bir saha oluşturur."""
    site = Site(**site_data)
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


async def update_site(db: Session, site_id: int, site_data: Dict[str, Any]) -> Site:
    """Mevcut bir sahayı günceller."""
    site = await get_site(db, site_id)
    
    for key, value in site_data.items():
        setattr(site, key, value)
    
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


async def delete_site(db: Session, site_id: int) -> None:
    """Bir sahayı siler."""
    site = await get_site(db, site_id)
    db.delete(site)
    db.commit()


async def get_forecast(
    db: Session, 
    site_id: int, 
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> List[ForecastRecord]:
    """Belirli bir saha için tahmin kayıtlarını döndürür."""
    if not start_time:
        start_time = datetime.now()
    if not end_time:
        end_time = start_time + timedelta(days=7)
    
    statement = select(ForecastRecord).where(
        ForecastRecord.site_id == site_id,
        ForecastRecord.timestamp >= start_time,
        ForecastRecord.timestamp <= end_time
    ).order_by(ForecastRecord.timestamp)
    
    forecasts = db.exec(statement).all()
    return forecasts


async def create_forecast(db: Session, forecast_data: Dict[str, Any]) -> ForecastRecord:
    """Yeni bir tahmin kaydı oluşturur."""
    forecast = ForecastRecord(**forecast_data)
    db.add(forecast)
    db.commit()
    db.refresh(forecast)
    return forecast


async def create_or_update_battery_config(
    db: Session, 
    site_id: int, 
    battery_data: Dict[str, Any]
) -> BatteryConfig:
    """Batarya konfigürasyonu oluşturur veya günceller."""
    statement = select(BatteryConfig).where(BatteryConfig.site_id == site_id)
    existing_config = db.exec(statement).first()
    
    if existing_config:
        for key, value in battery_data.items():
            setattr(existing_config, key, value)
        db.add(existing_config)
        db.commit()
        db.refresh(existing_config)
        return existing_config
    else:
        battery_data["site_id"] = site_id
        battery_config = BatteryConfig(**battery_data)
        db.add(battery_config)
        db.commit()
        db.refresh(battery_config)
        return battery_config


async def get_battery_config(db: Session, site_id: int) -> Optional[BatteryConfig]:
    """Bir saha için batarya konfigürasyonunu döndürür."""
    statement = select(BatteryConfig).where(BatteryConfig.site_id == site_id)
    battery_config = db.exec(statement).first()
    return battery_config


async def delete_old_forecasts(db: Session, older_than: datetime) -> int:
    """Belirli bir tarihten eski tahmin kayıtlarını siler."""
    statement = select(ForecastRecord).where(ForecastRecord.timestamp < older_than)
    old_forecasts = db.exec(statement).all()
    count = len(old_forecasts)
    
    for forecast in old_forecasts:
        db.delete(forecast)
    
    db.commit()
    return count
