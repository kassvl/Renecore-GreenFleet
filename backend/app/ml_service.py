"""
ML servis katmanı – model eğitme, yükleme ve tahmin işlevleri
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any

import pandas as pd
from sqlmodel import Session, select
from loguru import logger

from .models import ForecastRecord, Site
from .ml_models import ModelFactory, EnsembleForecaster, ModelConfig

# Model kayıt dizini
MODEL_DIR = Path(os.getenv("ML_MODEL_DIR", "./models"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def _get_site_data(db: Session, site_id: int) -> pd.DataFrame:
    """Belirli bir saha için tüm geçmiş ForecastRecord verilerini getirir."""
    stmt = (
        select(ForecastRecord)
        .where(ForecastRecord.site_id == site_id)
        .order_by(ForecastRecord.timestamp)
    )
    records = db.exec(stmt).all()
    if not records:
        raise ValueError("Seçilen saha için yeterli veri bulunamadı")

    df = pd.DataFrame([
        {
            "timestamp": r.timestamp,
            "site_id": r.site_id,
            "wind_speed": r.wind_speed,
            "ghi": r.ghi,
            "power_mw": r.power_mw,
            "price_eur_mwh": None,  # price alanı ForecastRecord'da yok, placeholder
            "battery_soc": r.battery_soc,
            "battery_power_mw": r.battery_power_mw,
        }
        for r in records
    ])
    return df


def _get_model_path(site_id: int) -> Path:
    return MODEL_DIR / f"site_{site_id}"


def train_model(db: Session, site_id: int) -> Dict[str, Any]:
    """Belirtilen saha için modeli eğitir ve kaydeder."""
    logger.info(f"ML eğitim başlıyor | site_id={site_id}")
    df = _get_site_data(db, site_id)

    # Model oluştur
    config: ModelConfig = ModelFactory.get_default_config()
    model: EnsembleForecaster = ModelFactory.create_model("ensemble", config)

    # Eğitim
    try:
        model.fit(df, target_col="power_mw")
    except Exception as exc:
        logger.error(f"Eğitim hatası: {exc}")
        raise

    # Performans değerlendirme (son 7 gün)
    test_df = df.tail(config.horizon)
    metrics = model.evaluate(test_df, target_col="power_mw")

    # Modeli kaydet
    save_path = _get_model_path(site_id)
    save_path.mkdir(parents=True, exist_ok=True)
    model.save_model(str(save_path))

    logger.info(f"Model eğitildi ve kaydedildi | path={save_path}")
    return {"metrics": metrics, "model_path": str(save_path)}


def load_model(site_id: int) -> EnsembleForecaster:
    """Kaydedilmiş modeli yükler. Yoksa hata fırlatır."""
    load_path = _get_model_path(site_id)
    if not load_path.exists():
        raise FileNotFoundError("Model henüz eğitilmemiş.")

    config = ModelFactory.get_default_config()
    model: EnsembleForecaster = ModelFactory.create_model("ensemble", config)
    model.load_model(str(load_path))
    return model


def predict_next_week(db: Session, site_id: int) -> pd.DataFrame:
    """Son 7 gün için tahmin verisi döndürür."""
    # Veri çek
    df = _get_site_data(db, site_id)

    # Model yükle
    model = load_model(site_id)

    # Tahmin
    forecast_df = model.predict(df, target_col="power_mw")
    return forecast_df
