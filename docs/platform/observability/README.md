# `docs/platform/observability/` — Gözlemlenebilirlik omurgası iskeleti (WBS 0.4.7)

OTel + Prometheus + Grafana + Loki iskeleti. Kaynak doğruluk: `observability-spec.json`
(makine-okunur metrik/span/alarm katalogları) + tasarım: `observability-backbone.md`. →SAD §17, BRD §15.

## İçerik
- `observability-backbone.md` — tasarım dokümanı (mimari, span modeli, kardinalite disiplini, alarmlar, izlenebilirlik).
- `observability-spec.json` — makine-okunur kaynak doğruluk; probe bunu doğrular.
- `observability_probe.py` — stdlib-only doğrulayıcı (vendor-neutral, credential-free).
- `config/` — skeleton config'ler: `otel-collector.yaml`, `prometheus.yml`, `alerts.yaml`, `loki.yaml`, `grafana-dashboard-voice-runtime.json`.

## Komutlar
```bash
python3 observability_probe.py selftest   # kapı/invariant/determinizm (11/11)
python3 observability_probe.py validate    # spec + config tamlık kapısı → çıkış kodu
python3 observability_probe.py coverage    # BRD §15 / SAD §17.2 kapsam matrisi
python3 observability_probe.py schema      # spec şeması + kapı tanımı
```

## Notlar
- **Vendor-neutral / credential-free:** açık standartlar; endpoint/secret `${ENV}` ile (repoya sır yazılmaz).
- İskelet kapısıdır; tam YAML şema doğrulaması canlı CI'da (0.4.4: `promtool`/`otelcol validate`).
- F1'de WBS §14.1 görevleri bu iskeleti gerçek kodla doldurur.
