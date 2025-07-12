import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from typing import List, Dict
import math

# Bağlantı pool'u uyarılarını gizle
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class CryptoScanner:
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.base_url = "https://api.binance.com"
        self.max_workers = 15  # Paralel çalışacak maksimum thread sayısı
        
        # HTTP Session ile bağlantı pool'u yönetimi
        self.session = requests.Session()
        
        # Retry stratejisi
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],  # method_whitelist yerine allowed_methods
            backoff_factor=1
        )
        
        # HTTP Adapter ile connection pool boyutunu artır
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=50,  # 10'dan 50'ye çıkar
            pool_maxsize=100,     # 10'dan 100'e çıkar
            pool_block=False
        )
        
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # Header ayarları
        self.session.headers.update({
            'User-Agent': 'CryptoScanner/1.0',
            'Accept': 'application/json',
            'Connection': 'keep-alive'
        })

    def get_all_usdt_pairs(self, custom_list=None):
        """USDT ile biten tüm çiftleri al veya özel listeyi kullan"""
        try:
            if custom_list:
                # Özel liste varsa, sadece geçerli USDT çiftlerini filtrele
                exchange_info = self.session.get(f"{self.base_url}/api/v3/exchangeInfo").json()
                valid_symbols = {s['symbol'] for s in exchange_info['symbols'] 
                               if s['symbol'].endswith('USDT') and s['status'] == 'TRADING'}
                
                # Özel listedeki sembolleri kontrol et ve geçerli olanları döndür
                return [symbol for symbol in custom_list if symbol in valid_symbols]
            
            # Özel liste yoksa tüm USDT çiftlerini al
            exchange_info = self.session.get(f"{self.base_url}/api/v3/exchangeInfo").json()
            symbols = [s['symbol'] for s in exchange_info['symbols'] 
                      if s['symbol'].endswith('USDT') and s['status'] == 'TRADING']
            return symbols
        except Exception as e:
            print(f"Hata: Çiftler alınamadı - {e}")
            return []

    def calculate_rsi(self, klines, length=13):
        """Verilen mumlar için RSI hesapla"""
        try:
            if not klines:
                return None
                
            # Kapanış fiyatlarını al ve DataFrame oluştur
            close_prices = pd.Series([float(k[4]) for k in klines])
            
            # RSI hesapla
            rsi = RSIIndicator(close=close_prices, window=length)
            return rsi.rsi().iloc[-1]  # Son RSI değerini döndür
            
        except Exception as e:
            print(f"Hata: RSI hesaplanamadı - {e}")
            return None

    def calculate_relative_volume(self, klines, lookback=20):
        """Göreceli hacim hesapla"""
        try:
            if not klines or len(klines) < lookback:
                return None
                
            # Hacimleri al
            volumes = pd.Series([float(k[5]) for k in klines])
            
            # Son hacim
            current_volume = volumes.iloc[-1]
            
            # Son 20 mumun ortalama hacmi
            avg_volume = volumes.iloc[-lookback:-1].mean()
            
            # Göreceli hacim (son hacim / ortalama hacim)
            relative_volume = current_volume / avg_volume if avg_volume > 0 else 0
            
            return relative_volume
            
        except Exception as e:
            print(f"Hata: Göreceli hacim hesaplanamadı - {e}")
            return None

    def calculate_percentage_change(self, klines):
        """Son mumun önceki muma göre yüzde değişimini hesapla"""
        try:
            if len(klines) < 2:
                return None
                
            # Son iki mumun kapanış fiyatlarını al
            current_close = float(klines[-1][4])  # Son mumun kapanış fiyatı
            previous_close = float(klines[-2][4])  # Önceki mumun kapanış fiyatı
            
            # Yüzde değişimi hesapla
            percentage_change = ((current_close - previous_close) / previous_close) * 100
            
            return percentage_change
            
        except Exception as e:
            print(f"Hata: Yüzde değişim hesaplanamadı - {e}")
            return None

    def aggregate_10min_candles(self, symbol: str, limit: int) -> List:
        """1 dakikalık mumları alıp 10 dakikalık mumlara dönüştür"""
        try:
            # 1 dakikalık mumları al (10 katı kadar al çünkü 10'arlı gruplar oluşturacağız)
            klines_1m = self.session.get(f"{self.base_url}/api/v3/klines", params={
                'symbol': symbol,
                'interval': '1m',
                'limit': limit * 10
            }).json()
            
            if not klines_1m:
                return []
            
            # DataFrame'e çevir
            df = pd.DataFrame(klines_1m)
            
            # Sütun isimlerini ayarla
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
                         'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 
                         'taker_buy_quote_asset_volume', 'ignore']
            
            # Veri tiplerini düzelt
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 10'ar dakikalık gruplar oluştur
            df['group'] = df.index // 10
            
            # Her grup için OHLCV değerlerini hesapla
            aggregated = df.groupby('group').agg({
                'timestamp': 'first',
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum',
                'close_time': 'last',
                'quote_asset_volume': 'sum',
                'number_of_trades': 'sum',
                'taker_buy_base_asset_volume': 'sum',
                'taker_buy_quote_asset_volume': 'sum',
                'ignore': 'last'
            }).reset_index(drop=True)
            
            # Son limit kadar mumu al
            aggregated = aggregated.tail(limit)
            
            # Listeye çevir
            return aggregated.values.tolist()
            
        except Exception as e:
            print(f"Hata: 10 dakikalık mumlar oluşturulamadı - {e}")
            return []

    def process_symbol_batch(self, symbols: List[str], timeframe: str, rsi_length: int, rsi_value: float, comparison: str, min_relative_volume: float = 0, min_volume: float = 0, min_percentage_change: float = 0) -> List[Dict]:
        """Sembol grubunu işle"""
        results = []
        binance_interval = {
            '1': '1m',
            '3': '3m', '5': '5m', '10': '10m', '15': '15m', '30': '30m'
        }.get(timeframe, '5m')
        
        for symbol in symbols:
            try:
                # Mumları al
                if timeframe == '10':
                    klines = self.aggregate_10min_candles(symbol, max(rsi_length * 3, 20))
                else:
                    klines = self.session.get(f"{self.base_url}/api/v3/klines", params={
                        'symbol': symbol,
                        'interval': binance_interval,
                        'limit': max(rsi_length * 3, 20)  # RSI ve göreceli hacim için yeterli veri
                    }).json()
                
                if len(klines) >= rsi_length * 3:
                    # Sadece gerekli hesaplamaları yap
                    result = {'symbol': symbol}
                    condition_met = True
                    
                    # RSI kontrolü
                    if rsi_value is not None:
                        rsi = self.calculate_rsi(klines, rsi_length)
                        if rsi is None:
                            condition_met = False
                        elif comparison == '≥':
                            condition_met = condition_met and (rsi >= float(rsi_value))
                        elif comparison == '≤':
                            condition_met = condition_met and (rsi <= float(rsi_value))
                        if condition_met and rsi is not None:
                            result['rsi'] = float(rsi)
                    
                    # Göreceli hacim kontrolü
                    if condition_met and min_relative_volume is not None and min_relative_volume > 0:
                        relative_volume = self.calculate_relative_volume(klines)
                        if relative_volume is None or relative_volume < min_relative_volume:
                            condition_met = False
                        elif relative_volume is not None:
                            result['relative_volume'] = float(relative_volume)
                    
                    # Hacim kontrolü
                    if condition_met and min_volume is not None and min_volume > 0:
                        last_volume = float(klines[-1][5])  # Coin hacmi
                        last_price = float(klines[-1][4])   # Kapanış fiyatı
                        volume_in_usdt = last_volume * last_price  # USDT cinsinden hacim
                        if volume_in_usdt < min_volume:
                            condition_met = False
                        else:
                            result['volume'] = float(volume_in_usdt)
                    
                    # Yüzde değişim kontrolü
                    if condition_met and min_percentage_change is not None and min_percentage_change > 0:
                        percentage_change = self.calculate_percentage_change(klines)
                        if percentage_change is None or percentage_change < min_percentage_change:
                            condition_met = False
                        elif percentage_change is not None:
                            result['percentage_change'] = float(percentage_change)
                    
                    if condition_met:
                        results.append(result)
            
            except Exception as e:
                print(f"\nHata ({symbol}): {str(e)}")
                continue
        
        return results

    def scan_market(self, timeframe, rsi_length, rsi_value, comparison, min_relative_volume=None, min_volume=None, min_percentage_change=None, closing_scan=False, coin_list=None):
        """Tüm piyasayı tara ve kriterlere uyan coinleri bul"""
        try:
            # Taranacak sembolleri al
            symbols = self.get_all_usdt_pairs(coin_list)
            total_symbols = len(symbols)
            
            print(f"\n{'='*80}")
            print(f"Tarama Başlatıldı - {time.strftime('%H:%M:%S')}")
            print(f"{'='*80}")
            print(f"Toplam {total_symbols} coin taranacak")
            print("\nTarama Ayarları:")
            print(f"- Zaman Aralığı: {timeframe} dakika")
            
            # Aktif filtreleri belirle
            active_filters = []
            header_columns = ['Sembol']
            if rsi_value is not None:
                active_filters.append(('RSI', f"RSI Periyodu: {rsi_length}\nRSI Değeri: {rsi_value}\nKarşılaştırma: {comparison}"))
                header_columns.append('RSI')
            if min_relative_volume is not None:
                active_filters.append(('Göreceli Hacim', f"Minimum Göreceli Hacim: {min_relative_volume}"))
                header_columns.append('Göreceli Hacim')
            if min_volume is not None:
                active_filters.append(('Hacim', f"Minimum Hacim: {min_volume} USDT"))
                header_columns.append('Hacim (USDT)')
            if min_percentage_change is not None:
                active_filters.append(('Değişim', f"Minimum Yüzde Değişim: %{min_percentage_change}"))
                header_columns.append('Değişim (%)')
            
            # Aktif filtreleri yazdır
            for _, filter_info in active_filters:
                print(f"- {filter_info}")
            
            header_columns.append('Saat')
            print(f"\n{'='*80}")
            
            # Sonuçları sakla
            all_results = []
            
            # Sembolleri gruplara böl
            batch_size = 20
            symbol_batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_batch = {
                    executor.submit(
                        self.process_symbol_batch, 
                        batch, timeframe, rsi_length, rsi_value, comparison,
                        min_relative_volume, min_volume, min_percentage_change
                    ): batch for batch in symbol_batches
                }
                
                completed = 0
                for future in as_completed(future_to_batch):
                    batch_results = future.result()
                    all_results.extend(batch_results)
                    completed += len(future_to_batch[future])
                    
                    # İlerleme durumunu göster
                    progress = (completed / total_symbols) * 100
                    print(f"\rİlerleme: {completed}/{total_symbols} ({progress:.1f}%)", end="", flush=True)
            
            print("\n")  # İlerleme çubuğundan sonra yeni satır
            
            if all_results:
                # Tablo başlığını yazdır
                print(f"{'='*100}")
                header_format = ""
                for col in header_columns[:-1]:  # Son sütun (Saat) hariç
                    if col == 'Sembol':
                        header_format += f"{col:<12} "
                    elif col == 'RSI':
                        header_format += f"{col:>7} "
                    else:
                        header_format += f"{col:>14} "
                header_format += f"{'Saat':>8}"
                print(header_format)
                print(f"{'-'*100}")
                
                # Her sonucu tablo formatında yazdır
                for result in all_results:
                    values = [result['symbol']]
                    format_str = "{:<12} "
                    
                    if 'RSI' in header_columns:
                        values.append(f"{result.get('rsi', 0):>7.2f}")
                        format_str += "{} "
                    if 'Hacim (USDT)' in header_columns:
                        values.append(f"{result.get('volume', 0):>14,.2f}")
                        format_str += "{} "
                    if 'Göreceli Hacim' in header_columns:
                        values.append(f"{result.get('relative_volume', 0):>14.2f}")
                        format_str += "{} "
                    if 'Değişim (%)' in header_columns:
                        values.append(f"{result.get('percentage_change', 0):>11.2f}%")
                        format_str += "{:>3} "
                    
                    values.append(time.strftime('%H:%M:%S'))
                    format_str += "{:>8}"
                    
                    print(format_str.format(*values))
                
                print(f"{'='*100}")
                print(f"\nTarama tamamlandı! {len(all_results)} coin bulundu. - {time.strftime('%H:%M:%S')}")
                print(f"{'='*100}\n")
            else:
                print("\nKriterlere uygun coin bulunamadı.")
            
            return all_results
            
        except Exception as e:
            print(f"Tarama hatası: {e}")
            return [] 