# 7.2.3 — Endpoint allowlist (onaysız endpoint engelleme)

`F1` · `Must` · → **FR-TOOL-012** · SAD §11.2 / §14 · ADR-014 · TM-E-06 / SEC-06 / SEC-20

> Kaynak doğruluk `endpoint-allowlist-spec.json`'dur; bu belge tasarımı/gerekçeyi anlatır. Çelişkide
> BRD/SAD esastır.

## 1. Amaç ve kapsam

Tool/Integration Gateway dış ağa çok sayıda giden bağlantı kurar. **FR-TOOL-012:** *"Onaylanmamış
endpoint'lere erişim engellenmelidir."* Bu modül, Tool Yürütme Hattının (SAD §11.1) **egress karar
gate'idir**: connector (7.2.1 REST / 7.2.2 SOAP/GraphQL/webhook) bir **kanonik endpoint + çözülmüş
hedef** üretir; gate o hedefi tenant-tanımlı **allowlist** ile karşılaştırıp **PERMIT/DENY** karar verir.
**DENY ise istek WIRE'a gitmez** — connector `upstream_call`'a inmez, `AttemptOutcome` üretilmez.

[ADR-014](../../docs/adr/0014-zorunlu-egress-kontrol.md) *Zorunlu egress kontrol katmanı (egress proxy +
merkezi allowlist)* kararının **uygulama-katmanı karar çekirdeği** budur. Ağ-katmanı egress proxy
enforcement'ı 17.1.4 / 0.4.x platform engineering kapsamında **aynı allowlist mantığını** her bağlantıda
yeniden uygular (defense-in-depth). [SEC-06](../../docs/THREAT_MODEL.md) (egress yalnız allowlist
üzerinden; iç metadata endpoint engeli) + SEC-20 (egress kontrol) tasarım kontrollerini gerçekler;
[TM-E-06](../../docs/THREAT_MODEL.md) (SSRF — tool/webhook ile iç ağ/metadata endpoint'e erişim) tehdidini
kapatır.

**Bu modül SADECE karar verir.** Kanonik endpoint/target **üretimi** connector'ın (7.2.1/7.2.2);
timeout/retry/breaker **orkestrasyonu** 7.1.4'ün; ağ-katmanı proxy enforcement 17.1.4'ün işidir.

## 2. Hattaki konum

```
LLM tool call ─► [1] input schema ─► [2] authz ─► [3] policy gate ─► [4] idempotency
              ─► [EGRESS GATE: connector kanonik endpoint+target üretir → allowlist KARAR]   ◄── bu modül
              ─► PERMIT ? [5] Integration GW {timeout+retry+breaker} ─► connector.upstream_call(req)
                       : DENY  short-circuit (ENDPOINT_NOT_ALLOWED — WIRE'a gitmez)
              ─► [6] output schema + error normalization ─► [7] correlation_id audit
```

Karar **saf**tır (clock/random yok, A10) — aynı policy+target → aynı karar. Voice-runtime hot-path
(orchestrator ACT) ama gecikme katkısı ihmal edilebilir (ağ I/O yok). `authz` (7.1.2 "agent bu tool'u
çağırabilir mi") ile allowlist (7.2.3 "bu endpoint'e gidilebilir mi") **dik** boyutlardır.

## 3. Karar sözleşmesi

`EgressGate(policy).decide(request) → AllowlistDecision`

| Yüzey | Alanlar |
|-------|---------|
| **EgressPolicy** (tenant-scoped) | `tenant_id`, `default_action: "deny"`, `schemes_allowed[]`, `ports_allowed[]`, `block_metadata`, `block_private_networks`, `allow[]` |
| **allow[] kuralı** | `connector_id?`, `scheme`, `host` (exact \| `*.suffix`), `port?`, `path_prefix?` |
| **EgressRequest** | `call_id`, `correlation_id`, `tenant_id`, `connector_id?`, `method?`, `endpoint` (kanonik template), `target{scheme,host,port,path}`, `resolved_ips[]` |
| **AllowlistDecision** | `decision: permit\|deny`, `reason_code`, `matched_rule`, `endpoint`, `fault_class`, `no_log` |

**reason_code:** PERMIT → `ALLOWED`; DENY → `UNLISTED_ENDPOINT` · `SCHEME_BLOCKED` · `PORT_BLOCKED` ·
`PRIVATE_NETWORK_BLOCKED` · `METADATA_BLOCKED` · `DNS_REBINDING_BLOCKED` · `PATH_NOT_ALLOWED` ·
`MALFORMED_TARGET` · `POLICY_TENANT_MISMATCH`.

**DENY → fault:** `ENDPOINT_NOT_ALLOWED` — gate-seviyesi **TERMINAL** fault. 7.1.4 bunu **retry etmez**
(engellenmiş endpoint'i tekrar denemek anlamsız + saldırı sinyali); 7.1.5 müşteriye teknik-detaysız
`NOT_PERMITTED`/`CANNOT_COMPLETE`'e çevirir.

## 4. Karar sırası ve HARD invariant'lar (A1–A12)

Gate kontrolleri **güvenlik-önce** sırada uygular; **block-overrides-allow** (A9, most-restrictive-wins):

1. **A12 fail-closed** — kontrol karakteri / eksik host·scheme·port → `MALFORMED_TARGET`.
2. **tenant scope** — `request.tenant_id ≠ policy.tenant_id` → `POLICY_TENANT_MISMATCH`.
3. **host kanonikleştirme** — IP literal doğrudan; decimal/octal/hex obfuscation (`2130706433`, `0x..`) → `MALFORMED_TARGET` (obfuscation permit'e taşınmaz); DNS adı → `resolved_ips` zorunlu (yoksa fail-closed).
4. **A2 metadata** — host adı ∨ herhangi resolved_ip cloud metadata (169.254.169.254, fd00:ec2::254, metadata.google.internal, …) → `METADATA_BLOCKED` (**allow EZİLİR**).
5. **A3/A4 özel ağ + rebinding** — host IP-literal ∨ herhangi resolved_ip global-olmayan (RFC1918/loopback/link-local/ULA/CGN/reserved) → IP-literal'de `PRIVATE_NETWORK_BLOCKED`, DNS-adında `DNS_REBINDING_BLOCKED`. **Tüm** resolved_ips kontrol edilir; allowlist'li host bir iç IP'ye çözülürse host-allow **bypass etmez**.
6. **A5 scheme** — `scheme ∉ schemes_allowed` → `SCHEME_BLOCKED` (file/gopher/ftp + https-only iken http).
7. **A6 port** — `port ∉ ports_allowed` → `PORT_BLOCKED`.
8. **A8 path normalize** — `..` segmenti → `MALFORMED_TARGET`.
9. **A1/A7/A8 allow eşleme** — host/scheme/port (+ opsiyonel `connector_id`) eşleşen kural yoksa → `UNLISTED_ENDPOINT` (**default-deny**); host eşleşip path_prefix tutmazsa → `PATH_NOT_ALLOWED`; tam eşleşme → **PERMIT**.

| ID | İnvariant |
|----|-----------|
| **A1** | Default-deny — `default_action` zorunlu `deny`; eşleşme yoksa DENY. **SR-TOOL-012 kabul ölçütü.** |
| **A2** | Metadata blok (allow ezilir) |
| **A3** | Özel-ağ blok (global-olmayan IP) |
| **A4** | DNS rebinding savunması (tüm resolved_ips) |
| **A5** | Scheme allowlist |
| **A6** | Port allowlist |
| **A7** | Host etiket-sınırı eşleme (substring yok; `*.x` ≠ `x` ≠ `evilx`) |
| **A8** | path_prefix segment-sınırı + traversal reddi |
| **A9** | Block-overrides-allow (most-restrictive-wins) |
| **A10** | Determinizm (saf karar) |
| **A11** | Audit no-log (düşük kardinalite: yalnız endpoint template + karar + reason) |
| **A12** | Fail-closed (bozuk/çözülemeyen → DENY, asla permit) |

### Host eşleme semantiği (A7)
`*.partner.example.com` → `api.partner.example.com` **eşleşir**; `partner.example.com` (apex) ve
`a.evil-example.com` **eşleşmez**. `crm.example.com.attacker.net` exact `crm.example.com` ile eşleşmez
(substring yok). Eşleme `/` etiket sınırındadır.

### SSRF sınıflandırma (A2/A3)
IP, **`is_global` tabanlı** sınıflandırılır: belgeleme aralıkları (RFC5737/RFC3849) hariç global-olmayan
**her** IP `private` sayılır (CGN 100.64/10 dahil). Cloud metadata özel-kasa (`metadata`). IPv4-mapped
IPv6 (`::ffff:127.0.0.1`) altta yatan v4'e indirgenir. Belgeleme aralıkları fixture'larda gerçek public IP
yerine kullanılır (sentetik — FR-TST-008).

## 5. Audit (no-log — A11)

Karar başına yapısal kayıt 7.1.6'ya (correlation_id audit; FR-TOOL-010) köprüdür:
`correlation_id` + kanonik `endpoint` (interpolesiz template) + `decision` + `reason_code` +
`matched_rule` + `no_log`. Ham URL query/path-param değeri/body/secret/PII/resolved_ip **yer almaz**
(0.4.7 label politikasıyla hizalı düşük kardinalite). IP-literal host endpoint'te zaten görünür (düşük
kardinalite kimlik — leak değil).

## 6. Doğrulama

```bash
python3 endpoint_allowlist_probe.py validate          # statik + sır/PII tarama + sample kapısı
python3 endpoint_allowlist_probe.py selftest          # gömülü davranış (A1–A12)
python3 endpoint_allowlist_probe.py decide <sample>   # tek sample kararı + kapı
python3 tests/endpoint_allowlist_behavior_test.py     # kara-kutu davranış
./run_live_test.sh                                    # hepsi + (varsa) canlı not
```

**Degraded anti-örnek (`samples/degraded.json`):** SSRF blok kapatılır (`enforce_ssrf=false` +
toggle'lar `false`) → gate iç metadata IP'yi PERMIT eder; `_check_gates`'in **SSRF-floor**'u (policy
toggle'dan bağımsız A2/A3/A9 invariant) bunu yakalar → 🔴. SSRF blokunun salt policy-opsiyonel değil,
**gerçek bir güvenlik kapısı** olduğunu kanıtlar. **`samples/invalid-policy.json`:** `default_action:
"allow"` → policy kurulumda reddedilir (default-deny yapı-zamanı garantisi).

## 7. İzlenebilirlik

| Kaynak | Eşleme |
|--------|--------|
| FR | FR-TOOL-012, FR-TST-008 |
| NFR | NFR 10.6 (egress/ağ güvenliği), NFR 10.7 (residency) |
| SR / TC | SR-TOOL-012 / TC-TOOL-012 (RTM satır 290 → 7.2.3; SRS/RTM değişikliği gerekmedi) |
| SAD | §11.2 (allowlist), §11.1 (Tool Yürütme Hattı), §14 (güvenlik) |
| ADR | ADR-014 (egress kontrol — karar çekirdeği), ADR-001/002 (SPI/vendor-neutral) |
| Threat | TM-E-06 (SSRF), TM-I-04 (exfil); SEC-06, SEC-20 |
| Tüketir | 7.2.1/7.2.2 (kanonik endpoint+target), tenant egress policy, DNS çözümleme |
| Tüketilir | 7.1.4 (PERMIT→sarar / DENY→retry yok), 7.1.5 (müşteri metni), 7.1.6 (audit), 17.1.4 (ağ proxy) |

## 8. Kapsam dışı (bilinçli)

Kanonik endpoint/target üretimi → **7.2.1/7.2.2**; timeout/retry/breaker → **7.1.4**; ağ-katmanı egress
proxy / private endpoint / WAF / inbound IP allowlist → **17.1.4** (defense-in-depth, aynı mantık);
input/output schema → 7.1.1; tool authz/scope → 7.1.2 (dik boyut); idempotency → 7.1.3; müşteri hata metni
→ 7.1.5; audit zenginleştirme → 7.1.6; allowlist L1 panel CRUD/maker-checker yönetimi → ileri panel WBS;
gerçek DNS çözümleme → canlı resolver (referans: `resolved_ips`). Sır/credential ve gerçek PII repoya
yazılmaz (host'lar `example.com`; IP'ler RFC5737/RFC1918/RFC3927 illüstratif).
