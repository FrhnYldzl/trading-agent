# TradingView Trading Agent — Alpaca Paper Trading

EMA Cross sinyallerini TradingView'den alıp Alpaca Paper Trading API'sine ileten otomasyon sistemi.

## Proje Yapısı

```
trading-agent/
├── pine_script/
│   └── strategy.pine      # Pine Script v5 — EMA Cross stratejisi
├── server/
│   ├── main.py            # FastAPI webhook sunucu
│   ├── broker/
│   │   ├── __init__.py
│   │   └── equity.py      # Alpaca Paper Trading entegrasyonu
│   ├── risk_manager.py    # Pozisyon büyüklüğü ve risk hesaplama
│   └── database.py        # SQLite işlem logu
├── .env.example           # API anahtarı şablonu
├── requirements.txt       # Python bağımlılıkları
└── README.md
```

## Kurulum

### 1. Python ortamı hazırla

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. API anahtarlarını ayarla

```bash
cp .env.example .env
# .env dosyasını aç ve gerçek değerleri gir
```

`.env` dosyasına yazılacaklar:
- `ALPACA_API_KEY` ve `ALPACA_SECRET_KEY` → [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading → API Keys
- `WEBHOOK_SECRET` → istediğin güçlü bir şifre (TradingView'de de kullanacaksın)

### 3. Sunucuyu başlat

```bash
cd server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Test et

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","action":"long","price":185.50,"secret":"test123"}'
```

### 5. TradingView'de alert kur

1. `pine_script/strategy.pine` dosyasını TradingView Pine Editor'e yapıştır
2. Strateji ayarlarından `Webhook Secret` alanına `.env`'deki `WEBHOOK_SECRET` değerini gir
3. Alert oluştur:
   - **Condition**: EMA Cross — Webhook Bot → Order fills only
   - **Webhook URL**: `http://SUNUCU_IP:8000/webhook`
   - **Message**: (boş bırak — `alert_message` parametresinden otomatik gelir)

## API Endpoint'leri

| Method | URL | Açıklama |
|--------|-----|----------|
| POST | `/webhook` | TradingView sinyalini işle |
| GET | `/trades` | Son işlemleri listele |
| GET | `/account` | Alpaca bakiyesini göster |
| GET | `/health` | Sunucu durumu |
| GET | `/docs` | Swagger UI |

## Desteklenen Aksiyonlar

| action | Açıklama |
|--------|----------|
| `long` | Alım emri ver |
| `short` | Açığa satış emri ver |
| `close_long` | Long pozisyonu kapat |
| `close_short` | Short pozisyonu kapat |

---

## GÜVENLİK KURALLARI

- API anahtarlarını `.env` dosyasında sakla, asla koda gömme
- Alpaca API'sinde sadece "Trade" yetkisi ver — "Withdrawal" KAPALI olsun
- `WEBHOOK_SECRET` ile gelen sinyalleri doğrula
- Gerçek parayla test etmeden önce paper trading modunu kullan

## RİSK UYARISI

Otomatik trading sistemleri finansal kayba yol açabilir.
Bu kod eğitim amaçlıdır. Gerçek işlemlerde kullanım kişinin sorumluluğundadır.
