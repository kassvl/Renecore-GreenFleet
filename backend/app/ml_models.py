

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error
import joblib
from loguru import logger
import warnings
warnings.filterwarnings('ignore')

# NeuralForecast kütüphanelerini import et
try:
    from neuralforecast import NeuralForecast
    from neuralforecast.models import TFT, NBEATS, DeepAR, LSTM, GRU
    from neuralforecast.losses.pytorch import MAE, MSE, RMSE
    from neuralforecast.utils import AirPassengersDF
except ImportError:
    logger.warning("NeuralForecast kütüphanesi yüklenmedi. Pip install gerekebilir.")

# MLflow ve monitoring
try:
    import mlflow
    import mlflow.pytorch
    from evidently import ColumnMapping
    from evidently.report import Report
    from evidently.metric_preset import DataDriftPreset, TargetDriftPreset
except ImportError:
    logger.warning("MLflow veya Evidently kütüphanesi yüklenmedi.")

@dataclass
class ModelConfig:
    """Model konfigürasyon sınıfı"""
    model_name: str
    horizon: int = 168  # 7 gün * 24 saat
    input_size: int = 168  # 7 günlük geçmiş
    hidden_size: int = 256
    num_layers: int = 3
    dropout: float = 0.1
    learning_rate: float = 0.001
    batch_size: int = 32
    max_epochs: int = 100
    patience: int = 10
    
class AdvancedFeatureEngineer:
    """Gelişmiş özellik mühendisliği sınıfı"""
    
    def __init__(self):
        self.scalers = {}
        self.encoders = {}
        self.fitted = False
        
    def create_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Zaman tabanlı özellikler oluşturur"""
        df = df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Temel zaman özellikleri
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek
        df['day_of_month'] = df['timestamp'].dt.day
        df['month'] = df['timestamp'].dt.month
        df['quarter'] = df['timestamp'].dt.quarter
        df['year'] = df['timestamp'].dt.year
        
        # Döngüsel özellikler (sinüs/kosinüs)
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
        df['day_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
        df['day_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
        df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
        df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
        
        # Tatil ve özel günler
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        df['is_business_hour'] = ((df['hour'] >= 8) & (df['hour'] <= 18)).astype(int)
        df['is_peak_hour'] = ((df['hour'] >= 17) & (df['hour'] <= 21)).astype(int)
        
        return df
    
    def create_lag_features(self, df: pd.DataFrame, target_col: str, lags: List[int]) -> pd.DataFrame:
        """Gecikmeli özellikler oluşturur"""
        df = df.copy()
        df = df.sort_values('timestamp')
        
        for lag in lags:
            df[f'{target_col}_lag_{lag}'] = df[target_col].shift(lag)
            
        return df
    
    def create_rolling_features(self, df: pd.DataFrame, target_col: str, windows: List[int]) -> pd.DataFrame:
        """Hareketli ortalama özellikleri oluşturur"""
        df = df.copy()
        df = df.sort_values('timestamp')
        
        for window in windows:
            df[f'{target_col}_rolling_mean_{window}'] = df[target_col].rolling(window=window).mean()
            df[f'{target_col}_rolling_std_{window}'] = df[target_col].rolling(window=window).std()
            df[f'{target_col}_rolling_min_{window}'] = df[target_col].rolling(window=window).min()
            df[f'{target_col}_rolling_max_{window}'] = df[target_col].rolling(window=window).max()
            
        return df
    
    def create_weather_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Hava durumu tabanlı özellikler oluşturur"""
        df = df.copy()
        
        if 'wind_speed' in df.columns:
            # Rüzgar güç eğrisi özellikleri
            df['wind_power_theoretical'] = np.where(
                (df['wind_speed'] >= 3) & (df['wind_speed'] <= 25),
                np.minimum(((df['wind_speed'] - 3) / 9) ** 3, 1.0),
                0.0
            )
            
            # Rüzgar kategorileri
            df['wind_category'] = pd.cut(
                df['wind_speed'], 
                bins=[0, 3, 7, 12, 18, 25, 100], 
                labels=['calm', 'light', 'moderate', 'strong', 'very_strong', 'extreme']
            )
            
        if 'ghi' in df.columns:
            # Güneş radyasyonu özellikleri
            df['solar_power_theoretical'] = np.maximum(df['ghi'] / 1000, 0) * 0.2 * 0.85
            
            # Güneş kategorileri
            df['solar_category'] = pd.cut(
                df['ghi'], 
                bins=[0, 100, 300, 600, 800, 1200], 
                labels=['very_low', 'low', 'moderate', 'high', 'very_high']
            )
            
        return df
    
    def fit_transform(self, df: pd.DataFrame, target_cols: List[str]) -> pd.DataFrame:
        """Tüm özellikleri oluşturur ve ölçeklendirir"""
        df_processed = df.copy()
        
        # Zaman özellikleri
        df_processed = self.create_time_features(df_processed)
        
        # Hava durumu özellikleri
        df_processed = self.create_weather_features(df_processed)
        
        # Lag özellikleri
        lags = [1, 3, 6, 12, 24, 48, 168]  # 1h, 3h, 6h, 12h, 1d, 2d, 1w
        for target_col in target_cols:
            if target_col in df_processed.columns:
                df_processed = self.create_lag_features(df_processed, target_col, lags)
        
        # Rolling özellikleri
        windows = [3, 6, 12, 24, 48, 168]
        for target_col in target_cols:
            if target_col in df_processed.columns:
                df_processed = self.create_rolling_features(df_processed, target_col, windows)
        
        # Kategorik değişkenleri encode et
        categorical_cols = ['wind_category', 'solar_category']
        for col in categorical_cols:
            if col in df_processed.columns:
                if col not in self.encoders:
                    self.encoders[col] = LabelEncoder()
                    df_processed[col] = self.encoders[col].fit_transform(df_processed[col].astype(str))
                else:
                    df_processed[col] = self.encoders[col].transform(df_processed[col].astype(str))
        
        # Sayısal değişkenleri ölçeklendir
        numeric_cols = df_processed.select_dtypes(include=[np.number]).columns
        numeric_cols = [col for col in numeric_cols if col not in ['site_id', 'id']]
        
        for col in numeric_cols:
            if col not in self.scalers:
                self.scalers[col] = StandardScaler()
                df_processed[col] = self.scalers[col].fit_transform(df_processed[[col]])
            else:
                df_processed[col] = self.scalers[col].transform(df_processed[[col]])
        
        self.fitted = True
        return df_processed
    
    def transform(self, df: pd.DataFrame, target_cols: List[str]) -> pd.DataFrame:
        """Önceden fit edilmiş transformerları kullanarak dönüştürür"""
        if not self.fitted:
            raise ValueError("FeatureEngineer önce fit edilmelidir!")
        
        df_processed = df.copy()
        
        # Zaman özellikleri
        df_processed = self.create_time_features(df_processed)
        
        # Hava durumu özellikleri
        df_processed = self.create_weather_features(df_processed)
        
        # Lag özellikleri
        lags = [1, 3, 6, 12, 24, 48, 168]
        for target_col in target_cols:
            if target_col in df_processed.columns:
                df_processed = self.create_lag_features(df_processed, target_col, lags)
        
        # Rolling özellikleri
        windows = [3, 6, 12, 24, 48, 168]
        for target_col in target_cols:
            if target_col in df_processed.columns:
                df_processed = self.create_rolling_features(df_processed, target_col, windows)
        
        # Kategorik değişkenleri encode et
        categorical_cols = ['wind_category', 'solar_category']
        for col in categorical_cols:
            if col in df_processed.columns and col in self.encoders:
                df_processed[col] = self.encoders[col].transform(df_processed[col].astype(str))
        
        # Sayısal değişkenleri ölçeklendir
        numeric_cols = df_processed.select_dtypes(include=[np.number]).columns
        numeric_cols = [col for col in numeric_cols if col not in ['site_id', 'id']]
        
        for col in numeric_cols:
            if col in self.scalers:
                df_processed[col] = self.scalers[col].transform(df_processed[[col]])
        
        return df_processed

class EnsembleForecaster:
    """Ensemble tahmin modeli - TFT, N-BEATS, DeepAR kombinasyonu"""
    
    def __init__(self, config: ModelConfig):
        self.config = config
        self.models = {}
        self.feature_engineer = AdvancedFeatureEngineer()
        self.is_fitted = False
        
        # Model ağırlıkları (ensemble için)
        self.model_weights = {
            'tft': 0.4,
            'nbeats': 0.3,
            'deepar': 0.3
        }
        
    def _prepare_data_for_neuralforecast(self, df: pd.DataFrame, target_col: str) -> pd.DataFrame:
        """NeuralForecast için veri formatını hazırlar"""
        df_nf = df.copy()
        df_nf = df_nf.rename(columns={
            'timestamp': 'ds',
            target_col: 'y',
            'site_id': 'unique_id'
        })
        
        # Eksik unique_id varsa oluştur
        if 'unique_id' not in df_nf.columns:
            df_nf['unique_id'] = 1
        
        # Gerekli sütunları seç
        required_cols = ['unique_id', 'ds', 'y']
        available_cols = [col for col in required_cols if col in df_nf.columns]
        
        return df_nf[available_cols]
    
    def fit(self, df: pd.DataFrame, target_col: str = 'power_mw') -> None:
        """Ensemble modeli eğitir"""
        logger.info(f"Ensemble model eğitimi başlıyor - Target: {target_col}")
        
        # Feature engineering
        df_processed = self.feature_engineer.fit_transform(df, [target_col])
        
        # NeuralForecast formatına dönüştür
        df_nf = self._prepare_data_for_neuralforecast(df_processed, target_col)
        
        try:
            # Model tanımları
            models = [
                TFT(
                    h=self.config.horizon,
                    input_size=self.config.input_size,
                    hidden_size=self.config.hidden_size,
                    n_head=8,
                    dropout=self.config.dropout,
                    max_epochs=self.config.max_epochs,
                    batch_size=self.config.batch_size,
                    learning_rate=self.config.learning_rate,
                    early_stop_patience_steps=self.config.patience,
                    loss=MAE(),
                    alias='TFT'
                ),
                NBEATS(
                    h=self.config.horizon,
                    input_size=self.config.input_size,
                    max_epochs=self.config.max_epochs,
                    batch_size=self.config.batch_size,
                    learning_rate=self.config.learning_rate,
                    early_stop_patience_steps=self.config.patience,
                    loss=MAE(),
                    alias='NBEATS'
                ),
                DeepAR(
                    h=self.config.horizon,
                    input_size=self.config.input_size,
                    hidden_size=self.config.hidden_size,
                    max_epochs=self.config.max_epochs,
                    batch_size=self.config.batch_size,
                    learning_rate=self.config.learning_rate,
                    early_stop_patience_steps=self.config.patience,
                    loss=MAE(),
                    alias='DeepAR'
                )
            ]
            
            # NeuralForecast objesi oluştur
            self.nf = NeuralForecast(models=models, freq='H')
            
            # Modeli eğit
            self.nf.fit(df_nf)
            
            self.is_fitted = True
            logger.info("Ensemble model eğitimi tamamlandı!")
            
        except Exception as e:
            logger.error(f"Model eğitimi hatası: {str(e)}")
            # Fallback: Basit LSTM modeli
            self._fit_fallback_model(df_processed, target_col)
    
    def _fit_fallback_model(self, df: pd.DataFrame, target_col: str) -> None:
        """Basit LSTM fallback modeli"""
        logger.info("Fallback LSTM modeli eğitiliyor...")
        
        df_nf = self._prepare_data_for_neuralforecast(df, target_col)
        
        models = [
            LSTM(
                h=self.config.horizon,
                input_size=self.config.input_size,
                hidden_size=128,
                max_epochs=50,
                batch_size=self.config.batch_size,
                learning_rate=self.config.learning_rate,
                alias='LSTM_Fallback'
            )
        ]
        
        self.nf = NeuralForecast(models=models, freq='H')
        self.nf.fit(df_nf)
        self.is_fitted = True
        
    def predict(self, df: pd.DataFrame, target_col: str = 'power_mw') -> pd.DataFrame:
        """7 günlük tahmin yapar"""
        if not self.is_fitted:
            raise ValueError("Model önce eğitilmelidir!")
        
        # Feature engineering (transform only)
        df_processed = self.feature_engineer.transform(df, [target_col])
        
        # NeuralForecast formatına dönüştür
        df_nf = self._prepare_data_for_neuralforecast(df_processed, target_col)
        
        # Tahmin yap
        forecasts = self.nf.predict(df_nf)
        
        # Sonuçları düzenle
        forecast_df = forecasts.reset_index()
        
        # Zaman damgalarını oluştur
        last_timestamp = df['timestamp'].max()
        future_timestamps = pd.date_range(
            start=last_timestamp + timedelta(hours=1),
            periods=self.config.horizon,
            freq='H'
        )
        
        # Sonuç DataFrame'i oluştur
        result_df = pd.DataFrame({
            'timestamp': future_timestamps,
            'predicted_power_mw': forecast_df.iloc[:, -1].values  # Son sütun tahmin
        })
        
        return result_df
    
    def evaluate(self, df_test: pd.DataFrame, target_col: str = 'power_mw') -> Dict[str, float]:
        """Model performansını değerlendirir"""
        if not self.is_fitted:
            raise ValueError("Model önce eğitilmelidir!")
        
        # Test verisi üzerinde tahmin yap
        predictions = self.predict(df_test, target_col)
        
        # Gerçek değerlerle karşılaştır
        actual = df_test[target_col].values[-len(predictions):]
        predicted = predictions['predicted_power_mw'].values
        
        # Metrikleri hesapla
        mae = mean_absolute_error(actual, predicted)
        mse = mean_squared_error(actual, predicted)
        rmse = np.sqrt(mse)
        mape = np.mean(np.abs((actual - predicted) / actual)) * 100
        
        metrics = {
            'MAE': mae,
            'MSE': mse,
            'RMSE': rmse,
            'MAPE': mape
        }
        
        logger.info(f"Model Performansı: {metrics}")
        return metrics
    
    def save_model(self, path: str) -> None:
        """Modeli kaydeder"""
        model_data = {
            'config': self.config,
            'feature_engineer': self.feature_engineer,
            'model_weights': self.model_weights,
            'is_fitted': self.is_fitted
        }
        
        joblib.dump(model_data, f"{path}/ensemble_model.pkl")
        
        # NeuralForecast modelini kaydet
        if hasattr(self, 'nf'):
            self.nf.save(path=f"{path}/neural_forecast_models")
        
        logger.info(f"Model kaydedildi: {path}")
    
    def load_model(self, path: str) -> None:
        """Modeli yükler"""
        model_data = joblib.load(f"{path}/ensemble_model.pkl")
        
        self.config = model_data['config']
        self.feature_engineer = model_data['feature_engineer']
        self.model_weights = model_data['model_weights']
        self.is_fitted = model_data['is_fitted']
        
        # NeuralForecast modelini yükle
        try:
            self.nf = NeuralForecast.load(path=f"{path}/neural_forecast_models")
        except:
            logger.warning("NeuralForecast modeli yüklenemedi")
        
        logger.info(f"Model yüklendi: {path}")

# Model fabrikası
class ModelFactory:
    """Model oluşturma fabrikası"""
    
    @staticmethod
    def create_model(model_type: str, config: ModelConfig) -> EnsembleForecaster:
        """Belirtilen tipte model oluşturur"""
        if model_type == "ensemble":
            return EnsembleForecaster(config)
        else:
            raise ValueError(f"Desteklenmeyen model tipi: {model_type}")
    
    @staticmethod
    def get_default_config() -> ModelConfig:
        """Varsayılan model konfigürasyonu"""
        return ModelConfig(
            model_name="RenecoreML_v1",
            horizon=168,  # 7 gün
            input_size=168,  # 7 günlük geçmiş
            hidden_size=256,
            num_layers=3,
            dropout=0.1,
            learning_rate=0.001,
            batch_size=32,
            max_epochs=100,
            patience=10
        )

# Kullanım örneği
if __name__ == "__main__":
    # Test verisi oluştur
    dates = pd.date_range(start='2024-01-01', end='2024-12-31', freq='H')
    test_data = pd.DataFrame({
        'timestamp': dates,
        'site_id': 1,
        'wind_speed': np.random.normal(8, 3, len(dates)),
        'ghi': np.maximum(np.random.normal(400, 200, len(dates)), 0),
        'power_mw': np.random.normal(2.5, 1.2, len(dates)),
        'price_eur_mwh': np.random.normal(50, 15, len(dates))
    })
    
    # Model oluştur ve eğit
    config = ModelFactory.get_default_config()
    model = ModelFactory.create_model("ensemble", config)
    
    # Eğitim
    train_data = test_data[:-168]  # Son 7 günü test için ayır
    model.fit(train_data, target_col='power_mw')
    
    # Tahmin
    predictions = model.predict(train_data, target_col='power_mw')
    print("Tahmin tamamlandı!")
    print(predictions.head())
