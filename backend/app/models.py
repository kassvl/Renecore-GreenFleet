import os
from datetime import datetime
from typing import List, Optional
from sqlmodel import Field, Relationship, SQLModel, create_engine

# Uluslararasılaştırma için metin sözlüğü
TEXTS = {
    "tr": {
        "site_name": "Saha Adı",
        "site_country": "Ülke",
        "site_capacity": "Kapasite (MW)",
        "site_type": "Tür",
        "site_lat": "Enlem",
        "site_lon": "Boylam",
        "forecast_timestamp": "Tahmin Zamanı",
        "forecast_wind_speed": "Rüzgar Hızı (m/s)",
        "forecast_ghi": "GHI (W/m²)",
        "forecast_power": "Güç (MW)",
        "forecast_revenue": "Gelir (EUR)",
        "forecast_co2_saved": "CO₂ Tasarrufu (kg)",
        "battery_capacity": "Batarya Kapasitesi (MWh)",
        "battery_power": "Batarya Gücü (MW)",
        "battery_soc": "Şarj Durumu",
    },
    "en": {
        "site_name": "Site Name",
        "site_country": "Country",
        "site_capacity": "Capacity (MW)",
        "site_type": "Type",
        "site_lat": "Latitude",
        "site_lon": "Longitude",
        "forecast_timestamp": "Forecast Time",
        "forecast_wind_speed": "Wind Speed (m/s)",
        "forecast_ghi": "GHI (W/m²)",
        "forecast_power": "Power (MW)",
        "forecast_revenue": "Revenue (EUR)",
        "forecast_co2_saved": "CO₂ Saved (kg)",
        "battery_capacity": "Battery Capacity (MWh)",
        "battery_power": "Battery Power (MW)",
        "battery_soc": "State of Charge",
    }
}

class Site(SQLModel, table=True):
    """Rüzgar ve güneş sahalarını temsil eden model."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    country: str = Field(index=True)  # TR veya RO
    capacity_mw: float
    site_type: str  # "wind" veya "solar"
    latitude: float
    longitude: float
    
    forecasts: List["ForecastRecord"] = Relationship(back_populates="site")
    battery_config: Optional["BatteryConfig"] = Relationship(back_populates="site")


class ForecastRecord(SQLModel, table=True):
    """Tahmin kayıtlarını temsil eden model."""
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="site.id")
    timestamp: datetime = Field(index=True)
    wind_speed: Optional[float] = None  # m/s, 100m yükseklikte
    ghi: Optional[float] = None  # W/m²
    power_mw: float  # Hesaplanan güç çıkışı
    revenue_eur: float  # Hesaplanan gelir
    co2_saved_kg: float  # Hesaplanan CO₂ tasarrufu
    battery_soc: Optional[float] = None  # Batarya şarj durumu (0-1)
    battery_power_mw: Optional[float] = None  # Batarya güç çıkışı/girişi
    
    site: Site = Relationship(back_populates="forecasts")


class BatteryConfig(SQLModel, table=True):
    """Batarya konfigürasyonunu temsil eden model."""
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="site.id", unique=True)
    capacity_mwh: float = 4.0  # Varsayılan 4 saat / 1 MW
    power_mw: float = 1.0
    initial_soc: float = 0.5  # Başlangıç şarj durumu (0-1)
    
    site: Site = Relationship(back_populates="battery_config")


# Veritabanı bağlantı URL'si
# Production: postgresql://postgres:postgres@db:5432/greenfleet
# Local test için SQLite kullanıyoruz
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./greenfleet.db")

def get_engine():
    """SQLAlchemy motor nesnesi oluşturur."""
    return create_engine(DATABASE_URL)


def create_db_and_tables():
    """Veritabanı ve tabloları oluşturur."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
