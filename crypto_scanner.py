from binance.client import Client
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
import math

class CryptoScanner:
    def __init__(self, socketio=None):
        # Binance API client - public endpoint kullanıyoruz
        self.client = Client()
        self.max_workers = 5  # Aynı anda çalışacak maksimum thread sayısı
        self.socketio = socketio  # WebSocket bağlantısı
        
    def get_all_usdt_pairs(self, custom_list=None):
        """USDT ile biten tüm çiftleri al veya özel listeyi kullan"""
        try:
            if custom_list:
                # Özel liste varsa, sadece geçerli USDT çiftlerini filtrele
                exchange_info = self.client.get_exchange_info()
                valid_symbols = {s['symbol'] for s in exchange_info['symbols'] 
                               if s['symbol'].endswith('USDT') and s['status'] == 'TRADING'}
                
                # Özel listedeki sembolleri kontrol et ve geçerli olanları döndür
                return [symbol for symbol in custom_list if symbol in valid_symbols]
            
            # Özel liste yoksa tüm USDT çiftlerini al
            exchange_info = self.client.get_exchange_info()
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
                
            # Kapanış fiyatlarını al
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
                                             'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 
                                             'taker_buy_quote_asset_volume', 'ignore'])
            
            # Kapanış fiyatlarını float'a çevir
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            
            # RSI hesapla
            rsi = RSIIndicator(close=df['close'], window=length)
            return rsi.rsi().iloc[-1]  # Son RSI değerini döndür
            
        except Exception as e:
            print(f"Hata: RSI hesaplanamadı - {e}")
            return None

    def calculate_relative_volume(self, klines, lookback=20):
        """Göreceli hacim hesapla"""
        try:
            if not klines or len(klines) < lookback:
                return None
                
            # Veriyi DataFrame'e çevir
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
                                             'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 
                                             'taker_buy_quote_asset_volume', 'ignore'])
            
            # Hacimleri float'a çevir
            df['volume'] = df['volume'].astype(float)
            
            # Son hacim
            current_volume = df['volume'].iloc[-1]
            
            # Son 20 mumun ortalama hacmi
            avg_volume = df['volume'].iloc[-lookback:-1].mean()
            
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
            klines_1m = self.client.get_klines(
                symbol=symbol,
                interval='1m',
                limit=limit * 10
            )
            
            if not klines_1m:
                return []
            
            # DataFrame'e çevir
            df = pd.DataFrame(klines_1m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
                                                'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 
                                                'taker_buy_quote_asset_volume', 'ignore'])
            
            # Veri tiplerini düzelt
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            
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
                    klines = self.client.get_klines(
                        symbol=symbol,
                        interval=binance_interval,
                        limit=max(rsi_length * 3, 20)  # RSI ve göreceli hacim için yeterli veri
                    )
                
                if len(klines) >= rsi_length * 3:
                    rsi = self.calculate_rsi(klines, rsi_length)
                    relative_volume = self.calculate_relative_volume(klines)
                    percentage_change = self.calculate_percentage_change(klines)
                    
                    # Son mumun hacmini USDT'ye çevir
                    last_volume = float(klines[-1][5])  # Coin hacmi
                    last_price = float(klines[-1][4])   # Kapanış fiyatı
                    volume_in_usdt = last_volume * last_price  # USDT cinsinden hacim
                    
                    # Koşulları kontrol et
                    condition_met = True
                    # RSI sadece aktifse kontrol edilecek
                    if rsi_value is not None:
                        if rsi is None:
                            condition_met = False
                        elif comparison == '≥':
                            condition_met = condition_met and (rsi >= float(rsi_value))
                        elif comparison == '≤':
                            condition_met = condition_met and (rsi <= float(rsi_value))
                    # Diğer filtreler de sadece aktifse kontrol edilecek
                    if min_relative_volume is not None:
                        if relative_volume is None or relative_volume < min_relative_volume:
                            condition_met = False
                    if min_volume is not None:
                        if volume_in_usdt < min_volume:
                            condition_met = False
                    if min_percentage_change is not None:
                        if percentage_change is None or percentage_change < min_percentage_change:
                            condition_met = False
                    
                    if condition_met:
                        result = {
                            'symbol': symbol,
                            'volume': round(volume_in_usdt, 2)
                        }
                        if rsi_value is not None and rsi is not None:
                            result['rsi'] = round(rsi, 2)
                        if min_relative_volume is not None and relative_volume is not None:
                            result['relative_volume'] = round(relative_volume, 2)
                        if min_percentage_change is not None and percentage_change is not None:
                            result['percentage_change'] = round(percentage_change, 2)
                        results.append(result)
                        # Eşleşen coini ilgili zaman aralığına özel event ile gönder
                        if self.socketio:
                            self.socketio.emit(f'match_found_{timeframe}', result)
                        print(f"\nEşleşme Bulundu! {symbol} -> " + \
                              (f"RSI: {round(rsi, 2)}, " if rsi_value is not None and rsi is not None else "") + \
                              (f"Göreceli Hacim: {round(relative_volume, 2)}, " if min_relative_volume is not None and relative_volume is not None else "") + \
                              f"Hacim: {round(volume_in_usdt, 2)} USDT, " + \
                              (f"Değişim: %{round(percentage_change, 2)}" if min_percentage_change is not None and percentage_change is not None else ""))
                
                time.sleep(0.02)  # Daha kısa bekleme süresi
                
            except Exception as e:
                print(f"\nHata: {symbol} taranırken hata oluştu - {e}")
                continue
                
        return results

    def scan_market(self, timeframe, rsi_length, rsi_value, comparison, min_relative_volume=0, min_volume=0, min_percentage_change=0, closing_scan=False, coin_list=None):
        """Piyasayı paralel olarak tara ve RSI koşulunu sağlayan çiftleri bul"""
        symbols = self.get_all_usdt_pairs(coin_list)
        total_symbols = len(symbols)
        if not symbols:
            return []
        print(f"\nToplam {total_symbols} coin taranacak")
        print("Tarama Ayarları:")
        print(f"- Zaman Aralığı: {timeframe} dakika")
        print(f"- RSI Periyodu: {rsi_length}")
        print(f"- RSI Değeri: {rsi_value}")
        print(f"- Karşılaştırma: {comparison}")
        print(f"- Minimum Göreceli Hacim: {min_relative_volume}")
        print(f"- Minimum Hacim: {min_volume} USDT")
        print(f"- Minimum Yüzde Değişim: %{min_percentage_change}")
        if coin_list:
            print(f"- Özel Coin Listesi: {len(coin_list)} coin")
        print("\nTarama başlıyor...\n")
        batch_size = math.ceil(total_symbols / self.max_workers)
        symbol_batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]
        all_results = []
        processed_count = 0
        last_progress_update = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_batch = {
                executor.submit(
                    self.process_symbol_batch, 
                    batch, 
                    timeframe, 
                    rsi_length, 
                    rsi_value, 
                    comparison,
                    min_relative_volume,
                    min_volume,
                    min_percentage_change
                ): batch for batch in symbol_batches
            }
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                processed_count += len(batch)
                try:
                    batch_results = future.result()
                    all_results.extend(batch_results)
                    current_progress = round(processed_count/total_symbols*100, 1)
                    if current_progress - last_progress_update >= 1:
                        progress = {
                            'current': processed_count,
                            'total': total_symbols,
                            'percentage': current_progress
                        }
                        if self.socketio:
                            self.socketio.emit(f'scan_progress_{timeframe}', progress)
                            last_progress_update = current_progress
                    print(f"\rİlerleme: {processed_count}/{total_symbols} "
                          f"({round(processed_count/total_symbols*100, 1)}%)", end="")
                except Exception as e:
                    print(f"\nHata: Batch işlenirken hata oluştu - {e}")
        if self.socketio:
            self.socketio.emit(f'scan_progress_{timeframe}', {
                'current': total_symbols,
                'total': total_symbols,
                'percentage': 100
            })
        print(f"\n\nTarama tamamlandı! {len(all_results)} coin bulundu.")
        if self.socketio:
            self.socketio.emit(f'scan_completed_{timeframe}', {
                'total_matches': len(all_results),
                'timeframe': timeframe
            })
        return all_results 