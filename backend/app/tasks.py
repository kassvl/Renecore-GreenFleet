import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import pandas as pd
from sqlmodel import Session, select
from fastapi import BackgroundTasks
# from weasyprint import HTML
import httpx

from .models import Site, ForecastRecord, BatteryConfig
from .services import fetch_forecast, calc_power, calc_revenue, calc_co2, battery_dispatch
from .crud import create_forecast, delete_old_forecasts

# Uluslararasılaştırma için metin sözlüğü
TEXTS = {
    "tr": {
        "report_title": "Günlük Yenilenebilir Enerji Raporu",
        "report_date": "Rapor Tarihi",
        "site_summary": "Saha Özeti",
        "total_production": "Toplam Üretim",
        "total_revenue": "Toplam Gelir",
        "total_co2": "Toplam CO₂ Tasarrufu",
        "site_details": "Saha Detayları",
        "forecast_updated": "Tahminler güncellendi",
        "report_generated": "Rapor oluşturuldu",
        "slack_sent": "Slack bildirimi gönderildi",
    },
    "en": {
        "report_title": "Daily Renewable Energy Report",
        "report_date": "Report Date",
        "site_summary": "Site Summary",
        "total_production": "Total Production",
        "total_revenue": "Total Revenue",
        "total_co2": "Total CO₂ Savings",
        "site_details": "Site Details",
        "forecast_updated": "Forecasts updated",
        "report_generated": "Report generated",
        "slack_sent": "Slack notification sent",
    }
}

# Rapor dosya yolu
REPORT_PATH = "/tmp/daily_report.pdf"

# Slack webhook URL'si (opsiyonel)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK")


async def update_forecasts(db: Session) -> Dict[str, Any]:
    """Tüm sahalar için tahminleri günceller."""
    result = {
        "updated_sites": 0,
        "total_records": 0,
        "errors": []
    }
    
    # Tüm sahaları al
    statement = select(Site)
    sites = db.exec(statement).all()
    
    for site in sites:
        try:
            # Tahmin verilerini çek
            forecast_df = await fetch_forecast(site.latitude, site.longitude)
            
            # Güç hesapla
            forecast_df = calc_power(forecast_df, site.capacity_mw, site.site_type)
            
            # Gelir hesapla
            forecast_df = calc_revenue(forecast_df, site.country)
            
            # CO₂ tasarrufu hesapla
            forecast_df = calc_co2(forecast_df, site.country)
            
            # Batarya konfigürasyonunu kontrol et
            battery_config = db.exec(
                select(BatteryConfig).where(BatteryConfig.site_id == site.id)
            ).first()
            
            # Batarya varsa simülasyon yap
            if battery_config:
                forecast_df = battery_dispatch(
                    forecast_df,
                    battery_config.capacity_mwh,
                    battery_config.power_mw,
                    battery_config.initial_soc
                )
            
            # Eski tahminleri sil
            now = datetime.now()
            await delete_old_forecasts(db, now - timedelta(days=1))
            
            # Yeni tahminleri kaydet
            for _, row in forecast_df.iterrows():
                forecast_data = {
                    "site_id": site.id,
                    "timestamp": row["timestamp"],
                    "wind_speed": row.get("wind_speed"),
                    "ghi": row.get("ghi"),
                    "power_mw": row["power_mw"],
                    "revenue_eur": row["revenue_eur"],
                    "co2_saved_kg": row["co2_saved_kg"],
                }
                
                # Batarya verileri varsa ekle
                if "battery_soc" in row and "battery_power_mw" in row:
                    forecast_data["battery_soc"] = row["battery_soc"]
                    forecast_data["battery_power_mw"] = row["battery_power_mw"]
                
                await create_forecast(db, forecast_data)
                result["total_records"] += 1
            
            result["updated_sites"] += 1
            
        except Exception as error:
            result["errors"].append(f"Error updating site {site.name}: {str(error)}")
    
    return result


async def generate_pdf_report(db: Session) -> str:
    """Günlük PDF raporu oluşturur."""
    # Rapor için veri topla
    statement = select(Site)
    sites = db.exec(statement).all()
    
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    
    site_data = []
    total_production = 0
    total_revenue = 0
    total_co2 = 0
    
    for site in sites:
        # Son 24 saatlik tahminleri al
        forecasts = db.exec(
            select(ForecastRecord).where(
                ForecastRecord.site_id == site.id,
                ForecastRecord.timestamp >= now,
                ForecastRecord.timestamp < tomorrow
            )
        ).all()
        
        # Site özeti hesapla
        site_production = sum(f.power_mw for f in forecasts)
        site_revenue = sum(f.revenue_eur for f in forecasts)
        site_co2 = sum(f.co2_saved_kg for f in forecasts)
        
        site_data.append({
            "name": site.name,
            "country": site.country,
            "type": site.site_type,
            "capacity": site.capacity_mw,
            "production": site_production,
            "revenue": site_revenue,
            "co2": site_co2
        })
        
        total_production += site_production
        total_revenue += site_revenue
        total_co2 += site_co2
    
    # HTML raporu oluştur
    html_content = f"""
    <html>
    <head>
        <title>{TEXTS['en']['report_title']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #2c3e50; }}
            .summary {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #3498db; color: white; }}
            tr:nth-child(even) {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h1>{TEXTS['en']['report_title']}</h1>
        <p>{TEXTS['en']['report_date']}: {now.strftime('%Y-%m-%d')}</p>
        
        <div class="summary">
            <h2>{TEXTS['en']['site_summary']}</h2>
            <p>{TEXTS['en']['total_production']}: {total_production:.2f} MWh</p>
            <p>{TEXTS['en']['total_revenue']}: {total_revenue:.2f} EUR</p>
            <p>{TEXTS['en']['total_co2']}: {total_co2:.2f} kg</p>
        </div>
        
        <h2>{TEXTS['en']['site_details']}</h2>
        <table>
            <tr>
                <th>Site</th>
                <th>Country</th>
                <th>Type</th>
                <th>Capacity (MW)</th>
                <th>Production (MWh)</th>
                <th>Revenue (EUR)</th>
                <th>CO₂ Saved (kg)</th>
            </tr>
    """
    
    for site in site_data:
        html_content += f"""
            <tr>
                <td>{site['name']}</td>
                <td>{site['country']}</td>
                <td>{site['type']}</td>
                <td>{site['capacity']:.2f}</td>
                <td>{site['production']:.2f}</td>
                <td>{site['revenue']:.2f}</td>
                <td>{site['co2']:.2f}</td>
            </tr>
        """
    
    html_content += """
        </table>
    </body>
    </html>
    """
    
    # HTML'i PDF'e dönüştür
    # HTML(string=html_content).write_pdf(REPORT_PATH)
    # WeasyPrint disabled due to pango dependency issue
    with open(REPORT_PATH.replace('.pdf', '.html'), 'w') as f:
        f.write(html_content)
    
    return REPORT_PATH


async def send_slack_notification(report_path: str) -> bool:
    """Slack'e rapor gönderir."""
    if not SLACK_WEBHOOK:
        return False
    
    try:
        now = datetime.now()
        message = {
            "text": f"{TEXTS['en']['report_title']} - {now.strftime('%Y-%m-%d')}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{TEXTS['en']['report_title']}*\n{now.strftime('%Y-%m-%d')}"
                    }
                }
            ]
        }
        
        async with httpx.AsyncClient() as client:
            # Önce mesajı gönder
            await client.post(SLACK_WEBHOOK, json=message)
            
            # Sonra dosyayı gönder
            with open(report_path, "rb") as file:
                files = {"file": ("daily_report.pdf", file, "application/pdf")}
                await client.post(
                    SLACK_WEBHOOK, 
                    files=files,
                    data={"filename": "daily_report.pdf"}
                )
        
        return True
    
    except Exception:
        return False


async def scheduled_tasks(db: Session) -> Dict[str, Any]:
    """Zamanlanmış görevleri çalıştırır."""
    result = {
        "forecast_update": None,
        "report_generated": False,
        "slack_sent": False
    }
    
    # Tahminleri güncelle
    result["forecast_update"] = await update_forecasts(db)
    print(TEXTS['en']['forecast_updated'])
    
    # Gece yarısı kontrolü (23:00 - 01:00 arası)
    now = datetime.now()
    if 23 <= now.hour or now.hour <= 1:
        # PDF raporu oluştur
        report_path = await generate_pdf_report(db)
        result["report_generated"] = True
        print(TEXTS['en']['report_generated'])
        
        # Slack bildirimi gönder
        if SLACK_WEBHOOK:
            result["slack_sent"] = await send_slack_notification(report_path)
            if result["slack_sent"]:
                print(TEXTS['en']['slack_sent'])
    
    return result


async def background_task_loop(db_generator) -> None:
    """Arka planda çalışan görev döngüsü."""
    while True:
        try:
            # Yeni bir DB oturumu oluştur
            with next(db_generator)() as db:
                await scheduled_tasks(db)
        except Exception as error:
            print(f"Background task error: {str(error)}")
        
        # 6 saat bekle
        await asyncio.sleep(6 * 60 * 60)


def start_background_tasks(background_tasks: BackgroundTasks, db_generator) -> None:
    """Arka plan görevlerini başlatır."""
    background_tasks.add_task(background_task_loop, db_generator)
