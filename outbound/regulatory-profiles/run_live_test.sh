#!/usr/bin/env bash
# WBS 10.2.5 — İYS/ETK (TR) + PECR/Ofcom (UK) profil parametreleri (BRD §14.3) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: BRD §14.3'te adı geçen iki rejim için outbound uyumluluk parametre setinin
# AUTHORITATIVE master'ı + tüketici (10.2.1–10.2.4) sürüklenme (drift) denetçisi (sunucu gerektirmez).
# Gerçek İYS/TPS-CTPS registry adapter senkronu (ADR-002), profile çözümleme (DPIA §5/SAD §19.3) ve
# panel parametre yönetimi (L1 T-06) F2'de gelir; bu modül onlara çözülecek DEĞERLERİ + sıkılaştırma yönünü
# + drift/monotonluk garantisini sağlar.
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon/MSISDN) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.2.5 regulatory-profiles: validate (statik spec/config/kapsama + crosscheck) =="
python3 regulatory_profiles_probe.py validate

echo
echo "== 10.2.5 regulatory-profiles: selftest (parametre motoru invariant'ları P1–P12) =="
python3 regulatory_profiles_probe.py selftest

echo
echo "== 10.2.5 regulatory-profiles: crosscheck (tüketici 10.2.1–10.2.4 sürüklenme denetimi — P10) =="
python3 regulatory_profiles_probe.py crosscheck

echo
echo "== 10.2.5 regulatory-profiles: check (örnek senaryolar — 8 pass + 15 degrade) =="
python3 regulatory_profiles_probe.py check samples

echo
echo "== 10.2.5 regulatory-profiles: behavior test (P1–P12) =="
python3 tests/regulatory_profiles_behavior_test.py

echo
if [ -n "${REGISTRY_ADAPTER_URL:-}" ]; then
  echo "REGISTRY_ADAPTER_URL set: canlı İYS/TPS-CTPS registry senkronu F2 entegrasyonunda — burada NOT."
else
  echo "Canlı İYS/TPS-CTPS registry senkronu + profile çözümleme (DPIA §5) SKIP — \${REGISTRY_ADAPTER_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı registry/çözümleme/panel parametre yönetimi gerçek entegrasyon (ADR-002/DPIA §5/L1 T-06) ile (SKIP burada)."
