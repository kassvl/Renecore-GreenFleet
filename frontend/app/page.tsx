'use client';

import { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { MultiChart } from './components/Chart';

// Leaflet marker icon fix
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// Uluslararasılaştırma için metin sözlüğü
const TEXTS = {
  tr: {
    title: 'Renecore-GreenFleet',
    subtitle: 'Yenilenebilir Enerji İzleme Paneli',
    loading: 'Yükleniyor...',
    error: 'Veri yüklenirken hata oluştu',
    site_details: 'Saha Detayları',
    battery_simulation: 'Batarya Simülasyonu',
    close: 'Kapat',
    revenue_24h: '24s Gelir',
    co2_saved_24h: '24s CO₂ Tasarrufu',
    capacity: 'Kapasite',
    country: 'Ülke',
    type: 'Tür',
    wind: 'Rüzgar',
    solar: 'Güneş',
  },
  en: {
    title: 'Renecore-GreenFleet',
    subtitle: 'Renewable Energy Monitoring Dashboard',
    loading: 'Loading...',
    error: 'Error loading data',
    site_details: 'Site Details',
    battery_simulation: 'Battery Simulation',
    close: 'Close',
    revenue_24h: '24h Revenue',
    co2_saved_24h: '24h CO₂ Saved',
    capacity: 'Capacity',
    country: 'Country',
    type: 'Type',
    wind: 'Wind',
    solar: 'Solar',
  }
};

// Saha tipi
interface Site {
  id: number;
  name: string;
  country: string;
  capacity_mw: number;
  site_type: string;
  latitude: number;
  longitude: number;
}

// Tahmin verisi tipi
interface ForecastData {
  timestamp: string;
  wind_speed?: number;
  ghi?: number;
  power_mw: number;
  revenue_eur: number;
  co2_saved_kg: number;
  battery_soc?: number;
  battery_power_mw?: number;
}

// Tahmin yanıtı tipi
interface ForecastResponse {
  site_id: number;
  site_name: string;
  country: string;
  capacity_mw: number;
  site_type: string;
  forecasts: ForecastData[];
}

export default function Home() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [selectedSite, setSelectedSite] = useState<Site | null>(null);
  const [forecastData, setForecastData] = useState<ForecastData[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(false);
  const [batteryEnabled, setBatteryEnabled] = useState<boolean>(false);
  const lang = 'en'; // Varsayılan dil

  // Sahaları yükle
  useEffect(() => {
    const fetchSites = async () => {
      try {
        const response = await fetch('http://localhost:8001/api/sites');
        if (!response.ok) {
          throw new Error('Failed to fetch sites');
        }
        const data = await response.json();
        setSites(data);
      } catch (err) {
        console.error('Error fetching sites:', err);
        setError('Failed to load sites');
      }
    };

    fetchSites();
  }, []);

  // Haritayı başlat
  useEffect(() => {
    if (map.current || !mapContainer.current) return;

    map.current = L.map(mapContainer.current).setView([45.0, 26.0], 5);

    // OpenStreetMap tile layer ekle
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18,
    }).addTo(map.current);

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  // Sahaları haritaya ekle
  useEffect(() => {
    if (!map.current || !sites.length) return;

    // Yeni işaretçileri ekle
    sites.forEach(site => {
      // 24 saatlik geliri hesapla (demo için rastgele değer)
      const revenue24h = Math.random() * 1000 + 500;
      
      // İşaretçi boyutunu gelire göre ölçeklendir
      const size = Math.max(20, Math.min(50, revenue24h / 50));
      
      // İşaretçi elementi oluştur
      const el = document.createElement('div');
      el.className = `site-marker ${site.site_type}`;
      el.style.width = `${size}px`;
      el.style.height = `${size}px`;
      el.style.borderRadius = '50%';
      el.style.cursor = 'pointer';
      
      // Site tipine göre renk ayarla
      if (site.site_type === 'wind') {
        el.style.backgroundColor = '#3b82f6';
      } else {
        el.style.backgroundColor = '#f59e0b';
      }
      
      // Gelire göre opaklık ayarla
      const opacity = Math.min(1, Math.max(0.5, revenue24h / 1500));
      el.style.opacity = opacity.toString();
      
      // Custom icon oluştur
      const customIcon = L.divIcon({
        html: el.outerHTML,
        className: 'custom-marker',
        iconSize: [size, size],
        iconAnchor: [size/2, size/2]
      });
      
      // İşaretçiyi haritaya ekle
      const marker = L.marker([site.latitude, site.longitude], { icon: customIcon })
        .addTo(map.current!);
      
      // Tıklama olayı ekle
      marker.on('click', () => {
        setSelectedSite(site);
        fetchForecast(site.id);
        setSidebarOpen(true);
      });
    });
  }, [sites]);

  // Seçili saha için tahmin verilerini yükle
  const fetchForecast = async (siteId: number) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(
        `http://localhost:8001/api/forecast/${siteId}?type=${selectedSite?.site_type || 'wind'}&battery=${batteryEnabled}`
      );
      
      if (!response.ok) {
        throw new Error('Failed to fetch forecast');
      }
      
      const data: ForecastResponse = await response.json();
      setForecastData(data.forecasts);
    } catch (err) {
      console.error('Error fetching forecast:', err);
      setError('Failed to load forecast data');
    } finally {
      setLoading(false);
    }
  };

  // Batarya durumu değiştiğinde tahminleri yeniden yükle
  useEffect(() => {
    if (selectedSite) {
      fetchForecast(selectedSite.id);
    }
  }, [batteryEnabled]);

  // 24 saatlik gelir ve CO2 tasarrufu hesapla
  const calculate24hMetrics = () => {
    if (!forecastData || forecastData.length === 0) {
      return { revenue: 0, co2: 0 };
    }
    
    // İlk 24 saatlik verileri al
    const data24h = forecastData.slice(0, 24);
    
    // Toplam gelir ve CO2 tasarrufu hesapla
    const revenue = data24h.reduce((sum, item) => sum + item.revenue_eur, 0);
    const co2 = data24h.reduce((sum, item) => sum + item.co2_saved_kg, 0);
    
    return { revenue, co2 };
  };

  const metrics24h = calculate24hMetrics();

  return (
    <div className="container">
      <header className="header">
        <div>
          <h1>{TEXTS[lang].title}</h1>
          <p>{TEXTS[lang].subtitle}</p>
        </div>
      </header>
      
      <main className="main">
        <div ref={mapContainer} className="map-container" />
        
        <div className={`sidebar ${sidebarOpen ? '' : 'closed'}`}>
          <button className="close-btn" onClick={() => setSidebarOpen(false)}>
            &times;
          </button>
          
          {selectedSite && (
            <div>
              <div className="card">
                <div className="card-header">
                  <h2 className="card-title">{selectedSite.name}</h2>
                </div>
                
                <div className="site-info">
                  <div className="site-info-item">
                    <span className="site-info-label">{TEXTS[lang].country}</span>
                    <span className="site-info-value">{selectedSite.country}</span>
                  </div>
                  
                  <div className="site-info-item">
                    <span className="site-info-label">{TEXTS[lang].type}</span>
                    <span className="site-info-value">
                      {selectedSite.site_type === 'wind' ? TEXTS[lang].wind : TEXTS[lang].solar}
                    </span>
                  </div>
                  
                  <div className="site-info-item">
                    <span className="site-info-label">{TEXTS[lang].capacity}</span>
                    <span className="site-info-value">{selectedSite.capacity_mw} MW</span>
                  </div>
                  
                  <div className="site-info-item">
                    <span className="site-info-label">{TEXTS[lang].revenue_24h}</span>
                    <span className="site-info-value">{metrics24h.revenue.toFixed(2)} EUR</span>
                  </div>
                  
                  <div className="site-info-item">
                    <span className="site-info-label">{TEXTS[lang].co2_saved_24h}</span>
                    <span className="site-info-value">{metrics24h.co2.toFixed(2)} kg</span>
                  </div>
                </div>
              </div>
              
              <div className="card">
                <div className="card-header">
                  <h3 className="card-title">{TEXTS[lang].battery_simulation}</h3>
                  <label className="switch">
                    <input 
                      type="checkbox" 
                      checked={batteryEnabled}
                      onChange={() => setBatteryEnabled(!batteryEnabled)}
                    />
                    <span className="slider"></span>
                  </label>
                </div>
              </div>
              
              <div className="card">
                {loading ? (
                  <p>{TEXTS[lang].loading}</p>
                ) : error ? (
                  <p>{error}</p>
                ) : (
                  <MultiChart data={forecastData} showBattery={batteryEnabled} />
                )}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
