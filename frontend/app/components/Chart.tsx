'use client';

import React, { useEffect, useRef } from 'react';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend } from 'chart.js';
import { Line } from 'react-chartjs-2';

// Chart.js tip tanımlamaları
type ChartDataType = {
  labels: string[];
  datasets: Array<{
    label: string;
    data: (number | null)[];
    borderColor: string;
    backgroundColor: string;
    tension: number;
    fill?: boolean;
    yAxisID?: string;
  }>;
};

type ChartOptionsType = {
  responsive: boolean;
  maintainAspectRatio: boolean;
  plugins: {
    legend: {
      position: 'top' | 'bottom' | 'left' | 'right';
    };
    title: {
      display: boolean;
      text: string;
    };
    tooltip: {
      mode: 'index' | 'nearest' | 'point' | 'dataset';
      intersect: boolean;
    };
  };
  scales: {
    x: {
      title: {
        display: boolean;
        text: string;
      };
    };
    y: {
      beginAtZero: boolean;
    };
  };
  interaction: {
    mode: 'nearest' | 'index' | 'point' | 'dataset';
    axis: 'x' | 'y' | 'xy';
    intersect: boolean;
  };
};

// Chart.js bileşenlerini kaydet
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

// Uluslararasılaştırma için metin sözlüğü
const TEXTS = {
  tr: {
    revenue: 'Gelir (EUR)',
    co2_saved: 'CO₂ Tasarrufu (kg)',
    battery_soc: 'Batarya Şarj Durumu',
    hours: 'Saat',
  },
  en: {
    revenue: 'Revenue (EUR)',
    co2_saved: 'CO₂ Saved (kg)',
    battery_soc: 'Battery State of Charge',
    hours: 'Hours',
  }
};

// Tahmin verisi tipi
interface ForecastData {
  timestamp: string;
  power_mw: number;
  revenue_eur: number;
  co2_saved_kg: number;
  battery_soc?: number;
}

// Grafik bileşeni özellikleri
interface ChartProps {
  data: ForecastData[];
  type: 'revenue' | 'co2' | 'soc';
  title?: string;
  height?: number;
  showBattery?: boolean;
}

export default function ForecastChart({ data, type, title, height = 300, showBattery = false }: ChartProps) {
  const chartRef = useRef<any>(null);
  const lang = 'en'; // Varsayılan dil

  // Zaman etiketlerini oluştur
  const labels = data.map(item => {
    const date = new Date(item.timestamp);
    return `${date.getDate()}/${date.getMonth() + 1} ${date.getHours()}:00`;
  });

  // Grafik verilerini hazırla
  const chartData: ChartDataType = {
    labels,
    datasets: []
  };

  // Grafik türüne göre veri setlerini oluştur
  if (type === 'revenue') {
    chartData.datasets.push({
      label: TEXTS[lang].revenue,
      data: data.map(item => item.revenue_eur),
      borderColor: '#3498db',
      backgroundColor: 'rgba(52, 152, 219, 0.2)',
      tension: 0.3,
      fill: true,
    });
  } else if (type === 'co2') {
    chartData.datasets.push({
      label: TEXTS[lang].co2_saved,
      data: data.map(item => item.co2_saved_kg),
      borderColor: '#2ecc71',
      backgroundColor: 'rgba(46, 204, 113, 0.2)',
      tension: 0.3,
      fill: true,
    });
  } else if (type === 'soc' && showBattery) {
    chartData.datasets.push({
      label: TEXTS[lang].battery_soc,
      data: data.map(item => (item.battery_soc !== undefined ? item.battery_soc * 100 : null)),
      borderColor: '#f39c12',
      backgroundColor: 'rgba(243, 156, 18, 0.2)',
      tension: 0.3,
      fill: true,
      yAxisID: 'y',
    });
  }

  // Grafik seçenekleri
  const options: ChartOptionsType = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
      },
      title: {
        display: !!title,
        text: title || '',
      },
      tooltip: {
        mode: 'index',
        intersect: false,
      },
    },
    scales: {
      x: {
        title: {
          display: true,
          text: TEXTS[lang].hours,
        },
      },
      y: {
        beginAtZero: true,
      },
    },
    interaction: {
      mode: 'nearest',
      axis: 'x',
      intersect: false,
    },
  };

  // Grafik yüksekliği için stil
  const chartStyle = {
    height: `${height}px`,
  };

  return (
    <div style={chartStyle}>
      <Line ref={chartRef} options={options} data={chartData} />
    </div>
  );
}

// Çoklu grafik bileşeni
interface MultiChartProps {
  data: ForecastData[];
  showBattery?: boolean;
}

export function MultiChart({ data, showBattery = false }: MultiChartProps) {
  if (!data || data.length === 0) {
    return <div>Veri yok</div>;
  }

  return (
    <div>
      <div className="chart-container">
        <ForecastChart data={data} type="revenue" title={TEXTS.en.revenue} showBattery={showBattery} />
      </div>
      <div className="chart-container">
        <ForecastChart data={data} type="co2" title={TEXTS.en.co2_saved} showBattery={showBattery} />
      </div>
      {showBattery && (
        <div className="chart-container">
          <ForecastChart data={data} type="soc" title={TEXTS.en.battery_soc} showBattery={true} />
        </div>
      )}
    </div>
  );
}
