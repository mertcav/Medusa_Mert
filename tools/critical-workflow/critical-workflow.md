# Kritik İşlem Workflow Durum Makinesi (WBS 7.3.1)

> **İz:** BRD §13 (Konuşma Güvenliği ve Davranış Kuralları) · FR-TOOL-006/007 · FR-IAM-005/006 · FR-AUTH-003 · SAD §11.1/§11.3 · ADR-001/002/012
> **Faz:** F1 · **Öncelik:** Must · **Workstream:** 7.3 Deterministic workflow engine (İLK modül)
> Kaynak doğruluk `docs/BRD.md` §13 + `critical-workflow-spec.json`. Çelişkide BRD/SAD esastır.

## 1. Amaç ve kapsam

BRD §13 emreder: agent **kredi/sigorta uygunluğu, sağlık teşhisi, hukuki tavsiye, sözleşme iptali,
yüksek tutarlı ödeme, iletişim bilgisi değişikliği, banka hesabı değişikliği, hassas PII açıklaması,
limit üstü iade/ödeme** gibi işlemlerde **serbest karar VERMEMELİDİR**. Bu işlemler için **6 zorunlu adım**:

1. **kimlik doğrulama** (auth)
2. **kurallı workflow** çalıştırılmalı (kural)
3. işlem müşteriye **özetlenmeli** (özet)
4. açık **teyit** alınmalı (teyit)
5. gerekirse insan **onayı** alınmalı (onay)
6. işlem sonucu **audit** log'a yazılmalıdır (audit)

Bu modül o 6 adımı bir **deterministik durum makinesi (FSM)** olarak gerçekler. 7.2.5
(reference-integration) zincirindeki tek-atımlık `policy_gate` (confirmation∧step_up boolean) **yerine**
bu modül kritik-işlem akışının **tam çok-adımlı stateful FSM'ini sahiplenir** (7.2.5 bunu açıkça
"kritik-işlem TAM durum makinesi→7.3.1/7.3.2" diye erteledi). FSM `EXECUTE`'a ulaştığında gerçek tool
eylemini 7.2.x tool zincirine **delege eder**; bu modül o zincirin tükettiği **teyit/step-up/onay
kararlarını üretir**.

## 2. Durum makinesi

```
INIT ─► AUTH(1) ─► RULE(2) ─► SUMMARY(3) ─► CONFIRM(4) ─► APPROVAL(5) ─► EXECUTE ─► AUDIT(6) ─► COMMITTED
          │           │                         │              │             │            ▲
          ▼           ▼                         ▼              ▼             ▼ (fault)     │
        DENIED      DENIED                   ABORTED         DENIED        FAILED ─────────┘
     (auth/step) (risk/kural)            (teyit yok/hayır) (onay/maker)
          └────────────────────── EXPIRED (deadline, bekleyen durumda) ──────────────────┘
                                            (her terminal → AUDIT → değiştirilemez kayıt)
```

| Durum | BRD §13 adım | Kapı | Başarısız → |
|-------|--------------|------|-------------|
| `AUTH` | 1 kimlik doğrulama | seviye ≥ risk-class tabanı ∧ (gerekiyorsa) step-up; caller_id tek başına güçlü değil (FR-AUTH-001) | `DENIED(AUTH_INSUFFICIENT/STEP_UP_REQUIRED)` |
| `RULE` | 2 kurallı workflow | kural tablosundan etkin gereksinim seti; forbidden_autonomous/tutar eşiği → eskalasyon | `DENIED(UNKNOWN_RISK_CLASS/RULE_BLOCKED)` |
| `SUMMARY` | 3 müşteriye özet | hassas değer maskeli (FR-AUTH-005) | — (teyit ön-koşulu) |
| `CONFIRM` | 4 açık teyit | yalnız `value=yes` ilerletir (FR-TOOL-006) | `ABORTED(CUSTOMER_DECLINED/CONFIRMATION_NOT_OBTAINED)` |
| `APPROVAL` | 5 gerekirse insan onayı | `approved` ∧ onaylayan ≠ talep eden (FR-IAM-005 maker-checker) | `DENIED(APPROVAL_REQUIRED/REJECTED/MAKER_CHECKER_VIOLATION)` |
| `EXECUTE` | — | 7.2.x'e delege (tüm kapılar geçti) | `FAILED(<fault_class>)` |
| `AUDIT` | 6 audit | her terminal sonuç değiştirilemez kayıt (FR-IAM-006) | — |

Terminal durumlar: `COMMITTED` · `FAILED` · `DENIED` · `ABORTED` · `EXPIRED` · `ERROR` — **immutable** (K8).

## 3. Kurallı workflow (RULE — adım 2)

`config/workflow-policies.json` BRD §13 listesini `risk_class → {min_auth_level, requires_step_up,
requires_confirmation, requires_human_approval}` tablosuna eşler. **Agent bu kararları kendi üretmez**
(BRD §13). RULE durumu deterministik **dinamik eskalasyon** uygular:

- `forbidden_autonomous=true` (kredi/sigorta uygunluğu, sağlık teşhisi, hukuki tavsiye) → `requires_human_approval` **zorlanır** (agent asla tek başına karar veremez).
- `params.amount > amount_threshold` (yüksek tutarlı ödeme / limit üstü) → `requires_human_approval` **zorlanır**.
- Bilinmeyen `risk_class` → **fail-closed** `DENIED(UNKNOWN_RISK_CLASS)`.

## 4. Invariant'lar (K1–K12)

| ID | Özet |
|----|------|
| K1 | Sıralı fail-closed kapı geçişi; EXECUTE yalnız tüm gerekli kapılar pass ise erişilir |
| K2 | Auth ön-koşulu; caller_id tek başına güçlü değil; hassas işlem step-up ister |
| K3 | Kural-güdümlü gereksinim; forbidden_autonomous → insan onayı; bilinmeyen risk → fail-closed |
| K4 | Özet-önce-teyit (teyit, özet emit edilmeden erişilemez) |
| K5 | Açık olumlu teyit; teyit alınmadan kritik işlem yürütülmez (SR-TOOL-006) |
| K6 | Gerekli insan onayı maker-checker (onaylayan ≠ talep eden); reddedilen/eksik → DENIED |
| K7 | Para/sözleşme/PII → ek doğrulama (step-up) zorunlu (SR-TOOL-007) |
| K8 | Terminal-immutable (WORM hizalı) |
| K9 | Deadline/zombie yok; bekleyen durum deadline aşımı → EXPIRED |
| K10 | Terminalde daima değiştirilemez audit; no-log (ham PII/secret yok) |
| K11 | Hassas veri sesli tam tekrarlanmaz (özet maskeli; FR-AUTH-005) |
| K12 | Determinizm (tohumlu sanal saat; Date.now/random yok) |

## 5. Mimari konum ve sorumluluk sınırı

FSM, orkestratör turn döngüsünün **üstünde** bir oturum-durumu makinesidir; hot-path turn'ünü
**bloklamaz** (bekleyen durumlar deadline'lı oturum belleğinde tutulur). Sahiplik/delege:

| Sorumluluk | Sahip |
|------------|-------|
| BRD §13 6-adım kompozisyon + kapı sırası + fail-closed geçiş + audit kaydı | **Bu modül (7.3.1)** |
| Kimlik doğrulama mekanizması (OTP/KBA/step-up üreteci) | 8.x (FR-AUTH-001..005) — seviye **tüketilir** |
| Müşteri teyidi toplama + ek-doğrulama ayrıntısı | 7.3.2 (FR-TOOL-006/007) — hook **tüketilir** |
| Gerçek tool dispatch/transport (EXECUTE) | 7.2.x (7.2.5 zinciri [1]→[7]) — outcome **tüketilir** |
| Müşteriye hata metni | 7.1.5 (FR-TOOL-008) |
| Audit store / correlation zenginleştirme | 7.1.6 + 12.1.8 (FR-TOOL-010/FR-IAM-006) — kayıt **üretilir** |
| Maker-checker onay kuyruğu UI | 12.1.7 (FR-IAM-005) |
| Output guard (yasak içerik üretimi) | 3.3.x (FR-LLM-009) |

## 6. Doğrulama (probe)

```
critical_workflow_probe.py validate     # statik spec/config/kapsama kapısı (72/72)
critical_workflow_probe.py run <sample> # FSM-yürütücü + kapı (K1–K12)
critical_workflow_probe.py selftest     # gömülü davranış (36/36)
critical_workflow_probe.py schema       # durum/olay/sonuç sözleşmesi
```

`run_live_test.sh` statik + selftest + behavior (27/27) + 11 sample kapısını koşar. Vendor-neutral
(ADR-002); sır/credential ve gerçek PII repoya yazılmaz (fixture'lar sentetik — FR-TST-008).
