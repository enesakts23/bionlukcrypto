from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from crypto_scanner import CryptoScanner
from flask_socketio import SocketIO
from waitress import serve
import logging
import sys
import os
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
