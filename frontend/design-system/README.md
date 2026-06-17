# WBS 13.1.3 — Tasarım sistemi / komponent kütüphanesi + i18n (TR/EN)

**Faz:** F1 · **Öncelik:** Must · **İz:** SAD §14.4.1 · FR-TEN-004 (tenant dil/bölge) · FR-TTS-004 (sayı/tarih/para — panel Intl karşılığı) · BRD §16 (residency UK/EU/NA/ME) · BRD §17 (L0/L1/L2 ekran etiketleri) · WCAG 2.1 AA · ADR-002 (vendor-neutral) · ADR-011 (her app'te vendored, cross-app import yok — A7)

**13.1 "Ortak frontend altyapısı"** alt-bloğunun **üçüncü** modülü. 13.1.1 iki ayrı Next.js app + route group **iskeletini**, 13.1.2 çalışma-anı **middleware kapısını** kurdu; bu modül her iki app'e **ortak bir tasarım sistemi + i18n (TR/EN)** katmanı ekler:

```
TOKEN PARITY → i18n KATALOG PARITY (TR↔EN) → WCAG KONTRAST → A11Y → LOCALE-AGNOSTİK KOMPONENT →
HTML lang/dir → LOCALE MÜZAKERE → globals↔token TUTARLILIK → SIR/PII YOK
```

## Tek kaynak doğruluk + per-app vendored kopya

| Canonical (kaynak doğruluk) | Her app vendored kopya |
|---|---|
| `config/design-tokens.json` (RMC token + contrast_pairs + locales) | `{app}/lib/ui/design-tokens.json` |
| `i18n/tr.json`, `i18n/en.json` (TR varsayılan) | `{app}/lib/i18n/{tr,en}.json` |

Probe **canonical-hash** ile drift'i FAIL eder. **ADR-011 blast-radius** gereği çekirdek runtime cross-app import YOK (A7); tasarım sistemi presentasyonel/güvenlik-dışı olduğundan **senkron probe** ile garanti edilir (13.1.2 middleware-core ile aynı disiplin).

## Çekirdek ilke (A8 — SAD §14.4.1)

> **Komponentler PRESENTASYONEL + locale-AGNOSTİK; UI yalnız görsel kapı.**

- `lib/ui/components.tsx` **i18n import etmez**; tüm kullanıcı-görünür metin **prop** olarak gelir → gömülü TR/EN cümle YOK. Yerelleştirme yalnız **çağrı yerinde** `t()` ile (layout'lar `t()` kullanır — dead-code değil).
- **İş mantığı/authz YOK**: rol→permission kararı 12.2.x backend'de; oturum/realm/tenant scope 13.1.2 middleware'de.

## RMC design token (`config/design-tokens.json`)

Markalı `.docx` hattıyla hizalı **RMC mavisi `#1F4E79`** birincil renk. Renk/tipografi/ölçü/yarıçap/gölge/z-index/breakpoint → `app/globals.css`'te `:root` altında `var(--rmc-*)` CSS değişkenleri. **WCAG kontrast** her `contrast_pair` için **deterministik hesaplanır** (sRGB→lineer→bağıl parlaklık): metin **≥4.5** (1.4.3), UI **≥3.0** (1.4.11). 15 çift tanımlı, tümü geçer.

> **Bugfix (probe ile yakalandı):** ilk `success_fg #1E7E45` (success-bg üstüne 4.48 < 4.5) ve `border_strong #9AA7B8` (beyaz üstüne 2.44 < 3.0) WCAG kapısını **eledi** → `#1B7340` (5.18) ve `#7C899B` (3.55) ile düzeltildi; canonical + her app + globals.css senkron güncellendi.

## Komponent kütüphanesi (`lib/ui/components.tsx`)

`Button` · `StatusPill` · `Card` · `PageHeader` · `Alert` · `Field` · `Table` · `Spinner` · `EmptyState` · `SkipLink` · `VisuallyHidden` · `LangSwitcher`. Hepsi presentasyonel, locale-agnostik, token ile stillenir, RSC-uyumlu (`'use client'` yok). Etkileşimli öğeler erişilebilir ad ister; durum bölgeleri `role=status/alert`; renk tek-başına anlam taşımaz.

## i18n çekirdeği (`lib/i18n/index.ts` — saf/deterministik)

| Fonksiyon | Sözleşme |
|---|---|
| `negotiateLocale({query?,cookie?,acceptLanguage?})` | `?lang` > çerez > Accept-Language > **default `tr`** |
| `t(catalog, "a.b.c", params?)` | dotted path + `{placeholder}` interpolasyon; eksik anahtar → anahtarın kendisi |
| `formatDate/Number/Currency(locale, …)` | Intl (`tr-TR`/`en-GB`) — FR-TTS-004 panel karşılığı |
| `dir(locale)` | `ltr`/`rtl` — TR/EN ltr; harita **RTL-hazır** (ME/AR → F2+) |

**i18n katalog invariant'ı:** TR ve EN **birebir aynı anahtar kümesi + aynı `{placeholder}` kümesi**; boş değer (untranslated) yasak. Sunucu-tarafı locale `lib/i18n/server.ts → getServerLocale()` (çerez `rmc_lang` + Accept-Language) ile çözülür; root layout `<html lang dir>` ayarlar.

## Kapı (probe)

`design_system_probe.py` (stdlib-only, deterministik, credential-free):

| Komut | İşlev |
|-------|-------|
| `validate` | Canonical + **ON-DISK** vendored kopya + WCAG kontrast + a11y + globals↔token invariant kapısı (D1–D12) → çıkış kodu |
| `check <sample\|dizin>` | Davranış: `locale` müzakere / `translate` interpolasyon / `contrast` / `parity` senaryoları |
| `selftest` | Gömülü davranış + WCAG + parity kontrolleri → çıkış kodu |
| `schema` | Karar/sözleşme özeti |

**İnvariant'lar (HARD kapılar, 0-ihlal):** D1 dosya/canonical · D2 token parity · D3 i18n parity · D4 key-set parity · D5 placeholder+boş · D6 WCAG kontrast (≥12 çift) · D7 a11y temelleri · D8 locale-agnostik komponent · D9 html lang/dir · D10 müzakere sözleşmesi · D11 globals↔token · D12 sır/PII yok + vendor-neutral.

## Sonuçlar

- `selftest` **23/23** 🟢 · `validate` **73/73** 🟢 · `check samples` **11/11** 🟢 (6 pass + 5 degrade) · davranış testi **23/23** 🟢
- `tsc --noEmit` her iki app 🟢 · `next build` her iki app 🟢 (platform 9 route + tenant 26 route + middleware)
- **Canlı smoke (next start + curl, sentetik oturum) — gerçek çalışma-anı kanıtı:**

| Senaryo | Sonuç |
|---|---|
| platform geçerli oturum + default | `<html lang="tr" dir="ltr">` · nav "Genel Bakış" · skip "İçeriğe geç" |
| platform `Accept-Language: en-GB` | `<html lang="en">` · nav "Overview" · skip "Skip to content" |
| platform `rmc_lang=en` çerez | `<html lang="en">` (çerez override) |
| tenant L1 `/admin/users` TR→EN | "Kullanıcılar / Roller" → "Users / Roles" |
| tenant L2 `/workspace/live-calls` TR→EN | "Canlı Çağrılar" → "Live Calls" |
| oturumsuz (13.1.2 regresyon) | **307** redirect · `X-Robots-Tag: noindex` (13.1.1 intact) |

```bash
python3 design_system_probe.py selftest
python3 design_system_probe.py validate
python3 design_system_probe.py check samples
./run_live_test.sh            # statik + tsc + build; SMOKE=1 ile canlı <html lang> smoke
```

## Kapsam dışı (bilinçli — başka modül sahibi)

rol→permission + kaynak sahipliği → **12.2.x backend**; oturum/tenant scope/realm ayrımı → **13.1.2 middleware**; PII maskeleme → **13.1.4**; ekran içi içerik/iş mantığı → **13.2/13.3/13.4**; client interaktivite (form submit, çerez-kalıcılaştıran dil-değiştir route) → **13.2+ client island'lar**; gerçek **AR katalogu + RTL stilleri** → **F2+** (mimari `rtl_ready` bırakıldı). Vendor-neutral (ADR-002; i18n SaaS/kütüphane bağlanmaz, Intl stdlib). Sır/credential repoya yazılmadı.
