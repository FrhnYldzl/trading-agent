# Crypto Railway Project — Setup Kılavuzu

Bu dokuman **YENİ** Railway projesi (`meridian-crypto` ya da `enthusiastic-delight`)
için adım adım yapılandırma rehberi. Mevcut equity Railway projesinin ayarlarına
**HİÇ DOKUNULMUYOR**.

## 0. Ön koşul

GitHub repo: `github.com/FrhnYldzl/trading-agent` — bu branch hazır olmalı:
```
claude/v5.8-abstract-bases
```
Bu branch'te `Dockerfile.crypto`, `crypto/`, `crypto_preview_app.py` ve
`static/crypto/` dosyaları var. Bu branch henüz `main`'e merge edilmedi —
**equity main'de tek satır değişmedi.**

## 1. Project Settings

### Source
- **Repository:** `FrhnYldzl/trading-agent`
- **Branch:** `claude/v5.8-abstract-bases`  ← KRİTİK, `main` değil
- **Root Directory:** `/` (boş bırak)

### Build
- **Builder:** `Dockerfile`  ← (Nixpacks değil!)
- **Dockerfile Path:** `Dockerfile.crypto`  ← KRİTİK
- (Build Command, Start Command alanlarını boş bırak — Dockerfile halleder)

### Deploy
- **Watch Paths** (auto-deploy filtresi — equity-only commit crypto'yu rebuild etmesin):
  ```
  Dockerfile.crypto
  requirements.txt
  server/crypto/**
  server/core/**
  server/crypto_preview_app.py
  server/static/crypto/**
  ```
- **Restart Policy:** `On Failure`, max 10 retries

## 2. Environment Variables

```
CRYPTO_ALPACA_API_KEY=PK7ONGDXJV7KMKID36D5HQX4US
CRYPTO_ALPACA_SECRET_KEY=7iTg9JAZ4b59YMzG1YYG2qW5RqNirZJx4tntMJ1qzHbv
CRYPTO_ALPACA_PAPER=true
CRYPTO_ACCOUNT_LABEL=Ferhan Crypto Paper #1

# Cross-module navigation (custom domain alınca güncelle)
MERIDIAN_EQUITY_URL=https://<equity-railway-url>.up.railway.app
MERIDIAN_CRYPTO_URL=https://<crypto-railway-url>.up.railway.app
MERIDIAN_OPTIONS_URL=https://<options-railway-url>.up.railway.app
```

⚠️ **DİKKAT:** Equity'nin `ALPACA_API_KEY` env var'ını bu projeye ASLA ekleme.
Her proje kendi paper hesabını kullansın.

## 3. Domain

- Railway otomatik bir URL verir: `<service-name>-production.up.railway.app`
- Custom domain için: Settings → Networking → Add Domain
- İdeal: `crypto.meridian.app` (CNAME `<railway-url>`'e işaretler)

## 4. Deploy

Yukarıdaki ayarlar tamamlanınca → "Deploy Latest" tıkla.

### Beklenen log
```
Initialization (✓)
Build (✓ ~1-2 dk, Docker image)
Deploy > Create container (✓ ~10sn)
Post-deploy (✓ uvicorn başlar)
```

### Health check
Deploy sonrası Railway URL'ine git: `/api/crypto/health` 200 dönmeli.
JSON içinde:
```json
{
  "status": "ok",
  "version": "5.9-ε",
  "asset_class": "crypto",
  "account_label": "Ferhan Crypto Paper #1",
  "is_dedicated_account": true,
  "paper": true
}
```

## 5. Hata giderme

### "The executable 'cd' could not be found"
→ Builder Nixpacks'e düşmüş, Procfile'ı okuyor.
→ Settings → Build → Builder = `Dockerfile` ve Dockerfile Path = `Dockerfile.crypto` olduğunu kontrol et.

### "FileNotFoundError: Dockerfile.crypto"
→ Branch yanlış. Settings → Source → Branch = `claude/v5.8-abstract-bases` mı?
→ Branch GitHub'a pushlandı mı? Local commit yetmez.

### Crypto endpoint'leri 404
→ `crypto_preview_app.py` çalışıyor mu? Logs'ta `Uvicorn running on http://0.0.0.0:$PORT` görmeli.
→ FastAPI title "Trading Agent — Crypto Preview" olmalı.

### `account_label = "Default (Equity Paper)"` çıkıyor
→ `CRYPTO_ALPACA_API_KEY` env var'ı set edilmemiş, equity key'ine fallback yaptı.
→ Variables tab'ında ekle, redeploy.

## 6. Equity projesi etkilendi mi?

**HAYIR.** Equity Railway projesi:
- Kendi dashboard'ında, kendi env'inde, kendi service'inde
- `main` branch'inden deploy ediyor (V5.7, broad scan açık)
- `Dockerfile`'ı (eski) kullanıyor — `main:app` çalıştırıyor
- ALPACA_API_KEY env'i değişmedi
- Crypto projesinin başarılı/başarısız deploy'u equity'i etkilemiyor

Equity'nin URL'ini ziyaret edip hâlâ çalıştığını doğrulayabilirsin.
