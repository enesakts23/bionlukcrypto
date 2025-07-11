// Sunucu URL'i yapılandırması
function getServerUrl() {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    const port = window.location.port;
    
    console.log('Current window location:', window.location.href);
    console.log('Hostname:', hostname, 'Protocol:', protocol, 'Port:', port);
    
    // Eğer zaten Flask sunucusundan servis ediliyorsa (port 5001) aynı URL'i kullan
    if (port === '5001') {
        const serverUrl = `${protocol}//${hostname}:5001`;
        console.log('Using same-origin server URL:', serverUrl);
        return serverUrl;
    }
    
    // Eğer localhost veya 127.0.0.1 ise (development - farklı port)
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        const serverUrl = 'http://localhost:5001';
        console.log('Using cross-origin server URL:', serverUrl);
        return serverUrl;
    }
    
    // Production ortamında
    const serverUrl = `${protocol}//${hostname}:5001`;
    console.log('Using production server URL:', serverUrl);
    return serverUrl;
}

const SERVER_URL = getServerUrl();

// Socket.IO bağlantısı - global değişken olarak tanımla
let socket = null;
let isConnected = false;
let isScanning = false;

// Page refresh prevention
let isPageRefreshing = false;

// Detect navigation
let lastUrl = window.location.href;
new MutationObserver(() => {
    const url = window.location.href;
    if (url !== lastUrl) {
        console.log('=== NAVIGATION DETECTED ===');
        console.log('From:', lastUrl);
        console.log('To:', url);
        lastUrl = url;
    }
}).observe(document, { subtree: true, childList: true });

// Seçili zaman aralıkları (çoklu seçim)
let selectedTimes = [];

// Çoklu zaman aralığı için progress barları ve sonuçlar
let multiTimeProgress = {};

// Heartbeat izleme
let lastHeartbeat = null;

// Socket.IO bağlantısını başlat
function initializeSocket() {
    if (socket) {
        socket.disconnect();
        socket = null;
    }

    socket = io(SERVER_URL, {
        // Backend ile uyumlu transport sıralaması - polling'e öncelik ver
        transports: ['polling'],
        reconnectionAttempts: 5,  // Azaltıldı - çok fazla retry'dan kaçın
        timeout: 30000,  // Artırıldı - daha uzun timeout
        reconnection: true,
        reconnectionDelay: 3000,  // Artırıldı - daha yavaş retry
        reconnectionDelayMax: 15000,  // Artırıldı
        autoConnect: true,
        forceNew: false,  // forceNew: false - mevcut bağlantıyı kullanmaya çalış
        // WebSocket upgrade'i devre dışı bırak (daha stabil)
        upgrade: false,
        rememberUpgrade: false,
        // Ping ayarları - daha uzun interval
        pingInterval: 25000,
        pingTimeout: 20000
    });

    let errorShown = false;
    let reconnectAttempts = 0;

    // Bağlantı olayları
    socket.on('connect', () => {
        console.log('Sunucuya bağlanıldı:', SERVER_URL);
        isConnected = true;
        showMessage('info', 'Sunucuya bağlanıldı');
        errorShown = false;
        reconnectAttempts = 0;
        
        // Auto-scan durumunu kontrol et ve gerekirse devam ettir
        if (isAutoScanActive) {
            appendToConsole('\n✅ Bağlantı yeniden kuruldu. Otomatik tarama devam ediyor...\n');
            console.log('Auto-scan aktif durumda, bağlantı yeniden kuruldu');
            
            // Buton durumunu otomatik tarama aktif haline getir - güvenilir şekilde
            const autoScanButton = document.querySelector('.auto-scan-btn');
            if (autoScanButton) {
                autoScanButton.textContent = 'TARAMAYI DURDUR';
                autoScanButton.style.backgroundColor = '#ff4d4d';
                console.log('Auto-scan button state restored: TARAMAYI DURDUR');
            }
        } else {
            // Auto-scan aktif değilse butonun doğru durumda olduğundan emin ol
            const autoScanButton = document.querySelector('.auto-scan-btn');
            if (autoScanButton && autoScanButton.textContent !== 'OTOMATİK TARAMA') {
                autoScanButton.textContent = 'OTOMATİK TARAMA';
                autoScanButton.style.backgroundColor = '#4CAF50';
                console.log('Auto-scan button state corrected: OTOMATİK TARAMA');
            }
        }
    });

    socket.on('disconnect', (reason) => {
        console.log('Sunucu bağlantısı kesildi, sebep:', reason);
        isConnected = false;
        
        if (!errorShown) {
            if (reason === 'io server disconnect') {
                showMessage('error', 'Sunucu tarafından bağlantı kesildi.');
            } else {
                showMessage('warning', 'Bağlantı kesildi. Yeniden bağlanmaya çalışılıyor...');
            }
            errorShown = true;
        }
        
        // Auto-scan aktifse bağlantı kesildi mesajı (ama durdurmuyoruz)
        if (isAutoScanActive) {
            appendToConsole(`\n⚠️ Bağlantı kesildi (${reason}). Yeniden bağlanmaya çalışılıyor...\n`);
            console.log('Auto-scan aktif, bağlantı kesildi ama devam ediyor');
        }
    });

    socket.on('connect_error', (error) => {
        reconnectAttempts++;
        console.error('Bağlantı hatası:', error, 'Deneme:', reconnectAttempts);
        isConnected = false;
        
        if (!errorShown) {
            if (reconnectAttempts > 10) {
                showMessage('error', 'Sunucuya bağlanılamadı. Lütfen sunucunun çalıştığını kontrol edin.');
                // Do NOT suggest page refresh - this might be causing the cycle
            } else {
                showMessage('warning', `Bağlantı hatası (${reconnectAttempts}/10). Yeniden deneniyor...`);
            }
            errorShown = true;
        }
    });

    socket.on('reconnect', (attemptNumber) => {
        console.log('Yeniden bağlandı, deneme sayısı:', attemptNumber);
        isConnected = true;
        showMessage('success', 'Bağlantı yeniden kuruldu');
        errorShown = false;
        reconnectAttempts = 0;
        
        if (isAutoScanActive) {
            appendToConsole('\n✅ Bağlantı başarıyla yeniden kuruldu. Otomatik tarama devam ediyor.\n');
            console.log('Reconnect tamamlandı, auto-scan devam ediyor');
        }
    });

    socket.on('reconnect_error', (error) => {
        console.error('Yeniden bağlantı hatası:', error);
        if (isAutoScanActive) {
            appendToConsole(`\n⚠️ Yeniden bağlantı hatası: ${error.message || error}\n`);
        }
    });

    socket.on('reconnect_failed', () => {
        console.error('Yeniden bağlantı başarısız - manuel retry gerekli');
        showMessage('error', 'Sunucuya bağlantı kurulamadı. Sunucu durumunu kontrol edin.');
        
        // Auto-scan'i durdur ama sayfayı yenileme!
        if (isAutoScanActive) {
            appendToConsole('\n❌ Bağlantı kurulamadı. Otomatik tarama durdu.\n');
            isAutoScanActive = false;
            const autoScanButton = document.querySelector('.auto-scan-btn');
            if (autoScanButton) {
                autoScanButton.textContent = 'OTOMATİK TARAMA';
                autoScanButton.style.backgroundColor = '#4CAF50';
            }
        }
        
        // Manual retry butonunu göster
        setTimeout(() => {
            const retryButton = document.createElement('button');
            retryButton.textContent = 'Yeniden Bağlan';
            retryButton.onclick = () => {
                retryButton.remove();
                initializeSocket();
            };
            retryButton.style.cssText = `
                background: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                cursor: pointer;
                margin: 10px;
            `;
            const resultsContainer = document.querySelector('.results-container');
            if (resultsContainer && !resultsContainer.querySelector('button')) {
                resultsContainer.appendChild(retryButton);
            }
        }, 2000);
    });

    socket.on('match_found', (result) => {
        if (!document.querySelector('.results-table')) {
            createResultsTable();
        }
        addResultToTable(result);
    });

    socket.on('scan_progress', (progress) => {
        if (isScanning) {
            updateProgress(progress);
        }
    });

    // --- YENİ: Her zaman aralığı için scan_completed dinleyicisi ekle ---
    const timeframes = ['1', '3', '5', '10', '15', '30'];
    timeframes.forEach(time => {
        socket.on(`scan_completed_${time}`, async (data) => {
            // SADECE otomatik tarama aktif DEĞİLSE bu handler'ı çalıştır
            if (!isAutoScanActive) {
                isScanning = false;
                const filterButton = document.querySelector('.filter-btn');
                if (filterButton) {
                    filterButton.disabled = false;
                    filterButton.textContent = 'FILTRELE';
                }
                showSuccessMessage(`Tarama tamamlandı! ${data.total_matches} eşleşme bulundu.`);
            }
            // Auto-scan aktifse bu olayları göz ardı et - auto-scan kendi durumunu yönetir
        });
    });
    // --- YENİ SONU ---

    // *** OTOMATIK TARAMA EVENT LISTENER'LARI - BURAYA TAŞINDI ***
    let lastUpdateTime = {};
    let isFirstScan = true;
    
    socket.on('auto_scan_started', (data) => {
        console.log('Auto scan started event received:', data);
        if (isFirstScan) {
            const consoleDiv = document.getElementById('console-output') || createConsoleDiv();
            consoleDiv.innerHTML = ''; // Sadece ilk başlangıçta konsolu temizle
            isFirstScan = false;
        }
        appendToConsole(data.message);
        lastUpdateTime = {};
    });

    socket.on('auto_scan_result', (data) => {
        console.log('Auto scan result received:', data);
        if (!isAutoScanActive) return;
        
        // Validate button state when receiving results
        validateAndSyncButtonState();
        
        // Her sonucu göster - zaman filtrelemesi kaldırıldı
        appendToConsole(data.message, data.timeframe);
    });

    socket.on('auto_scan_error', (data) => {
        console.log('Auto scan error received:', data);
        appendToConsole(`\nHATA: ${data.error}\n`);
    });

    socket.on('auto_scan_stopped', (data) => {
        console.log('Auto scan stopped event received:', data);
        appendToConsole(`\n${data.message}\n`);
        
        // SADECE kullanıcı tarafından durdurulmuşsa buton durumunu değiştir
        // Exact message check for manual stop
        if (data.message === 'Otomatik tarama durduruldu') {
            console.log('Manual stop detected (exact match), updating button state');
            isAutoScanActive = false;
            isFirstScan = true;
            const autoScanButton = document.querySelector('.auto-scan-btn');
            if (autoScanButton) {
                autoScanButton.textContent = 'OTOMATİK TARAMA';
                autoScanButton.style.backgroundColor = '#4CAF50';
                console.log('Button state changed to: OTOMATİK TARAMA');
            }
            lastUpdateTime = {};
        } else {
            // Bağlantı ile ilgili durdurma veya diğer mesajlar, buton durumunu değiştirme
            console.log('Non-manual stop message, keeping button state. Message:', data.message);
        }
    });

    socket.on('auto_scan_heartbeat', (data) => {
        console.log('Auto scan heartbeat:', data);
        // Heartbeat mesajını konsola yazmıyoruz, sadece logluyoruz
        
        // Auto-scan aktifse ve heartbeat alıyorsak, bu iyi bir işaret
        if (isAutoScanActive) {
            // Durumu kontrol et, gerekirse yeniden başlat
            const now = Date.now();
            if (!lastHeartbeat) {
                lastHeartbeat = now;
            } else {
                const timeSinceHeartbeat = now - lastHeartbeat;
                if (timeSinceHeartbeat > 90000) { // 90 saniyeden fazla heartbeat yoksa
                    console.warn('Heartbeat timeout, checking auto-scan status');
                }
                lastHeartbeat = now;
            }
        }
    });
}

// Sonuç tablosunu oluştur
function createResultsTable(columns) {
    const resultsContainer = document.querySelector('.results-container');
    // Tablo başlıklarını dinamik oluştur
    let headers = '<th>Sembol</th>';
    if (columns.includes('rsi')) headers += '<th>RSI</th>';
    if (columns.includes('relative_volume')) headers += '<th>Göreceli Hacim</th>';
    if (columns.includes('volume')) headers += '<th>Hacim</th>';
    if (columns.includes('percentage_change')) headers += '<th>Yüzde Değişim</th>';
    resultsContainer.innerHTML = `
        <div class="table-header">
            <button class="clear-results-btn" onclick="clearResults()">Sonuçları Temizle</button>
        </div>
        <table class="results-table">
            <thead>
                <tr>${headers}</tr>
            </thead>
            <tbody></tbody>
        </table>
    `;
}

// Başarı mesajını göster
function showSuccessMessage(message) {
    const resultsContainer = document.querySelector('.results-container');
    const existingMessage = resultsContainer.querySelector('.success-message');
    if (existingMessage) {
        existingMessage.remove();
    }

    const successDiv = document.createElement('div');
    successDiv.className = 'success-message';
    successDiv.textContent = message;

    const table = resultsContainer.querySelector('.results-table');
    if (table) {
        resultsContainer.insertBefore(successDiv, table);
    } else {
        resultsContainer.appendChild(successDiv);
    }

    setTimeout(() => {
        if (successDiv && successDiv.parentNode) {
            successDiv.remove();
        }
    }, 5000);
}

// Coin listesi
let coinList = null;

// Değer sınırları
const limits = {
    rsi1: { min: 0, max: 100, step: 1 },
    rsi2: { min: 0, max: 100, step: 1 },
    hacim: { min: 0.1, max: 10.0, step: 0.1 },  // Göreceli hacim için 0.1-10.0 arası
    volume: { min: 0, max: 250000, step: 100 },  // Normal hacim için
    artis: { min: -100, max: 100, step: 0.1 }  // Yüzde değişim için 0.1'lik adımlar
};

// Filtre durumları
const filterStates = {
    rsi1: false,
    rsi2: false,
    hacim: false,
    volume: false,
    artis: false
};

// Seçili karşılaştırma operatörü
let selectedComparison = '≥';

// Kapanışta tarama durumu
let isClosingScanActive = false;

// Otomatik tarama durumu
let isAutoScanActive = false;

// Button state validation and sync function
function validateAndSyncButtonState() {
    const autoScanButton = document.querySelector('.auto-scan-btn');
    if (!autoScanButton) return;
    
    const expectedText = isAutoScanActive ? 'TARAMAYI DURDUR' : 'OTOMATİK TARAMA';
    const expectedColor = isAutoScanActive ? '#ff4d4d' : '#4CAF50';
    
    if (autoScanButton.textContent !== expectedText) {
        console.log(`Button state mismatch detected! Expected: ${expectedText}, Current: ${autoScanButton.textContent}`);
        console.log(`Correcting button state. isAutoScanActive: ${isAutoScanActive}`);
        autoScanButton.textContent = expectedText;
        autoScanButton.style.backgroundColor = expectedColor;
    }
}

// Debounce mechanism for button clicks
let lastButtonClick = 0;
const BUTTON_DEBOUNCE_MS = 1000; // 1 second debounce

// Konsol div'i oluştur
function createConsoleDiv() {
    // Eğer zaten varsa, yeni oluşturma
    let consoleDiv = document.getElementById('console-output');
    if (consoleDiv) {
        return consoleDiv;
    }

    consoleDiv = document.createElement('div');
    consoleDiv.id = 'console-output';
    consoleDiv.style.cssText = `
        background-color: #1a1a1a;
        color: #00ff00;
        font-family: monospace;
        padding: 10px;
        margin-top: 20px;
        border-radius: 8px;
        height: 300px;
        overflow-y: auto;
        white-space: pre-wrap;
        display: none;
    `;
    document.querySelector('.results-container').appendChild(consoleDiv);
    return consoleDiv;
}

// Konsola mesaj ekle
function appendToConsole(message, timeframe = null) {
    const consoleDiv = document.getElementById('console-output') || createConsoleDiv();
    consoleDiv.style.display = 'block';
    
    // Yeni mesajı ekle
    const messageDiv = document.createElement('div');
    messageDiv.textContent = message;
    
    // Timeframe bilgisi varsa ve yeni bir tarama sonucuysa, önceki aynı timeframe sonuçlarını temizle
    if (timeframe) {
        const oldResults = consoleDiv.querySelectorAll(`[data-timeframe="${timeframe}"]`);
        oldResults.forEach(result => result.remove());
        messageDiv.setAttribute('data-timeframe', timeframe);
    }
    
    consoleDiv.appendChild(messageDiv);
    
    // Scroll'u en alta getir (performanslı şekilde)
    requestAnimationFrame(() => {
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
    });
}

// Coin listesi dosyasını işle
document.getElementById('coinListFile').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const content = e.target.result;
            const lines = content.split(/[\n,]/).map(line => line.trim()).filter(line => line);

            // Spot coin sembollerini işle
            coinList = lines
                .map(line => {
                    // BINANCE:BTCUSDT.P formatıysa, BTCUSDT'ye çevir
                    const match = line.match(/BINANCE:([A-Z0-9]+)USDT\.P/);
                    if (match) {
                        return match[1] + 'USDT';
                    }
                    // BINANCE:BTCUSDT formatıysa, BTCUSDT'ye çevir
                    const matchSpot = line.match(/BINANCE:([A-Z0-9]+USDT)$/);
                    if (matchSpot) {
                        return matchSpot[1];
                    }
                    // BTCUSDT.P formatıysa, BTCUSDT'ye çevir
                    if (/^[A-Z0-9]+USDT\.P$/.test(line)) {
                        return line.replace('.P', '');
                    }
                    // Sadece BTCUSDT gibi olanları al
                    if (/^[A-Z0-9]+USDT$/.test(line)) {
                        return line;
                    }
                    return null;
                })
                .filter(symbol => symbol);

            // Sonuçları göster
            const fileName = file.name;
            const fileSize = (file.size / 1024).toFixed(1); // KB cinsinden
            document.getElementById('selectedFileName').textContent = `${fileName} (${fileSize} KB)`;
            document.getElementById('coinCount').textContent = `${coinList.length} coin yüklendi`;

            // Başarı mesajı göster
            showMessage('success', `${coinList.length} coin başarıyla yüklendi.`);
            
            console.log('İşlenmiş coin listesi:', coinList);
        } catch (error) {
            console.error('Dosya işleme hatası:', error);
            showMessage('error', 'Dosya işlenirken bir hata oluştu. Lütfen geçerli bir dosya yükleyin.');
            resetFileUpload();
        }
    };

    reader.onerror = function() {
        showMessage('error', 'Dosya okuma hatası. Lütfen tekrar deneyin.');
        resetFileUpload();
    };

    reader.readAsText(file);
});

// Dosya yükleme alanını sıfırla
function resetFileUpload() {
    document.getElementById('coinListFile').value = '';
    document.getElementById('selectedFileName').textContent = 'Liste seçilmedi';
    document.getElementById('coinCount').textContent = '';
    coinList = null;
}

// Mesaj göster
function showMessage(type, message) {
    const resultsContainer = document.querySelector('.results-container');
    const messageDiv = document.createElement('div');
    messageDiv.className = `${type}-message`;
    messageDiv.textContent = message;
    
    resultsContainer.innerHTML = '';
    resultsContainer.appendChild(messageDiv);
    
    // 5 saniye sonra mesajı kaldır
    setTimeout(() => {
        messageDiv.remove();
    }, 5000);
}

// İlerleme çubuğunu güncelle
function updateProgress(progress) {
    const progressBar = document.querySelector('.progress');
    const progressText = document.querySelector('.progress-text');
    
    progressBar.style.width = `${progress.percentage}%`;
    progressText.textContent = `${progress.percentage}% (${progress.current}/${progress.total})`;
}

// İlerleme çubuğunu sıfırla
function resetProgress() {
    const progressBar = document.querySelector('.progress');
    const progressText = document.querySelector('.progress-text');
    
    progressBar.style.width = '0%';
    progressText.textContent = '0%';
}

// Sonuç tablosuna yeni sonuç ekle
function addResultToTable(result) {
    let resultsContainer = document.querySelector('.results-container');
    // Eğer tablo yoksa oluştur
    if (!document.querySelector('.results-table')) {
        const columns = Object.keys(result);
        createResultsTable(columns);
    }
    const tbody = document.querySelector('.results-table tbody');
    let rowHtml = `<td>${result.symbol}</td>`;
    if ('rsi' in result) rowHtml += `<td>${result.rsi}</td>`;
    if ('relative_volume' in result) rowHtml += `<td>${result.relative_volume}x</td>`;
    if ('volume' in result) rowHtml += `<td>${Number(result.volume).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>`;
    if ('percentage_change' in result) rowHtml += `<td>${result.percentage_change}%</td>`;
    const row = document.createElement('tr');
    row.innerHTML = rowHtml;
    tbody.appendChild(row);
}

// Sonuçları temizle
function clearResults() {
    document.querySelector('.results-container').innerHTML = '';
}

// Filtre durumunu değiştir
function toggleFilter(id) {
    filterStates[id] = !filterStates[id];
    const button = document.querySelector(`button[onclick="toggleFilter('${id}')"]`);
    const valueButtons = document.querySelectorAll(`button[onclick^="updateValue('${id}'"]`);
    const comparisonButtons = document.querySelectorAll(`button[onclick^="setComparison('${id}'"]`);
    const row = button.closest('.filter-row');
    
    button.textContent = filterStates[id] ? 'Aktif' : 'Pasif';
    button.classList.toggle('active', filterStates[id]);
    if (row) row.classList.toggle('active', filterStates[id]);
    
    // Değer butonlarını aktif/pasif yap
    valueButtons.forEach(btn => {
        btn.disabled = !filterStates[id];
    });
    
    // Karşılaştırma butonlarını aktif/pasif yap (sadece RSI2 için)
    if (comparisonButtons.length > 0) {
        comparisonButtons.forEach(btn => {
            btn.disabled = !filterStates[id];
        });
    }
}

// Değerleri güncelleme fonksiyonu
function updateValue(id, change) {
    // Eğer filtre pasifse işlem yapma
    if (!filterStates[id]) return;
    
    const element = document.getElementById(`${id}-value`);
    let currentValue = parseFloat(element.textContent);
    const limit = limits[id];
    
    currentValue += change;
    
    // Sınırları kontrol et
    if (currentValue < limit.min) currentValue = limit.min;
    if (currentValue > limit.max) currentValue = limit.max;
    
    // Değeri güncelle ve ondalık basamak sayısını ayarla
    if (id === 'hacim' || id === 'artis') {
        element.textContent = currentValue.toFixed(1);
    } else {
        element.textContent = Math.round(currentValue);
    }
}

// Karşılaştırma operatörü seçme fonksiyonu
function setComparison(id, operator) {
    if (id === 'rsi2' && filterStates[id]) {
        selectedComparison = operator;
        
        // Karşılaştırma butonlarını güncelle
        const comparisonButtons = document.querySelectorAll('.comparison-btn');
        comparisonButtons.forEach(button => {
            button.classList.toggle('active', button.textContent === operator);
        });
    }
}

// Kapanışta tarama toggle fonksiyonu
function toggleClosingScan(button) {
    isClosingScanActive = !isClosingScanActive;
    button.textContent = isClosingScanActive ? 'Aktif' : 'Pasif';
    button.classList.toggle('active', isClosingScanActive);
}

function listenMultiTimeEvents(times) {
    times.forEach(time => {
        // Progress
        socket.on(`scan_progress_${time}`, (progress) => {
            updateMultiTimeProgress(time, progress);
        });

        // Scan completed
        socket.on(`scan_completed_${time}`, async (data) => {
            console.log(`${time} dk taraması tamamlandı!`);
            
            // Progress barı sıfırla
            updateMultiTimeProgress(time, {percentage: 100, current: 0, total: 0});
        });

        // Anlık eşleşen coinleri ekle
        socket.on(`match_found_${time}`, (result) => {
            const multiTimeContainer = document.querySelector('.multi-time-results-container');
            let tableDiv = multiTimeContainer.querySelector(`.multi-time-table[data-time="${time}"]`);
            
            if (!tableDiv) {
                tableDiv = document.createElement('div');
                tableDiv.className = 'multi-time-table results-container';
                tableDiv.setAttribute('data-time', time);
                
                // Tablo başlığı ve yapısını oluştur
                let headers = '<th>Sembol</th>';
                if ('rsi' in result) headers += '<th>RSI</th>';
                if ('relative_volume' in result) headers += '<th>Göreceli Hacim</th>';
                if ('volume' in result) headers += '<th>Hacim</th>';
                if ('percentage_change' in result) headers += '<th>Yüzde Değişim</th>';
                
                tableDiv.innerHTML = `
                    <div class="table-header">${time} dk Sonuçları</div>
                    <table class="results-table">
                        <thead><tr>${headers}</tr></thead>
                        <tbody></tbody>
                    </table>
                `;
                multiTimeContainer.appendChild(tableDiv);
            }

            const tbody = tableDiv.querySelector('tbody');
            if (tbody) {
                let rowHtml = `<td>${result.symbol}</td>`;
                if ('rsi' in result) rowHtml += `<td>${result.rsi}</td>`;
                if ('relative_volume' in result) rowHtml += `<td>${result.relative_volume}x</td>`;
                if ('volume' in result) rowHtml += `<td>${Number(result.volume).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>`;
                if ('percentage_change' in result) rowHtml += `<td>${result.percentage_change}%</td>`;
                
                const row = document.createElement('tr');
                row.innerHTML = rowHtml;
                tbody.appendChild(row);
            }
        });
    });
}

function updateMultiTimeProgress(time, progress) {
    let multiTimeContainer = document.querySelector('.multi-time-results-container');
    let progressDiv = multiTimeContainer.querySelector(`.progress-bar[data-time="${time}"]`);
    
    if (!progressDiv) {
        progressDiv = document.createElement('div');
        progressDiv.className = 'progress-bar';
        progressDiv.setAttribute('data-time', time);
        progressDiv.innerHTML = `
            <div class="progress-header">${time} dk Taraması</div>
            <div class="progress" style="width: 0%"></div>
            <span class="progress-text">0%</span>
        `;
        multiTimeContainer.insertBefore(progressDiv, multiTimeContainer.firstChild);
    }
    
    const progressBar = progressDiv.querySelector('.progress');
    const progressText = progressDiv.querySelector('.progress-text');
    progressBar.style.width = `${progress.percentage}%`;
    progressText.textContent = `${progress.percentage}%`;
    
    if (progress.percentage >= 100) {
        setTimeout(() => {
            if (progressDiv && progressDiv.parentNode) {
                progressDiv.remove();
            }
        }, 2000);
    }
}

// Sonuçları temizle (çoklu zaman aralığı için)
function clearMultiTimeResults() {
    document.querySelector('.multi-time-results-container').innerHTML = '';
}

// Sonuç tablosunu oluştur fonksiyonunun altına ekle:
function addClearResultsButton() {
    const multiTimeContainer = document.querySelector('.multi-time-results-container');
    if (!multiTimeContainer.querySelector('.clear-results-btn')) {
        const btn = document.createElement('button');
        btn.className = 'clear-results-btn';
        btn.textContent = 'Sonuçları Temizle';
        btn.onclick = clearMultiTimeResults;
        multiTimeContainer.prepend(btn);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // İlk filtre durumlarını ayarla
    Object.keys(filterStates).forEach(id => {
        const button = document.querySelector(`button[onclick="toggleFilter('${id}')"]`);
        if (button) {
            button.textContent = filterStates[id] ? 'Aktif' : 'Pasif';
            button.classList.toggle('active', filterStates[id]);
            const row = button.closest('.filter-row');
            if (row) row.classList.toggle('active', filterStates[id]);
            // Değer butonlarını aktif/pasif yap
            const valueButtons = document.querySelectorAll(`button[onclick^="updateValue('${id}'"]`);
            valueButtons.forEach(btn => {
                btn.disabled = !filterStates[id];
            });
            // Karşılaştırma butonlarını aktif/pasif yap (sadece RSI2 için)
            const comparisonButtons = document.querySelectorAll(`button[onclick^="setComparison('${id}'"]`);
            if (comparisonButtons.length > 0) {
                comparisonButtons.forEach(btn => {
                    btn.disabled = !filterStates[id];
                });
            }
        }
    });
    
    // İlk karşılaştırma operatörünü ayarla
    setComparison('rsi2', '≥');
    
    // Zaman butonları fonksiyonalitesi
    const timeButtons = document.querySelectorAll('.time-btn');
    timeButtons.forEach(button => {
        button.addEventListener('click', () => {
            const time = button.getAttribute('data-time');
            if (button.classList.contains('active')) {
                button.classList.remove('active');
                selectedTimes = selectedTimes.filter(t => t !== time);
            } else {
                button.classList.add('active');
                if (!selectedTimes.includes(time)) {
                    selectedTimes.push(time);
                }
            }
            console.log('Seçili zaman aralıkları:', selectedTimes);
        });
    });

    // Socket.IO bağlantısını başlat
    initializeSocket();

    // Periodic button state validation - every 3 seconds
    setInterval(() => {
        if (isAutoScanActive) {
            validateAndSyncButtonState();
        }
    }, 3000);

    // Filtre butonu fonksiyonalitesi
    const filterButton = document.querySelector('.filter-btn');
    filterButton.addEventListener('click', async (e) => {
        e.preventDefault();
        if (isScanning) {
            return; // Zaten tarama yapılıyorsa yeni tarama başlatma
        }
        if (!isConnected) {
            socket.connect();
        }
        // Zaman aralığı seçilmediyse uyarı ver
        if (selectedTimes.length === 0) {
            showMessage('error', 'Lütfen en az bir zaman aralığı seçin!');
            return;
        }

        // Önceki sonuçları temizle
        document.querySelector('.multi-time-results-container').innerHTML = '';
        addClearResultsButton();

        // Filtre butonunu devre dışı bırak
        filterButton.disabled = true;
        filterButton.textContent = 'TARANIYOR...';
        isScanning = true;

        try {
            // Çoklu zaman aralığı desteği
            const timesToSend = [...selectedTimes]; // Sadece seçili olanlar
            // Aktif filtreleri topla
            const filterData = {
                rsi1: filterStates.rsi1 ? document.getElementById('rsi1-value').textContent : null,
                rsi2: filterStates.rsi2 ? document.getElementById('rsi2-value').textContent : null,
                comparison: selectedComparison,
                hacim: filterStates.hacim ? document.getElementById('hacim-value').textContent : null,
                volume: filterStates.volume ? document.getElementById('volume-value').textContent : null,
                artis: filterStates.artis ? document.getElementById('artis-value').textContent : null,
                times: timesToSend,
                closingScan: isClosingScanActive,
                coinList: coinList,
                filterStates: {...filterStates}
            };

            // Çoklu zaman aralığı için dinleyicileri başlat
            listenMultiTimeEvents(timesToSend);

            const response = await fetch(`${SERVER_URL}/filter`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                mode: 'cors',
                body: JSON.stringify(filterData)
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const result = await response.json();
            if (result.status !== 'success') {
                throw new Error(result.message);
            }
        } catch (error) {
            console.error('Hata:', error);
            showMessage('error', 'Tarama sırasında bir hata oluştu! Lütfen tekrar deneyin.');
            filterButton.disabled = false;
            filterButton.textContent = 'FILTRELE';
            isScanning = false;
        }
    });

    // Filtre satırlarının tamamına tıklanabilirlik ekle
    document.querySelectorAll('.filter-row').forEach(row => {
        const toggleBtn = row.querySelector('.toggle-btn');
        if (toggleBtn) {
            row.addEventListener('click', (e) => {
                // Sadece toggle veya değer butonlarına tıklanmadıysa toggle et
                if (!e.target.classList.contains('btn')) {
                    toggleBtn.click();
                }
            });
        }
    });

    // CSS için stil ekle
    const style = document.createElement('style');
    style.textContent = `
    .table-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
        padding: 10px;
        background-color: #f5f5f5;
        border-radius: 8px;
    }

    .clear-results-btn {
        background-color: #ff4d4d;
        color: white;
        border: none;
        padding: 8px 15px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 14px;
        transition: all 0.3s ease;
    }

    .clear-results-btn:hover {
        background-color: #ff3333;
    }

    .multi-time-table {
        margin-bottom: 30px;
        background: white;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        padding: 15px;
    }

    .multi-time-table .table-header {
        background-color: #f8f9fa;
        color: #333;
        font-size: 16px;
        font-weight: bold;
    }

    .multi-time-table .results-table {
        width: 100%;
        margin-top: 10px;
        border-collapse: collapse;
    }

    .multi-time-table .results-table th,
    .multi-time-table .results-table td {
        padding: 12px;
        text-align: left;
        border-bottom: 1px solid #eee;
    }

    .multi-time-table .results-table th {
        background-color: #f8f9fa;
        font-weight: bold;
        color: #333;
    }

    .multi-time-table .results-table tr:hover {
        background-color: #f5f5f5;
    }

    .progress-bar[data-time] {
        margin-bottom: 15px;
        background-color: #f0f0f0;
        border-radius: 10px;
        overflow: hidden;
    }
    `;
    document.head.appendChild(style);

    // Stil güncellemesi
    const additionalStyle = document.createElement('style');
    additionalStyle.textContent = `
        .multi-time-results-container {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .multi-time-table {
            margin-bottom: 20px;
            background: var(--calculator-bg);
            border-radius: 12px;
            padding: 15px;
        }

        .multi-time-table .table-header {
            color: var(--text-color);
            font-weight: bold;
            margin-bottom: 10px;
            background: var(--calculator-bg);
            padding: 10px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }

        .multi-time-table .results-table {
            width: 100%;
            border-collapse: collapse;
        }

        .multi-time-table .results-table th,
        .multi-time-table .results-table td {
            padding: 10px;
            text-align: left;
            color: var(--text-color);
            border-bottom: 1px solid var(--border-color);
        }

        .multi-time-table .results-table th {
            font-weight: bold;
            background: var(--calculator-bg);
            border-bottom: 2px solid var(--border-color);
        }

        .multi-time-table .results-table tr:hover {
            background: var(--hover-bg);
        }

        .progress-header {
            color: var(--text-color);
            margin-bottom: 5px;
            font-weight: bold;
            background: var(--calculator-bg);
            padding: 8px;
            border-radius: 6px;
            border: 1px solid var(--border-color);
        }

        .progress-bar[data-time] {
            margin-bottom: 15px;
            background: var(--progress-bg);
            border-radius: 8px;
            overflow: hidden;
        }

        .progress-bar[data-time] .progress {
            background: var(--progress-fill);
        }

        .progress-bar[data-time] .progress-text {
            color: var(--text-color);
        }
    `;
    document.head.appendChild(additionalStyle);

    // Otomatik tarama butonu fonksiyonalitesi
    const autoScanButton = document.querySelector('.auto-scan-btn');
    if (autoScanButton) {
        autoScanButton.addEventListener('click', async () => {
            // Debounce protection
            const now = Date.now();
            if (now - lastButtonClick < BUTTON_DEBOUNCE_MS) {
                console.log('Button click ignored (debounce protection)');
                return;
            }
            lastButtonClick = now;
            
            // Validate current state before processing
            validateAndSyncButtonState();
            
            console.log('=== AUTO-SCAN BUTTON CLICKED ===');
            console.log('Current isAutoScanActive:', isAutoScanActive);
            console.log('Current button text:', autoScanButton.textContent);
            console.log('isConnected:', isConnected);
            console.log('socket.disconnected:', socket ? socket.disconnected : 'socket is null');
            
            // Eğer bağlantı yoksa yeniden bağlan
            if (!isConnected || !socket || socket.disconnected) {
                console.log('No connection, reinitializing socket...');
                initializeSocket();
                // Bağlantı kurulana kadar bekle
                await new Promise((resolve) => {
                    const checkConnection = () => {
                        if (isConnected) {
                            console.log('Connection established, continuing...');
                            resolve();
                        } else {
                            setTimeout(checkConnection, 100);
                        }
                    };
                    checkConnection();
                });
            }

            if (isAutoScanActive) {
                // Taramayı durdur
                console.log('=== STOPPING AUTO-SCAN ===');
                socket.emit('stop_auto_scan');
                autoScanButton.textContent = 'OTOMATİK TARAMA';
                autoScanButton.style.backgroundColor = '#4CAF50';
                isAutoScanActive = false;
                lastHeartbeat = null;
                appendToConsole('\nOtomatik tarama durduruldu.\n');
                console.log('Auto-scan stopped by user, button set to: OTOMATİK TARAMA');
            } else {
                // Zaman aralığı seçilmediyse uyarı ver
                if (selectedTimes.length === 0) {
                    showMessage('error', 'Lütfen en az bir zaman aralığı seçin!');
                    console.log('No timeframes selected, aborting auto-scan start');
                    return;
                }

                console.log('=== STARTING AUTO-SCAN ===');
                console.log('Starting auto-scan with times:', selectedTimes);

                // Aktif filtreleri topla
                const filterData = {
                    rsi1: filterStates.rsi1 ? document.getElementById('rsi1-value').textContent : null,
                    rsi2: filterStates.rsi2 ? document.getElementById('rsi2-value').textContent : null,
                    comparison: selectedComparison,
                    hacim: filterStates.hacim ? document.getElementById('hacim-value').textContent : null,
                    volume: filterStates.volume ? document.getElementById('volume-value').textContent : null,
                    artis: filterStates.artis ? document.getElementById('artis-value').textContent : null,
                    times: [...selectedTimes].sort((a, b) => parseInt(a) - parseInt(b)), // Sıralı zaman aralıkları
                    coinList: coinList,
                    filterStates: {...filterStates}
                };

                console.log('Filter data being sent:', filterData);

                // Konsolu temizle ve başlangıç mesajını göster
                const consoleDiv = document.getElementById('console-output') || createConsoleDiv();
                consoleDiv.innerHTML = 'Otomatik tarama başlatılıyor...\n';
                consoleDiv.style.display = 'block';

                // Otomatik taramayı başlat
                try {
                    socket.emit('start_auto_scan', filterData);
                    autoScanButton.textContent = 'TARAMAYI DURDUR';
                    autoScanButton.style.backgroundColor = '#ff4d4d';
                    isAutoScanActive = true;
                    lastHeartbeat = Date.now();
                    console.log('Auto-scan start event emitted successfully, button set to: TARAMAYI DURDUR');
                    console.log('isAutoScanActive set to:', isAutoScanActive);
                } catch (error) {
                    console.error('Error emitting start_auto_scan:', error);
                    showMessage('error', 'Otomatik tarama başlatılamadı. Bağlantı kontrol ediliyor...');
                    autoScanButton.textContent = 'OTOMATİK TARAMA';
                    autoScanButton.style.backgroundColor = '#4CAF50';
                    isAutoScanActive = false;
                    console.log('Auto-scan start failed, button reset to: OTOMATİK TARAMA');
                }
            }
            console.log('=== AUTO-SCAN BUTTON CLICK COMPLETED ===');
        });
    } else {
        console.error('Auto-scan button not found!');
    }
});

// Sayfadan ayrılırken socket bağlantısını kapat
window.addEventListener('beforeunload', (e) => {
    console.log('=== PAGE UNLOAD DETECTED ===');
    console.log('Reason: beforeunload event');
    console.log('isAutoScanActive:', isAutoScanActive);
    console.log('isConnected:', isConnected);
    
    // Only allow unload if user explicitly wants to leave
    if (isAutoScanActive && !isPageRefreshing) {
        e.preventDefault();
        e.returnValue = 'Otomatik tarama çalışıyor. Sayfayı kapatmak istediğinizden emin misiniz?';
        return e.returnValue;
    }
    
    if (socket) {
        socket.disconnect();
    }
});
