# A-12 — Çağrı Detayı / Transkript & Timeline · WBS 13.4.12

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) **on birinci** implemente edilen ekranı. TEK bir çağrının
**detayını** sunar: **çağrı özeti** (süre · tur · olay · araç çağrısı · barge-in · düşük-güven · maskeli · erişim),
**çağrı künyesi** (yön · agent · sonuç · süre · kayıt · transkript · saklama · erişim), **olay zaman çizelgesi**
(DB §23 `call_event` — yapısal olaylar), **transkript** (DB §21 `transcript_segment` — speaker · offset ·
redaction'lı metin · güven) ve **erişim & redaction sağlığı**. **A-11'den farkı:** A-11 çağrı LİSTESİ +
arama/filtreleme (yalnız META); **A-12 tek çağrının zaman çizelgesi + transkript + olaylarını** (içerik) gösterir.

## İçerik kapısı (ÇEKİRDEK)
Transkript **İÇERİĞİ** yalnız iki koşul birlikte sağlanırsa gösterilir:
- **Redaction TAMAM** (`transcriptState === "redacted"` — FR-REC-004): `pending` ise içerik gizlenir.
- **Erişim AUDIT'li** (`accessAudited === true` — FR-REC-009): işaretsizse erişim engellenir (danger).

`transcriptViewable = redacted && accessAudited`. Aksi halde içerik yerine kapı mesajı (redaction-beklemede /
auditsiz-erişim / transkript-yok) gösterilir.

## Hijyen + güvenlik — İKİ KATMAN
A-12 transkript içeriğini gösterdiği için **iki katmanlı** guard uygular (`assertSafe`):
1. **Yapısal anahtar** (`assertNoForbiddenKeys`): ham kimlik/iş-içeriği (ham ses kaydı, **ham transkript blob'u**,
   e164/numara, müşteri PII, kart-OTP, çağrı özeti) + sır/credential + nesne-depo URI alan **ADI** taşınamaz
   (`FORBIDDEN_PII_KEYS` + `FORBIDDEN_SECRET_KEYS` — BRD §17.7 + NFR 10.6). `text` (tur metni) **izinlidir**.
2. **İçerik redaction** (`assertRedactionClean`): hiçbir string değer ham PII **DESENİ** (≥7 ardışık rakam →
   telefon/kart/poliçe/hesap; e-posta; `+`rakam; kart-bloğu; IBAN) taşıyamaz (`RAW_PII_PATTERNS` — FR-REC-004/005).
   PII yalnız **MASK_TOKEN `[•••]`** olarak görünür (redaction panel görüntülemelerinde de uygulanır — BRD §17.7).

Kayıt dinleme **derin aksiyondur**: yalnız durum + (görsel) oynatma kapısı; ham ses BYTE'ı / nesne-depo URI'si /
imzalı-URL panele KONMAZ (NFR 10.6); dinleme audit'li erişimle backend'de (API §6 + WBS 11.6).

## Kaynak gereksinimler
- **BRD §17.5** A-12 "Çağrı Detayı / Transkript & Timeline" (Çağrı zaman çizelgesi, transkript, olaylar).
- **FR-REC-004** transkript PII redaction (içerik kapısı) · **FR-REC-005** kart/parola/OTP gizleme (`maskedTurns`).
- **FR-REC-008** yetkili dinler/görür · **FR-REC-009** erişim audit (erişim kapısı `accessBlocked`).
- **FR-REC-001/002/003** kayıt durumu + kanal · **FR-REC-006/007/010** saklama/yasal-tutma (künye).
- **FR-ANA-002/003** outcome · **DB §21** transcript_segment (speaker/text/confidence) · **DB §23** call_event ·
  **SAD §6.1** turn state machine (barge-in/transfer) · **BRD §15** zaman damgası + word confidence · **BRD §14.2**
  AI bildirimi/karşılama · **FR-HND** insan aktarımı · **FR-TOOL** tool çağrısı · **FR-KB** RAG retrieval.
- **BRD §17.6** RBAC · **§17.7** hijyen · **FR-TEN-002** tenant scope · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2 A-12 satırı)
`operations_manager`=**Yönet** · `conversation_designer`=**Görüntüle** · `qa_analyst`=**Yönet** (kalite skorlama
bağlamı) · `human_agent`=**Görüntüle (kendi)**. A-11'e göre tek fark: qa_analyst A-11'de Görüntüle, A-12'de Yönet.
`tenant_owner` kural 17.7 ile Yönet. UI yalnız görsel kapı; nihai yetki + erişim-audit backend + RLS. Permission-key:
`calls:read`.

## Dosyalar
- `a12-call-detail-spec.json` — kaynak doğruluk + invariant (S1..S8) + referans anahtarlar + placeholder'lar.
- `a12_call_detail_probe.py` — stdlib-only probe (`validate`/`check`/`selftest`/`schema`); `lib/tenant/call-detail.ts`
  saf yardımcılarının Python aynası.
- `samples/detail-{clean,issues}.json` — `$expect` ile sentetik görüntülenebilir + erişim-engelli detay (FR-TST-008).
- `tests/a12_call_detail_test.py` — üç kapının çıkış kodu davranış testi.
- `run_live_test.sh` — canlı smoke (next build+start+curl; credential-free).

## Çalıştırma
```
python3 a12_call_detail_probe.py selftest    # pozitif/negatif kendi-testleri (içerik/erişim kapısı + İKİ KATMAN guard)
python3 a12_call_detail_probe.py check       # saf çekirdek + samples
python3 a12_call_detail_probe.py validate    # on-disk sayfa + seam + i18n + spec (S1..S8)
python3 a12_call_detail_probe.py schema      # görünüm şema özeti
bash run_live_test.sh                        # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek çağrı/olay/transkript besleme (Call Store + Event + Transcript — DB §19/§21/§23, RLS tenant-scope) → F1 §14.1.
- PII redaction + kart/OTP scrub ÜRETİMİ → WBS 11.3/11.4 (FR-REC-004/005); bu ekran yalnız redaction SONUCUNU yansıtır.
- Kaydı dinleme + transkript export + erişim-audit YAZIMI → API §6 + WBS 11.6 (görsel kapı; ham ses/URI yok).
- `/workspace/call/[callRef]` dinamik routing + çağrı seçimi → F1 (bu dilim tek temsili detayı besler).
- QA skorlama (otomatik + manuel) → A-13 (FR-EVAL-*).
- Vendor-neutral (ADR-002; belirli kayıt/depo/CDR/STT markası bağlanmaz); sır/credential repoya yazılmadı.
