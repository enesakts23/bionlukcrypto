from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from crypto_scanner import CryptoScanner
from flask_socketio import SocketIO
from waitress import serve
import logging
import sys
import os
import threading
import time
import json
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix
import requests  # Telegram API için requests kütüphanesi
import subprocess
import signal

# Telegram Bot Konfigürasyonu
TELEGRAM_BOT_TOKEN = "8136016388:AAEfuAAaFPTBIGWReXzsta3C1VrA7lgkM80"
TELEGRAM_CHANNEL_ID = "@kriptotaramaoto"  # Telegram kanal ID'si

def load_parameters():
    try:
        if os.path.exists('parameters.json'):
            with open('parameters.json', 'r') as f:
                return json.load(f)
    except Exception as e:
        logging.error(f"Parametre yükleme hatası: {str(e)}")
    return None

def save_parameters(params):
    try:
        with open('parameters.json', 'w') as f:
            json.dump(params, f, indent=4)
    except Exception as e:
        logging.error(f"Parametre kaydetme hatası: {str(e)}")

def send_telegram_message(message):
    """Telegram kanalına mesaj gönderen yardımcı fonksiyon"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logging.error("Telegram bot token veya kanal ID'si ayarlanmamış!")
        return
        
    try:
        # Mesajı parçalara böl (maksimum 30 coin her mesajda)
        lines = message.split("\n")
        header_lines = []
        result_lines = []
        footer_lines = []
        
        # Mesajı bölümlere ayır
        in_results = False
        for line in lines:
            if line.startswith("📊 Sonuçlar"):
                in_results = True
                header_lines.append(line)
            elif line.startswith("🎯 Bu bölümde"):
                in_results = False
                footer_lines.append(line)
            elif in_results and line.startswith("💰"):
                result_lines.append(line)
            else:
                if not in_results:
                    header_lines.append(line)
        
        # Eğer sonuç yoksa, tüm mesajı tek parça olarak gönder
        if not result_lines:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=data)
            if response.status_code != 200:
                logging.error(f"Telegram API hata kodu: {response.status_code}")
                logging.error(f"Telegram API yanıtı: {response.text}")
            return
            
        # Sonuçları gruplara böl
        chunk_size = 30
        result_chunks = [result_lines[i:i + chunk_size] for i in range(0, len(result_lines), chunk_size)]
        
        # Her grup için mesaj oluştur ve gönder
        for i, chunk in enumerate(result_chunks, 1):
            # Header'ı ekle
            chunk_message = "\n".join(header_lines) + "\n"
            
            # Bölüm bilgisini ekle
            if len(result_chunks) > 1:
                chunk_message += f"(Bölüm {i}/{len(result_chunks)})\n"
            
            # Sonuçları ekle
            chunk_message += "\n".join(chunk) + "\n"
            
            # Footer'ı ekle (son chunk için)
            if i == len(result_chunks):
                chunk_message += "\n" + "\n".join(footer_lines)
            else:
                chunk_message += f"\n🎯 Bu bölümde {len(chunk)} coin bulundu (Devamı var...)"
            
            # Mesajı gönder
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": chunk_message,
                "parse_mode": "HTML"
            }
            
            try:
                response = requests.post(url, json=data)
                if response.status_code != 200:
                    logging.error(f"Telegram API hata kodu: {response.status_code}")
                    logging.error(f"Telegram API yanıtı: {response.text}")
                    continue
                
                # Mesajlar arası 1 saniye bekle
                if i < len(result_chunks):
                    time.sleep(1)
                    
            except Exception as e:
                logging.error(f"Telegram mesajı gönderilirken hata oluştu (Bölüm {i}): {str(e)}")
                continue
            
    except Exception as e:
        logging.error(f"Telegram mesajı hazırlanırken hata oluştu: {str(e)}")
        logging.exception("Tam hata detayı:")

# Loglama ayarları
logging.basicConfig(
    filename='crypto_scanner.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Flask uygulamasını oluştur
app = Flask(__name__, static_url_path='')

# IIS reverse proxy desteği
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# CORS ayarlarını tüm originlere izin verecek şekilde güncelle
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# WebSocket desteği ekle - WebSocket protokol hatalarını önlemek için yapılandırma
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    # WebSocket protokol hatalarını önlemek için sadece polling kullan
    transports=['polling'],
    ping_timeout=30,  # Azaltıldı
    ping_interval=15,  # Azaltıldı
    always_connect=True,
    reconnection=True,
    reconnection_attempts=10,  # Frontend ile uyumlu
    reconnection_delay=2000,  # Frontend ile uyumlu
    reconnection_delay_max=10000,  # Frontend ile uyumlu
    logger=False,
    engineio_logger=False,
    # WebSocket upgrade'i tamamen devre dışı bırak
    upgrade=False,
    compression=False,  # Compression'u devre dışı bırak
    allow_upgrades=False  # Upgrade'leri tamamen engelle
)

# CryptoScanner instance'ı oluştur
scanner = CryptoScanner(socketio)

# Son tarama sonuçlarını sakla
last_scan_results = []

# Otomatik tarama için global değişkenler
auto_scan_threads = {}
stop_auto_scan = {}
active_scan_params = {}  # Her client için aktif tarama parametrelerini sakla

def auto_scan_worker(timeframes, scan_params, client_id):
    """Otomatik tarama işlemini gerçekleştiren worker fonksiyonu"""
    logging.info(f"AUTO SCAN WORKER BAŞLATILDI - Client: {client_id}")
    logging.info(f"Başlatılan tarama parametreleri: {scan_params}")
    logging.info(f"Seçili zaman aralıkları: {timeframes}")
    
    # Timeframe'leri integer'a çevir ve sırala
    timeframes = sorted([int(tf) for tf in timeframes])
    
    # Son tarama zamanlarını takip et
    last_scan_times = {tf: 0 for tf in timeframes}
    
    scan_count = 0
    consecutive_errors = 0
    max_consecutive_errors = 10  # Hata toleransını artır
    emit_errors = 0
    max_emit_errors = 15  # Emit hataları için ayrı sayaç
    
    while not stop_auto_scan.get(client_id, False):
        try:
            now = datetime.now()
            current_minute = now.minute
            current_second = now.second
            current_timestamp = now.timestamp()
            
            # Her 30 saniyede bir yaşam belirtisi gönder
            if current_second % 30 == 0:
                try:
                    logging.info(f"AUTO SCAN WORKER YAŞIYOR - Client: {client_id}, Saat: {now.strftime('%H:%M:%S')}")
                    socketio.emit('auto_scan_heartbeat', {
                        'message': f'Otomatik tarama aktif - {now.strftime("%H:%M:%S")}',
                        'scan_count': scan_count
                    }, room=client_id)
                    emit_errors = 0
                except Exception as emit_error:
                    emit_errors += 1
                    logging.warning(f"Heartbeat gönderilemedi - Client: {client_id}, Emit Hata: {emit_errors}/{max_emit_errors}, Hata: {str(emit_error)}")
                    if emit_errors >= max_emit_errors:
                        logging.warning(f"Çok fazla emit hatası - Emit gönderimini geçici olarak durdur - Client: {client_id}")
                        emit_errors = 0
            
            # Her timeframe için kontrol et
            for timeframe in timeframes:
                if stop_auto_scan.get(client_id, False):
                    break
                    
                # Mum kapanışını kontrol et
                should_scan = False
                
                if timeframe == 1:
                    should_scan = current_second == 0
                elif timeframe == 3:
                    should_scan = current_minute % 3 == 0 and current_second == 0
                elif timeframe == 5:
                    should_scan = current_minute % 5 == 0 and current_second == 0
                elif timeframe == 10:
                    should_scan = current_minute % 10 == 0 and current_second == 0
                elif timeframe == 15:
                    should_scan = current_minute % 15 == 0 and current_second == 0
                elif timeframe == 30:
                    should_scan = current_minute % 30 == 0 and current_second == 0
                
                time_since_last = current_timestamp - last_scan_times[timeframe]
                min_interval = timeframe * 60 - 10  # 10 saniye tolerans
                
                if should_scan and time_since_last >= min_interval:
                    try:
                        logging.info(f"TARAMA BAŞLATILIYOR - {timeframe} dakika, Client: {client_id}, Saat: {now.strftime('%H:%M:%S')}")
                        last_scan_times[timeframe] = current_timestamp
                        scan_count += 1
                        consecutive_errors = 0
                        
                        # Tarama parametrelerini kopyala
                        current_scan_params = scan_params.copy()
                        
                        results = scanner.scan_market(
                            timeframe=str(timeframe),
                            rsi_length=current_scan_params['rsi_length'],
                            rsi_value=current_scan_params['rsi_value'],
                            comparison=current_scan_params['comparison'],
                            min_relative_volume=current_scan_params['min_relative_volume'],
                            min_volume=current_scan_params['min_volume'],
                            min_percentage_change=current_scan_params['min_percentage_change'],
                            closing_scan=True,
                            coin_list=current_scan_params['coin_list']
                        )
                        
                        # Telegram mesajını hazırla
                        telegram_message = f"🔍 <b>{timeframe} Dakikalık Tarama Sonuçları</b>\n"
                        telegram_message += f"⏰ <i>{now.strftime('%H:%M:%S')}</i>\n\n"
                        
                        # Aktif filtreleri belirle
                        active_filters = {
                            'rsi': current_scan_params['rsi_value'] is not None,
                            'relative_volume': current_scan_params['min_relative_volume'] is not None,
                            'volume': current_scan_params['min_volume'] is not None,
                            'percentage_change': current_scan_params['min_percentage_change'] is not None
                        }
                        
                        # Filtre bilgilerini ekle
                        telegram_message += "🎯 Aktif Filtreler:\n"
                        filters_added = False
                        
                        if active_filters['rsi']:
                            telegram_message += f"• RSI Periyodu: {current_scan_params['rsi_length']}\n"
                            telegram_message += f"• RSI {current_scan_params['comparison']} {current_scan_params['rsi_value']}\n"
                            filters_added = True
                        if active_filters['relative_volume']:
                            telegram_message += f"• Göreceli Hacim ≥ {current_scan_params['min_relative_volume']}x\n"
                            filters_added = True
                        if active_filters['volume']:
                            telegram_message += f"• Minimum Hacim ≥ {current_scan_params['min_volume']} USDT\n"
                            filters_added = True
                        if active_filters['percentage_change']:
                            telegram_message += f"• Minimum Değişim ≥ %{current_scan_params['min_percentage_change']}\n"
                            filters_added = True
                        
                        if not filters_added:
                            telegram_message += "• Filtre seçilmedi\n"
                        
                        # Tarama parametrelerini ekle
                        telegram_message += "\n📊 Tarama Parametreleri:\n"
                        telegram_message += f"• Zaman Dilimi: {timeframe} dakika\n"
                        if current_scan_params['coin_list']:
                            telegram_message += f"• Liste Modu: Özel Liste ({len(current_scan_params['coin_list'])} coin)\n"
                        else:
                            telegram_message += "• Liste Modu: Tüm Coinler\n"
                        
                        if results:
                            telegram_message += "\n📊 Sonuçlar:\n"
                            
                            for result in results:
                                telegram_coin_info = [f"💰 <b>{result['symbol']}</b>"]
                                
                                if active_filters['rsi'] and 'rsi' in result:
                                    telegram_coin_info.append(f"RSI: {result['rsi']:.2f}")
                                
                                if active_filters['relative_volume'] and 'relative_volume' in result:
                                    telegram_coin_info.append(f"Göreceli Hacim: {result['relative_volume']:.2f}x")
                                
                                if active_filters['volume'] and 'volume' in result:
                                    telegram_coin_info.append(f"Hacim: {result['volume']:.2f}")
                                
                                if active_filters['percentage_change'] and 'percentage_change' in result:
                                    telegram_coin_info.append(f"Değişim: %{result['percentage_change']:.2f}")
                                
                                telegram_message += " | ".join(telegram_coin_info) + "\n"
                            
                            telegram_message += f"\n🎯 Bu bölümde {len(results)} coin, toplam {len(results)} coin bulundu."
                        else:
                            telegram_message += "\n❌ Filtre kriterlerine uygun coin bulunamadı."
                        
                        # Telegram'a gönder
                        send_telegram_message(telegram_message)
                        
                    except Exception as scan_error:
                        consecutive_errors += 1
                        logging.error(f"Tarama hatası - {timeframe} dakika, Client: {client_id}, Genel Hata: {consecutive_errors}/{max_consecutive_errors}, Hata: {str(scan_error)}")
                        if consecutive_errors >= max_consecutive_errors:
                            logging.error(f"Çok fazla ardışık tarama hatası - Worker durduruluyor - Client: {client_id}")
                            break
            
            # Her döngüde 1 saniye bekle
            time.sleep(1)
            
        except Exception as general_error:
            consecutive_errors += 1
            logging.error(f"Worker genel hatası - Client: {client_id}, Genel Hata: {consecutive_errors}/{max_consecutive_errors}, Hata: {str(general_error)}")
            if consecutive_errors >= max_consecutive_errors:
                logging.error(f"Çok fazla ardışık genel hata - Worker durduruluyor - Client: {client_id}")
                break
            time.sleep(2)
    
    # Worker sonlandırılıyor
    logging.info(f"AUTO SCAN WORKER SONLANDI - Client: {client_id}, Toplam tarama: {scan_count}")
    
    # Thread'i temizle
    if client_id in auto_scan_threads:
        del auto_scan_threads[client_id]
    if client_id in stop_auto_scan:
        del stop_auto_scan[client_id]

@socketio.on('start_auto_scan')
def handle_auto_scan(data):
    """Otomatik taramayı başlat"""
    try:
        client_id = request.sid
        if not client_id:
            raise ValueError("Client ID bulunamadı!")
            
        timeframes = data.get('times', [])
        filter_states = data.get('filterStates', {})
        
        logging.info(f"Gelen veri: {data}")
        logging.info(f"Client bağlantı ID'si: {client_id}")
        
        # TÜM aktif taramaları durdur
        logging.info("Tüm aktif taramaları durdurma başlatılıyor...")
        
        # Thread'leri güvenli bir şekilde durdur
        threads_to_stop = list(auto_scan_threads.keys())
        for cid in threads_to_stop:
            try:
                logging.info(f"Tarama durduruluyor - Client: {cid}")
                stop_auto_scan[cid] = True
                
                if cid in auto_scan_threads:
                    thread = auto_scan_threads[cid]
                    if thread and thread.is_alive():
                        thread.join(timeout=5)
                        if thread.is_alive():
                            logging.warning(f"Thread {cid} zamanında durdurulamadı!")
                    
                    # Thread referanslarını temizle
                    del auto_scan_threads[cid]
                
                if cid in stop_auto_scan:
                    del stop_auto_scan[cid]
                if cid in active_scan_params:
                    del active_scan_params[cid]
                
                logging.info(f"Eski tarama durduruldu - Client: {cid}")
            except Exception as thread_error:
                logging.error(f"Thread durdurma hatası - Client: {cid}, Hata: {str(thread_error)}")
                continue
        
        # RSI değerini belirle (RSI1 veya RSI2'den hangisi aktifse)
        rsi_value = None
        if filter_states.get('rsi1') and data.get('rsi1'):
            rsi_value = float(data['rsi1'])
        elif filter_states.get('rsi2') and data.get('rsi2'):
            rsi_value = float(data['rsi2'])
        
        # Tarama parametrelerini hazırla
        scan_params = {
            'rsi_length': 13,
            'rsi_value': rsi_value,
            'comparison': data.get('comparison', '≥'),
            'min_relative_volume': float(data['hacim']) if filter_states.get('hacim') and data.get('hacim') else None,
            'min_volume': float(data['volume']) if filter_states.get('volume') and data.get('volume') else None,
            'min_percentage_change': float(data['artis']) if filter_states.get('artis') and data.get('artis') else None,
            'closing_scan': True,
            'coin_list': data.get('coinList')
        }
        
        # Yeni parametreleri sakla
        active_scan_params[client_id] = {
            'times': timeframes,
            'filterStates': filter_states,
            'rsi1': data.get('rsi1'),
            'rsi2': data.get('rsi2'),
            'comparison': data.get('comparison', '≥'),
            'hacim': data.get('hacim'),
            'volume': data.get('volume'),
            'artis': data.get('artis'),
            'coinList': data.get('coinList')
        }
        
        # Log parametreleri
        logging.info(f"Hazırlanan yeni tarama parametreleri: {scan_params}")
        
        # Aktif filtreleri belirle
        active_filters = []
        if scan_params['rsi_value'] is not None:
            active_filters.append(f"RSI {scan_params['comparison']} {scan_params['rsi_value']}")
        if scan_params['min_relative_volume'] is not None:
            active_filters.append(f"Göreceli Hacim > {scan_params['min_relative_volume']}")
        if scan_params['min_volume'] is not None:
            active_filters.append(f"Hacim > {scan_params['min_volume']}")
        if scan_params['min_percentage_change'] is not None:
            active_filters.append(f"Değişim > %{scan_params['min_percentage_change']}")
        
        # Yeni taramayı başlat
        stop_auto_scan[client_id] = False
        auto_scan_threads[client_id] = threading.Thread(
            target=auto_scan_worker,
            args=(timeframes, scan_params.copy(), client_id)  # scan_params'ın bir kopyasını gönder
        )
        auto_scan_threads[client_id].daemon = True
        auto_scan_threads[client_id].start()
        
        logging.info(f"Yeni tarama başlatıldı - Client: {client_id}, Thread ID: {auto_scan_threads[client_id].ident}")
        
        # Başlangıç mesajı
        start_message = f'Otomatik tarama başlatıldı.\n'
        start_message += f'Seçili zaman aralıkları: {", ".join(timeframes)} dakika\n'
        
        # Zamanlama bilgilerini ekle
        now = datetime.now()
        start_message += f'Başlatılma zamanı: {now.strftime("%H:%M:%S")}\n'
        start_message += 'Tarama zamanları:\n'
        
        for tf in sorted([int(t) for t in timeframes]):
            current_minute = now.minute
            if tf == 1:
                next_scan = (current_minute + 1) % 60
                start_message += f'- {tf} dk: Her dakika (bir sonraki: {next_scan:02d}. dakika)\n'
            elif tf == 3:
                next_scan = ((current_minute // 3) + 1) * 3
                if next_scan >= 60:
                    next_scan = 0
                start_message += f'- {tf} dk: 0,3,6,9... dakikalarda (bir sonraki: {next_scan:02d}. dakika)\n'
            elif tf == 5:
                next_scan = ((current_minute // 5) + 1) * 5
                if next_scan >= 60:
                    next_scan = 0
                start_message += f'- {tf} dk: 0,5,10,15... dakikalarda (bir sonraki: {next_scan:02d}. dakika)\n'
            elif tf == 10:
                next_scan = ((current_minute // 10) + 1) * 10
                if next_scan >= 60:
                    next_scan = 0
                start_message += f'- {tf} dk: 0,10,20,30... dakikalarda (bir sonraki: {next_scan:02d}. dakika)\n'
            elif tf == 15:
                next_scan = ((current_minute // 15) + 1) * 15
                if next_scan >= 60:
                    next_scan = 0
                start_message += f'- {tf} dk: 0,15,30,45 dakikalarda (bir sonraki: {next_scan:02d}. dakika)\n'
            elif tf == 30:
                next_scan = ((current_minute // 30) + 1) * 30
                if next_scan >= 60:
                    next_scan = 0
                start_message += f'- {tf} dk: 0,30 dakikalarda (bir sonraki: {next_scan:02d}. dakika)\n'
        
        if active_filters:
            start_message += 'Aktif filtreler:\n- ' + '\n- '.join(active_filters)
        else:
            start_message += 'Hiçbir filtre seçilmedi'
            
        try:
            socketio.emit('auto_scan_started', {
                'message': start_message,
                'is_running': True,
                'params': active_scan_params[client_id]
            }, room=client_id)
        except Exception as emit_error:
            logging.error(f"Emit hatası - Client: {client_id}, Hata: {str(emit_error)}")
            # Emit hatası durumunda thread'i temizle
            if client_id in auto_scan_threads:
                del auto_scan_threads[client_id]
            if client_id in stop_auto_scan:
                del stop_auto_scan[client_id]
            if client_id in active_scan_params:
                del active_scan_params[client_id]
            raise emit_error
        
    except Exception as e:
        logging.error(f"Otomatik tarama başlatma hatası: {str(e)}")
        # Hata durumunda tüm kaynakları temizle
        if 'client_id' in locals():
            if client_id in auto_scan_threads:
                del auto_scan_threads[client_id]
            if client_id in stop_auto_scan:
                del stop_auto_scan[client_id]
            if client_id in active_scan_params:
                del active_scan_params[client_id]
        socketio.emit('auto_scan_error', {'error': 'Tarama başlatılamadı: ' + str(e)}, room=client_id)

@socketio.on('stop_auto_scan')
def handle_stop_auto_scan():
    """Otomatik taramayı durdur"""
    client_id = request.sid
    logging.info(f"Auto-scan durdurma isteği - Client: {client_id}")
    
    try:
        # Önce stop sinyali gönder
        stop_auto_scan[client_id] = True
        
        # Thread varsa ve çalışıyorsa dur
        if client_id in auto_scan_threads:
            thread = auto_scan_threads[client_id]
            if thread and thread.is_alive():
                thread.join(timeout=5)  # 5 saniye bekle
                if thread.is_alive():
                    logging.warning(f"Thread durdurulamadı - Client: {client_id}")
            
            # Thread referansını temizle
            del auto_scan_threads[client_id]
            
            # Parametreleri temizle
            if client_id in active_scan_params:
                del active_scan_params[client_id]
        
        # Stop sinyalini temizle
        if client_id in stop_auto_scan:
            del stop_auto_scan[client_id]
            
        # Client'a bildir
        socketio.emit('auto_scan_stopped', {'message': 'Otomatik tarama durduruldu'}, room=client_id)
        logging.info(f"Auto-scan başarıyla durduruldu - Client: {client_id}")
        
    except Exception as e:
        logging.error(f"Auto-scan durdurma hatası - Client: {client_id}, Hata: {str(e)}")
        # Hata olsa bile temizlik yap
        if client_id in auto_scan_threads:
            del auto_scan_threads[client_id]
        if client_id in stop_auto_scan:
            del stop_auto_scan[client_id]
        # Hatayı client'a bildir
        socketio.emit('auto_scan_error', {'error': 'Tarama durdurulurken hata oluştu'}, room=client_id)

@socketio.on('disconnect')
def handle_disconnect():
    """Client bağlantısı koptuğunda çalışır"""
    client_id = request.sid
    logging.info(f"Client bağlantısı koptu - Client: {client_id}")
    
    # Artık client disconnect olduğunda taramayı durdurmuyoruz
    # Sadece log tutuyoruz
    logging.info(f"Client {client_id} bağlantısı koptu ama tarama devam ediyor")

@app.route('/')
def root():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_file(path):
    return send_from_directory('.', path)

@app.route('/bionlukcrypto/api/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'message': 'Crypto Scanner API is running'
    })

@app.route('/filter', methods=['POST'])
def filter():
    try:
        data = request.get_json()
        
        # Gelen verileri al
        times = data.get('times', ['15'])
        comparison = data.get('comparison', '≥')
        closing_scan = data.get('closingScan', False)
        coin_list = data.get('coinList')
        all_results = {}
        
        # Telegram mesajı için başlık
        now = datetime.now()
        telegram_message = f"🔍 <b>Manuel Tarama Sonuçları</b>\n"
        telegram_message += f"⏰ <i>{now.strftime('%H:%M:%S')}</i>\n\n"
        
        # Aktif filtreleri belirle
        filter_states = data.get('filterStates', {})
        
        # Filtre bilgilerini Telegram mesajına ekle
        telegram_message += "🎯 Aktif Filtreler:\n"
        filters_added = False
        
        # RSI kontrolü
        rsi1_active = filter_states.get('rsi1', False)
        rsi2_active = filter_states.get('rsi2', False)
        rsi1_val = float(data.get('rsi1')) if rsi1_active and data.get('rsi1') is not None else None
        rsi2_val = float(data.get('rsi2')) if rsi2_active and data.get('rsi2') is not None else None
        rsi_value = rsi1_val if rsi1_active else (rsi2_val if rsi2_active else None)
        
        if rsi_value is not None:
            telegram_message += f"• RSI Periyodu: 13\n"
            telegram_message += f"• RSI {comparison} {rsi_value}\n"
            filters_added = True
        
        # Diğer filtreler
        hacim_active = filter_states.get('hacim', False)
        volume_active = filter_states.get('volume', False)
        artis_active = filter_states.get('artis', False)
        
        # Aktif filtrelerin değerlerini al
        hacim_val = float(data.get('hacim')) if hacim_active and data.get('hacim') is not None else None
        volume_val = float(data.get('volume')) if volume_active and data.get('volume') is not None else None
        artis_val = float(data.get('artis')) if artis_active and data.get('artis') is not None else None
        
        if hacim_val is not None:
            telegram_message += f"• Göreceli Hacim ≥ {hacim_val}x\n"
            filters_added = True
        if volume_val is not None:
            telegram_message += f"• Minimum Hacim ≥ {volume_val} USDT\n"
            filters_added = True
        if artis_val is not None:
            telegram_message += f"• Minimum Değişim ≥ %{artis_val}\n"
            filters_added = True
            
        if not filters_added:
            telegram_message += "• Filtre seçilmedi\n"
        
        # Tarama parametrelerini ekle
        telegram_message += "\n📊 Tarama Parametreleri:\n"
        telegram_message += f"• Zaman Dilimi: {', '.join(times)} dakika\n"
        if coin_list:
            telegram_message += f"• Liste Modu: Özel Liste ({len(coin_list)} coin)\n"
        else:
            telegram_message += "• Liste Modu: Tüm Coinler\n"
        
        for t in times:
            # Tarama yap
            results = scanner.scan_market(
                timeframe=t,
                rsi_length=13,
                rsi_value=rsi_value,
                comparison=comparison,
                min_relative_volume=hacim_val if hacim_active else None,
                min_volume=volume_val if volume_active else None,
                min_percentage_change=artis_val if artis_active else None,
                closing_scan=closing_scan,
                coin_list=coin_list
            )
            all_results[t] = results
            
            # Telegram mesajına sonuçları ekle
            if results:
                telegram_message += f"\n📊 {t} dk Sonuçları:\n"
                for result in results:
                    coin_info = [f"💰 <b>{result['symbol']}</b>"]
                    
                    if rsi_value is not None and 'rsi' in result:
                        coin_info.append(f"RSI: {result['rsi']:.2f}")
                    
                    if hacim_active and 'relative_volume' in result:
                        coin_info.append(f"Göreceli Hacim: {result['relative_volume']:.2f}x")
                    
                    if volume_active and 'volume' in result:
                        coin_info.append(f"Hacim: {result['volume']:.2f}")
                    
                    if artis_active and 'percentage_change' in result:
                        coin_info.append(f"Değişim: %{result['percentage_change']:.2f}")
                    
                    telegram_message += " | ".join(coin_info) + "\n"
            else:
                telegram_message += f"\n❌ {t} dk için filtre kriterlerine uygun coin bulunamadı."
        
        # Toplam sonuç sayısını ekle
        total_coins = sum(len(results) for results in all_results.values())
        telegram_message += f"\n🎯 Toplam {total_coins} coin bulundu."
        
        # Telegram'a gönder
        send_telegram_message(telegram_message)
        
        # Sonuçları kaydet
        app.config['LAST_RESULTS'] = all_results
        return jsonify({'status': 'success', 'results': all_results})
    except Exception as e:
        logging.error(f"Tarama hatası: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/last-results', methods=['GET'])
def last_results():
    results = app.config.get('LAST_RESULTS', {})
    return jsonify({'status': 'success', 'results': results})

@socketio.on('connect')
def handle_connect():
    """Client bağlandığında son durumu senkronize et"""
    client_id = request.sid
    logging.info(f"Yeni client bağlandı - Client: {client_id}")
    
    # Eğer bu client için aktif bir tarama varsa, durumu bildir
    if client_id in auto_scan_threads and auto_scan_threads[client_id].is_alive():
        # Son parametreleri al
        params = active_scan_params.get(client_id, {})
        
        socketio.emit('auto_scan_started', {
            'message': 'Mevcut otomatik tarama devam ediyor',
            'is_running': True,
            'params': params  # Son parametreleri gönder
        }, room=client_id)
        logging.info(f"Client {client_id} yeniden bağlandı, mevcut tarama durumu ve parametreler gönderildi")

@app.route('/restart', methods=['POST'])
def restart_server():
    """Server'ı yeniden başlatma endpoint'i"""
    try:
        # Mevcut process ID'sini al
        current_pid = os.getpid()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, 'server.py')
        
        # Python yolunu al
        python_executable = sys.executable
        
        # Yeni bir batch dosyası oluştur
        batch_path = os.path.join(current_dir, 'restart.bat')
        with open(batch_path, 'w') as f:
            f.write(f'''@echo off
timeout /t 2 /nobreak
taskkill /F /PID {current_pid}
start "" "{python_executable}" "{script_path}"
del "%~f0"
''')
        
        # Batch dosyasını çalıştır
        subprocess.Popen(['start', 'restart.bat'], shell=True)
        
        return jsonify({'status': 'success', 'message': 'Server yeniden başlatılıyor'})
        
    except Exception as e:
        logging.error(f"Server yeniden başlatma hatası: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def main():
    try:
        host = '0.0.0.0'  # Tüm IP'lerden bağlantı kabul et
        port = 5001
        print(f"Server başlatılıyor... http://{host}:{port}")
        logging.info(f"Server başlatıldı - http://{host}:{port}")
        socketio.run(app, debug=False, port=port, host=host)
    except Exception as e:
        logging.error(f"Server başlatılırken hata oluştu: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
