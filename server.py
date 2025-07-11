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

# WebSocket desteği ekle
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
    always_connect=True,
    reconnection=True,
    reconnection_attempts=5,
    reconnection_delay=1000,
    reconnection_delay_max=5000
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
    logging.info(f"Başlatılan tarama parametreleri: {scan_params}")
    logging.info(f"Seçili zaman aralıkları: {timeframes}")
    
    # Timeframe'leri integer'a çevir ve sırala
    timeframes = sorted([int(tf) for tf in timeframes])
    
    while not stop_auto_scan.get(client_id, False):
        now = datetime.now()
        current_minute = now.minute
        current_second = now.second
        
        for timeframe in timeframes:
            # Mum kapanışını kontrol et
            # Örneğin 3dk için: 00,03,06,09,12,15... dakikalarda
            if current_minute % timeframe == 0 and current_second == 0:
                try:
                    logging.info(f"{timeframe} dakikalık tarama başlatılıyor... Saat: {now.strftime('%H:%M:%S')}")
                    
                    # Bir önceki mum kapanışını baz al
                    results = scanner.scan_market(
                        timeframe=str(timeframe),  # string'e çevir
                        rsi_length=scan_params['rsi_length'],
                        rsi_value=scan_params['rsi_value'],
                        comparison=scan_params['comparison'],
                        min_relative_volume=scan_params['min_relative_volume'],
                        min_volume=scan_params['min_volume'],
                        min_percentage_change=scan_params['min_percentage_change'],
                        closing_scan=True,
                        coin_list=scan_params['coin_list']
                    )
                    
                    if results:
                        # Sonuçları konsol formatında gönder
                        message = f"\n{timeframe} dakikalık tarama sonuçları ({now.strftime('%H:%M:%S')}):\n"
                        message += "-" * 50 + "\n"
                        
                        # Aktif filtreleri belirle
                        active_filters = {
                            'rsi': scan_params['rsi_value'] is not None,
                            'relative_volume': scan_params['min_relative_volume'] is not None,
                            'volume': scan_params['min_volume'] is not None,
                            'percentage_change': scan_params['min_percentage_change'] is not None
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
                        socketio.emit('auto_scan_result', {'message': message, 'timeframe': str(timeframe)}, room=client_id)
                        logging.info(f"{timeframe} dakikalık tarama tamamlandı. {len(results)} sonuç bulundu.")
                except Exception as e:
                    error_msg = f"{timeframe} dakikalık tarama hatası: {str(e)}"
                    logging.error(error_msg)
                    socketio.emit('auto_scan_error', {'error': error_msg}, room=client_id)
        
        # Her saniye kontrol et
        time.sleep(1)

@socketio.on('start_auto_scan')
def handle_auto_scan(data):
    """Otomatik taramayı başlat"""
    try:
        client_id = request.sid
        timeframes = data.get('times', [])
        filter_states = data.get('filterStates', {})
        
        logging.info(f"Gelen veri: {data}")
        
        # Eğer bu client için zaten çalışan bir tarama varsa, onu durdur
        if client_id in auto_scan_threads and auto_scan_threads[client_id].is_alive():
            stop_auto_scan[client_id] = True
            auto_scan_threads[client_id].join()
        
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
        
        # Başlangıç mesajı
        start_message = f'Otomatik tarama başlatıldı.\n'
        start_message += f'Seçili zaman aralıkları: {", ".join(timeframes)} dakika\n'
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
    if client_id in auto_scan_threads:
        stop_auto_scan[client_id] = True
        socketio.emit('auto_scan_stopped', {'message': 'Otomatik tarama durduruldu'}, room=client_id)

@socketio.on('disconnect')
def handle_disconnect():
    """Client bağlantısı koptuğunda otomatik taramayı durdur"""
    client_id = request.sid
    if client_id in auto_scan_threads:
        stop_auto_scan[client_id] = True

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
        hacim = data.get('hacim', 1.0)
        volume = data.get('volume', 1000)
        artis = data.get('artis', 0.0)
        closing_scan = data.get('closingScan', False)
        coin_list = data.get('coinList')
        all_results = {}
        for t in times:
            # Hangi filtreler aktif?
            filter_states = data.get('filterStates', {})
            rsi1_active = filter_states.get('rsi1', False)
            rsi2_active = filter_states.get('rsi2', False)
            hacim_active = filter_states.get('hacim', False)
            volume_active = filter_states.get('volume', False)
            artis_active = filter_states.get('artis', False)
            rsi1_val = float(data.get('rsi1')) if rsi1_active and data.get('rsi1') is not None else None
            rsi2_val = float(data.get('rsi2')) if rsi2_active and data.get('rsi2') is not None else None
            hacim_val = float(data.get('hacim')) if hacim_active and data.get('hacim') is not None else None
            volume_val = float(data.get('volume')) if volume_active and data.get('volume') is not None else None
            artis_val = float(data.get('artis')) if artis_active and data.get('artis') is not None else None
            comparison = data.get('comparison', '≥')
            closing_scan = data.get('closingScan', False)
            coin_list = data.get('coinList')
            rsi_value = None
            if rsi1_val is not None:
                rsi_value = rsi1_val
            elif rsi2_val is not None:
                rsi_value = rsi2_val
            rsi_length = 13
            results = scanner.scan_market(
                timeframe=t,
                rsi_length=rsi_length,
                rsi_value=rsi_value,
                comparison=comparison,
                min_relative_volume=hacim_val,
                min_volume=volume_val,
                min_percentage_change=artis_val,
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
