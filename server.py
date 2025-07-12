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
from datetime import datetime
from werkzeug.middleware.proxy_fix import ProxyFix

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
            
            # Her 30 saniyede bir yaşam belirtisi gönder (emit hatalarından etkilenmesin)
            if current_second % 30 == 0:
                try:
                    logging.info(f"AUTO SCAN WORKER YAŞIYOR - Client: {client_id}, Saat: {now.strftime('%H:%M:%S')}")
                    socketio.emit('auto_scan_heartbeat', {
                        'message': f'Otomatik tarama aktif - {now.strftime("%H:%M:%S")}',
                        'scan_count': scan_count
                    }, room=client_id)
                    emit_errors = 0  # Başarılı emit, emit hata sayacını sıfırla
                except Exception as emit_error:
                    emit_errors += 1
                    logging.warning(f"Heartbeat gönderilemedi - Client: {client_id}, Emit Hata: {emit_errors}/{max_emit_errors}, Hata: {str(emit_error)}")
                    # Emit hataları worker'ı durdurmaz, sadece uyarı verir
                    if emit_errors >= max_emit_errors:
                        logging.warning(f"Çok fazla emit hatası - Emit gönderimini geçici olarak durdur - Client: {client_id}")
                        emit_errors = 0  # Sayacı sıfırla, devam et
            
            # Her timeframe için kontrol et
            for timeframe in timeframes:
                if stop_auto_scan.get(client_id, False):
                    break
                    
                # Mum kapanışını kontrol et - timeframe'e göre dakika kontrolü
                should_scan = False
                
                if timeframe == 1:
                    # Her dakika
                    should_scan = current_second == 0
                elif timeframe == 3:
                    # 0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57
                    should_scan = current_minute % 3 == 0 and current_second == 0
                elif timeframe == 5:
                    # 0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55
                    should_scan = current_minute % 5 == 0 and current_second == 0
                elif timeframe == 10:
                    # 0, 10, 20, 30, 40, 50
                    should_scan = current_minute % 10 == 0 and current_second == 0
                elif timeframe == 15:
                    # 0, 15, 30, 45
                    should_scan = current_minute % 15 == 0 and current_second == 0
                elif timeframe == 30:
                    # 0, 30
                    should_scan = current_minute % 30 == 0 and current_second == 0
                
                # Aynı timeframe için son taramadan en az timeframe dakika geçmiş olmalı
                time_since_last = current_timestamp - last_scan_times[timeframe]
                min_interval = timeframe * 60 - 10  # 10 saniye tolerans
                
                if should_scan and time_since_last >= min_interval:
                    try:
                        logging.info(f"TARAMA BAŞLATILIYOR - {timeframe} dakika, Client: {client_id}, Saat: {now.strftime('%H:%M:%S')}")
                        last_scan_times[timeframe] = current_timestamp
                        scan_count += 1
                        consecutive_errors = 0  # Tarama başarılı, genel hata sayacını sıfırla
                        
                        # Tarama parametrelerini kopyala
                        fast_scan_params = scan_params.copy()
                        
                        # Bir önceki mum kapanışını baz al
                        results = scanner.scan_market(
                            timeframe=str(timeframe),  # string'e çevir
                            rsi_length=fast_scan_params['rsi_length'],
                            rsi_value=fast_scan_params['rsi_value'],
                            comparison=fast_scan_params['comparison'],
                            min_relative_volume=fast_scan_params['min_relative_volume'],
                            min_volume=fast_scan_params['min_volume'],
                            min_percentage_change=fast_scan_params['min_percentage_change'],
                            closing_scan=True,
                            coin_list=fast_scan_params['coin_list']
                        )
                        
                        # Sonuç mesajını hazırla
                        message = f"\n{timeframe} dakikalık tarama sonuçları ({now.strftime('%H:%M:%S')}):\n"
                        message += "-" * 50 + "\n"
                        
                        if results:
                            # Aktif filtreleri belirle
                            active_filters = {
                                'rsi': fast_scan_params['rsi_value'] is not None,
                                'relative_volume': fast_scan_params['min_relative_volume'] is not None,
                                'volume': fast_scan_params['min_volume'] is not None,
                                'percentage_change': fast_scan_params['min_percentage_change'] is not None
                            }
                            
                            for result in results:
                                coin_info = [f"Sembol: {result['symbol']}"]
                                
                                if active_filters['rsi'] and 'rsi' in result:
                                    coin_info.append(f"RSI: {result['rsi']:.2f}")
                                
                                if active_filters['relative_volume'] and 'relative_volume' in result:
                                    coin_info.append(f"Göreceli Hacim: {result['relative_volume']:.2f}")
                                
                                if active_filters['volume'] and 'volume' in result:
                                    coin_info.append(f"Hacim: {result['volume']:.2f}")
                                
                                if active_filters['percentage_change'] and 'percentage_change' in result:
                                    coin_info.append(f"Değişim: %{result['percentage_change']:.2f}")
                                
                                message += ", ".join(coin_info) + "\n"
                            
                            message += "-" * 50 + "\n"
                            logging.info(f"TARAMA TAMAMLANDI - {timeframe} dakika, {len(results)} sonuç, Client: {client_id}")
                        else:
                            # Sonuç bulunamadığında
                            message += "Filtre kriterlerine uygun coin bulunamadı.\n"
                            message += "-" * 50 + "\n"
                            logging.info(f"TARAMA TAMAMLANDI - {timeframe} dakika, sonuç yok, Client: {client_id}")
                        
                        # Sonucu gönder (emit hatalarından etkilenmesin)
                        try:
                            socketio.emit('auto_scan_result', {'message': message, 'timeframe': str(timeframe)}, room=client_id)
                        except Exception as emit_error:
                            emit_errors += 1
                            logging.warning(f"Sonuç gönderilemedi - {timeframe} dakika, Client: {client_id}, Emit Hata: {emit_errors}/{max_emit_errors}, Hata: {str(emit_error)}")
                            # Emit hatası taramayı durdurmaz, sadece log yapar
                            
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
            time.sleep(2)  # Hata durumunda biraz daha bekle
    
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
        timeframes = data.get('times', [])
        filter_states = data.get('filterStates', {})
        
        logging.info(f"Gelen veri: {data}")
        logging.info(f"Client bağlantı ID'si: {client_id}")
        
        # Eğer bu client için zaten çalışan bir tarama varsa, onu durdur
        if client_id in auto_scan_threads and auto_scan_threads[client_id].is_alive():
            logging.info(f"Mevcut auto-scan thread durduruluyor - Client: {client_id}")
            stop_auto_scan[client_id] = True
            auto_scan_threads[client_id].join(timeout=5)
            if auto_scan_threads[client_id].is_alive():
                logging.warning(f"Thread zorla sonlandırıldı - Client: {client_id}")
        
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
        
        # Log parametreleri
        logging.info(f"Hazırlanan tarama parametreleri: {scan_params}")
        
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
            args=(timeframes, scan_params, client_id)
        )
        auto_scan_threads[client_id].daemon = True
        auto_scan_threads[client_id].start()
        
        logging.info(f"Yeni auto-scan thread başlatıldı - Client: {client_id}, Thread ID: {auto_scan_threads[client_id].ident}")
        
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
            
        socketio.emit('auto_scan_started', {'message': start_message}, room=client_id)
        
    except Exception as e:
        logging.error(f"Otomatik tarama başlatma hatası: {str(e)}")
        socketio.emit('auto_scan_error', {'error': str(e)}, room=client_id)

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
    
    try:
        # Aktif tarama varsa durdur
        if client_id in auto_scan_threads:
            stop_auto_scan[client_id] = True
            thread = auto_scan_threads[client_id]
            if thread and thread.is_alive():
                thread.join(timeout=3)  # 3 saniye bekle
            
            # Thread referansını temizle
            del auto_scan_threads[client_id]
            
        # Stop sinyalini temizle
        if client_id in stop_auto_scan:
            del stop_auto_scan[client_id]
            
    except Exception as e:
        logging.error(f"Disconnect cleanup hatası - Client: {client_id}, Hata: {str(e)}")
        # Hata olsa bile temizlik yapmaya çalış
        if client_id in auto_scan_threads:
            del auto_scan_threads[client_id]
        if client_id in stop_auto_scan:
            del stop_auto_scan[client_id]

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
        
        for t in times:
            # Hangi filtreler aktif?
            filter_states = data.get('filterStates', {})
            
            # RSI kontrolü
            rsi1_active = filter_states.get('rsi1', False)
            rsi2_active = filter_states.get('rsi2', False)
            rsi1_val = float(data.get('rsi1')) if rsi1_active and data.get('rsi1') is not None else None
            rsi2_val = float(data.get('rsi2')) if rsi2_active and data.get('rsi2') is not None else None
            rsi_value = rsi1_val if rsi1_active else (rsi2_val if rsi2_active else None)
            
            # Diğer filtreler
            hacim_active = filter_states.get('hacim', False)
            volume_active = filter_states.get('volume', False)
            artis_active = filter_states.get('artis', False)
            
            # Aktif filtrelerin değerlerini al
            hacim_val = float(data.get('hacim')) if hacim_active and data.get('hacim') is not None else None
            volume_val = float(data.get('volume')) if volume_active and data.get('volume') is not None else None
            artis_val = float(data.get('artis')) if artis_active and data.get('artis') is not None else None
            
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
    """Client bağlandığında son sonuçları gönder"""
    if last_scan_results:
        for result in last_scan_results:
            socketio.emit('match_found', result, room=request.sid)

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
