import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx
import pandas as pd
import numpy as np
from fastapi import HTTPException

# Sabit değerler
PRICES_PATH = "./prices.json"
GRID_FACTORS_PATH = "./grid_factors.json"

# Uluslararasılaştırma için metin sözlüğü
TEXTS = {
    "tr": {
        "error_fetch": "Tahmin verileri alınamadı",
        "error_prices": "Fiyat verileri okunamadı",
        "error_grid": "Şebeke faktörleri okunamadı",
    },
    "en": {
        "error_fetch": "Failed to fetch forecast data",
        "error_prices": "Failed to read price data",
        "error_grid": "Failed to read grid factors",
    }
}

async def fetch_forecast(latitude: float, longitude: float) -> pd.DataFrame:
    """Open-Meteo API'sinden 7 günlük tahmin verilerini çeker."""
    url = "https://api.open-meteo.com/v1/forecast"
    
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "windspeed_100m,direct_radiation,diffuse_radiation",
        "forecast_days": 7,
        "timezone": "auto"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Saatlik verileri DataFrame'e dönüştür
            hourly_data = data["hourly"]
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(hourly_data["time"], utc=True),
                "wind_speed": hourly_data["windspeed_100m"],
                "direct_radiation": hourly_data["direct_radiation"],
                "diffuse_radiation": hourly_data["diffuse_radiation"]
            })
            
            # GHI (Global Horizontal Irradiance) hesapla
            df["ghi"] = df["direct_radiation"] + df["diffuse_radiation"]
            
            # Gereksiz sütunları kaldır
            df = df.drop(columns=["direct_radiation", "diffuse_radiation"])
            
            return df
    except Exception as error:
        raise HTTPException(
            status_code=500, 
            detail=f"{TEXTS['en']['error_fetch']}: {str(error)}"
        )


def calc_power(df: pd.DataFrame, capacity_mw: float, site_type: str) -> pd.DataFrame:
    """Rüzgar veya güneş için güç üretimini hesaplar."""
    df_result = df.copy()
    
    if site_type == "wind":
        # Basit rüzgar türbini güç eğrisi modeli
        # Cut-in hızı: 3 m/s, rated hızı: 12 m/s, cut-out hızı: 25 m/s
        wind_speed = df_result["wind_speed"]
        power_factor = np.zeros(len(wind_speed))
        
        # Cut-in ile rated arasında kübik artış
        mask_ramp = (wind_speed >= 3) & (wind_speed < 12)
        power_factor[mask_ramp] = ((wind_speed[mask_ramp] - 3) / 9) ** 3
        
        # Rated ile cut-out arasında sabit
        mask_rated = (wind_speed >= 12) & (wind_speed <= 25)
        power_factor[mask_rated] = 1.0
        
        df_result["power_mw"] = power_factor * capacity_mw
        
    elif site_type == "solar":
        # Basit güneş PV modeli
        # Varsayılan panel verimliliği %20, sistem kayıpları %15
        efficiency = 0.20
        system_losses = 0.15
        
        # Standart test koşulları: 1000 W/m²
        stc_irradiance = 1000.0
        
        # Güç hesaplama (GHI * verimlilik * (1-kayıplar) * (kapasite/stc))
        df_result["power_mw"] = (
            df_result["ghi"] * efficiency * (1 - system_losses) * 
            (capacity_mw / stc_irradiance)
        )
        
        # Gece saatlerinde (GHI < 5) güç üretimi sıfır
        df_result.loc[df_result["ghi"] < 5, "power_mw"] = 0
        
    else:
        raise ValueError(f"Geçersiz site türü: {site_type}. 'wind' veya 'solar' olmalı.")
    
    # Negatif değerleri sıfırla ve kapasiteyi aşan değerleri kırp
    df_result["power_mw"] = np.clip(df_result["power_mw"], 0, capacity_mw)
    
    return df_result


def calc_revenue(df: pd.DataFrame, country: str) -> pd.DataFrame:
    """Güç üretimi ve dinamik fiyatlara göre geliri hesaplar."""
    df_result = df.copy()
    
    try:
        # Fiyat verilerini oku
        with open(PRICES_PATH, "r") as file:
            prices_data = json.load(file)
        
        # Ülkeye göre fiyatları al
        if country not in prices_data:
            raise ValueError(f"Ülke fiyat verisi bulunamadı: {country}")
        
        country_prices = prices_data[country]
        base_price = country_prices["base_price"]
        daily_pattern = country_prices["daily_pattern"]
        weekly_multiplier = country_prices["weekly_multiplier"]
        
        # Her timestamp için dinamik fiyat hesapla
        prices = []
        for timestamp in df_result["timestamp"]:
            # Saat ve gün bilgilerini al
            hour = timestamp.strftime("%H")
            day_name = timestamp.strftime("%A").lower()
            
            # Dinamik fiyat hesapla
            hourly_factor = daily_pattern.get(hour, 1.0)
            weekly_factor = weekly_multiplier.get(day_name, 1.0)
            
            # Rastgele varyasyon ekle (±5%)
            import random
            random_factor = random.uniform(0.95, 1.05)
            
            final_price = base_price * hourly_factor * weekly_factor * random_factor
            prices.append(final_price)
        
        df_result["price_eur_mwh"] = prices
        
        # Geliri hesapla (MWh * EUR/MWh)
        df_result["revenue_eur"] = df_result["power_mw"] * df_result["price_eur_mwh"]
        
        return df_result
    
    except Exception as error:
        raise HTTPException(
            status_code=500, 
            detail=f"{TEXTS['en']['error_prices']}: {str(error)}"
        )


def calc_co2(df: pd.DataFrame, country: str) -> pd.DataFrame:
    """Güç üretimine göre CO₂ tasarrufunu hesaplar."""
    df_result = df.copy()
    
    try:
        # Grid faktörlerini oku
        with open(GRID_FACTORS_PATH, "r") as file:
            grid_factors = json.load(file)
        
        # Ülkeye göre grid faktörünü al (kg CO₂/kWh)
        if country not in grid_factors:
            raise ValueError(f"Ülke grid faktörü bulunamadı: {country}")
        
        grid_factor = grid_factors[country]
        
        # CO₂ tasarrufunu hesapla (MWh * 1000 * kg CO₂/kWh)
        df_result["co2_saved_kg"] = df_result["power_mw"] * 1000 * grid_factor
        
        return df_result
    
    except Exception as error:
        raise HTTPException(
            status_code=500, 
            detail=f"{TEXTS['en']['error_grid']}: {str(error)}"
        )


def battery_dispatch(
    df: pd.DataFrame, 
    capacity_mwh: float = 4.0, 
    power_mw: float = 1.0, 
    soc0: float = 0.5
) -> pd.DataFrame:
    """Batarya depolama simülasyonu yapar."""
    df_result = df.copy()
    
    # Başlangıç değerleri
    soc = soc0  # State of Charge (0-1)
    energy_mwh = soc * capacity_mwh
    
    # Sonuç sütunları
    soc_values = []
    battery_power_values = []
    
    # Fiyat eşiği hesapla (ortalama fiyat)
    price_threshold = df_result["price_eur_mwh"].mean()
    
    for idx, row in df_result.iterrows():
        price = row["price_eur_mwh"]
        renewable_power = row["power_mw"]
        
        # Batarya güç değişimi (pozitif = şarj, negatif = deşarj)
        battery_power = 0.0
        
        # Fiyat düşükse ve batarya dolu değilse şarj et
        if price < price_threshold and soc < 0.95:
            # Şarj gücü (min(batarya max gücü, boş kapasite))
            charge_power = min(power_mw, (capacity_mwh * (1 - soc)))
            battery_power = min(charge_power, renewable_power)
        
        # Fiyat yüksekse ve batarya boş değilse deşarj et
        elif price > price_threshold and soc > 0.05:
            # Deşarj gücü (min(batarya max gücü, dolu kapasite))
            discharge_power = min(power_mw, (capacity_mwh * soc))
            battery_power = -discharge_power
        
        # Enerji ve SOC güncelle
        energy_mwh += battery_power
        soc = energy_mwh / capacity_mwh
        
        # Sınırları kontrol et
        soc = np.clip(soc, 0, 1)
        energy_mwh = soc * capacity_mwh
        
        # Değerleri kaydet
        soc_values.append(soc)
        battery_power_values.append(battery_power)
    
    # Sonuçları DataFrame'e ekle
    df_result["battery_soc"] = soc_values
    df_result["battery_power_mw"] = battery_power_values
    
    # Toplam gücü güncelle (yenilenebilir + batarya)
    df_result["power_mw"] = df_result["power_mw"] + df_result["battery_power_mw"]
    
    # Geliri yeniden hesapla
    df_result["revenue_eur"] = df_result["power_mw"] * df_result["price_eur_mwh"]
    
    # CO₂ tasarrufunu yeniden hesapla
    grid_factor = df_result["co2_saved_kg"].iloc[0] / (df_result["power_mw"].iloc[0] * 1000)
    df_result["co2_saved_kg"] = df_result["power_mw"] * 1000 * grid_factor
    
    return df_result
