# Kripto Para Tarayıcı - Kullanım Kılavuzu

## 📊 Genel Bakış

Bu uygulama, kripto para piyasasını belirlediğiniz kriterlere göre taramanızı ve potansiyel fırsatları yakalamanızı sağlar. Otomatik veya manuel tarama seçenekleriyle, RSI, hacim ve fiyat değişimi gibi göstergeleri kullanarak coin'leri filtreleyebilirsiniz.

## 🚀 Başlangıç

1. Uygulamayı açtığınızda karşınıza gelen arayüzde çeşitli filtre seçenekleri ve zaman aralıkları bulunur.
2. Filtreler varsayılan olarak "Pasif" durumdadır. İstediğiniz filtreleri "Aktif" hale getirerek kullanabilirsiniz.

## 💡 Temel Özellikler

### 📋 Coin Listesi Yükleme
- "Coin Listesi Yükle" butonuna tıklayarak özel bir coin listesi yükleyebilirsiniz
- Desteklenen formatlar: .txt ve .csv
- Her satırda bir coin sembolü olmalıdır (örn: BTCUSDT)
- Liste yüklemezseniz, tüm coinler taranır

### ⚙️ Filtreler

#### RSI Filtreleri
- İki ayrı RSI filtresi bulunur
- Her filtre için + ve - butonlarıyla değeri ayarlayabilirsiniz
- RSI2 için ≤ (küçük eşit) veya ≥ (büyük eşit) karşılaştırma operatörlerini seçebilirsiniz

#### Hacim Filtreleri
1. **Göreceli Hacim**
   - Coin'in ortalama hacmine göre şu anki hacmini karşılaştırır
   - 1.0 değeri normal hacmi temsil eder
   - 2.0 değeri normalin 2 katı hacmi gösterir

2. **Hacim (USDT)**
   - Minimum USDT hacmini belirler
   - + ve - butonlarıyla değeri ayarlayabilirsiniz

#### Yüzde Artış Koşulu
- Coin'in fiyat değişim yüzdesini filtreler
- Pozitif veya negatif değerler kullanabilirsiniz

### ⏱️ Zaman Aralıkları
- 1, 3, 5, 10, 15 ve 30 dakikalık periyotlar mevcuttur
- Birden fazla zaman aralığı seçebilirsiniz
- En az bir zaman aralığı seçilmelidir

### 🔄 Tarama Modları

#### Manuel Tarama
1. "FILTRELE" butonu ile tek seferlik tarama yaparsınız
2. Sonuçlar her zaman aralığı için ayrı tablolarda gösterilir
3. Her tabloda coin sembolleri ve seçili filtrelere ait değerler listelenir

#### Otomatik Tarama
1. "OTOMATİK TARAMA" butonu ile sürekli tarama başlatırsınız
2. Seçilen zaman aralıklarında otomatik olarak tarama yapılır
3. Her mum kapanışında yeni sonuçlar gösterilir
4. Durdurmak için tekrar aynı butona basın

### 🔄 Sunucu Yönetimi
- "SUNUCUYU YENİDEN BAŞLAT" butonu ile sistemi yeniden başlatabilirsiniz
- Bu işlem tüm bağlantıları yenileyecektir

## 📊 Sonuçların Görüntülenmesi

- Her tarama sonucu ayrı bir tablo olarak gösterilir
- Tablolarda:
  - Coin sembolü
  - RSI değeri (filtre aktifse)
  - Göreceli hacim (filtre aktifse)
  - USDT hacmi (filtre aktifse)
  - Yüzde değişim (filtre aktifse)
- "Sonuçları Temizle" butonu ile mevcut sonuçları silebilirsiniz

## 💡 İpuçları

1. **Verimli Tarama İçin:**
   - Önce geniş filtrelerle başlayın
   - Sonuçlara göre filtreleri daraltın
   - Önemli coinler için özel liste kullanın

2. **Otomatik Tarama:**
   - Uzun süre çalıştıracaksanız daha uzun zaman aralıkları seçin
   - Çok sayıda filtre kullanmak işlem yükünü artırır

3. **Filtre Kombinasyonları:**
   - RSI ile hacim filtrelerini birlikte kullanmak etkili sonuçlar verir
   - Yüksek göreceli hacim ve RSI değerleri önemli hareketleri işaret edebilir

## ⚠️ Önemli Notlar

- Tarama sonuçları yatırım tavsiyesi değildir
- Her zaman kendi araştırmanızı yapın
- Otomatik tarama sırasında sayfayı kapatmadan önce taramayı durdurun
- Çok sayıda filtre ve kısa zaman aralığı seçmek sistem performansını etkileyebilir
