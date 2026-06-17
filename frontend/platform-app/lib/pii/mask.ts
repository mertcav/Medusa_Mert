// WBS 13.1.4 — SUNUM-KATMANI (view-time) PII maskeleme çekirdeği. Saf/deterministik; React/Next API'sinden
// BAĞIMSIZ → birim-test + Python aynası (pii_masking_probe.py: mask_field + scan_and_mask). BRD §17.7:
// 'PII redaction ve kart/OTP gizleme kuralları (FR-REC-004/005) panel görüntülemelerinde de uygulanır.'
//
// ÇEKİRDEK İLKELER:
//  - DEFENSE-IN-DEPTH: birincil redaction backend Analytics Plane'de async (SAD §19.2); bu katman veriyi
//    GÖRÜNTÜLERKEN ikinci kez maskeler → yetkisiz/varsayılan görünümde ham PII ekrana ASLA düşmez.
//  - PROHIBITED (kart/CVV/OTP/parola — FR-REC-005): panelde TAM değer ASLA; reveal flag'i YOK SAYILIR
//    (reveal-immune). Kart için PCI ödünü yalnız son 4 hane.
//  - RESTRICTED (e-posta/telefon/IBAN/ulusal kimlik — FR-REC-004): varsayılan maskeli; yalnız
//    (reveal ∧ canReveal) ham gösterilir.
//  - AUTHZ KARARI YOK (A8 / SAD §14.4.1): bu çekirdek permission'a KARAR VERMEZ — canReveal yalnız BACKEND'ten
//    gelen bir flag'tir, honor edilir. Rol→permission kararı 12.2.x backend; reveal erişimi audit'lenir
//    (FR-REC-009 — backend). Vendor-neutral (ADR-002): maskeleme kütüphanesi bağlanmaz; saf string.
//
// policy.json TEK kaynak doğruluğun (config/pii-policy.json) BİREBİR vendored kopyasıdır; probe canonical-hash
// ile drift'i FAIL eder. Sır/PII DEĞERİ YOK.
import policy from "./policy.json";

export type PiiClass = "prohibited" | "restricted";
export interface RevealOpts {
  reveal?: boolean;
  canReveal?: boolean;
}

interface Scan {
  regex: string;
  flags?: string;
  target?: string;
}
interface Category {
  id: string;
  class: PiiClass;
  strategy: string;
  keep: number;
  scan?: Scan;
}

const MASK: string = policy.mask_char;
const REDACT: string = policy.redact_token;
const CATEGORIES = policy.categories as Category[];
const BY_ID = new Map<string, Category>(CATEGORIES.map((c) => [c.id, c]));
const SCAN_ORDER = policy.scan_order as string[];

// Python str.isalnum() ile aynı küme (unicode harf/sayı); '•' (U+2022) alfasayısal DEĞİL.
function isAlnum(ch: string): boolean {
  return /[\p{L}\p{N}]/u.test(ch);
}

// Son n alfasayısal hariç hepsini MASK ile değiştirir; ayraçlar korunur. Değer n'den KISAYSA tümü
// maskelenir (leak-safe); tam n ise korunur → idempotent (zaten-maskeli değer son-n'i silmez).
function keepLastAlnum(raw: string, n: number): string {
  const chars = Array.from(raw);
  const alnumTotal = chars.filter(isAlnum).length;
  const keepN = alnumTotal >= n ? n : 0;
  let seen = 0;
  let out = "";
  for (const c of chars) {
    if (isAlnum(c)) {
      seen += 1;
      out += keepN > 0 && seen > alnumTotal - keepN ? c : MASK;
    } else {
      out += c;
    }
  }
  return out;
}

function maskEmail(raw: string): string {
  const at = raw.indexOf("@");
  if (at <= 0) return REDACT;
  return raw[0] + "•••" + raw.slice(at);
}

function applyStrategy(strategy: string, raw: string, keep: number): string {
  if (strategy === "redact_full") return REDACT;
  if (strategy === "keep_last") return keepLastAlnum(raw, keep);
  if (strategy === "mask_email") return maskEmail(raw);
  return REDACT; // bilinmeyen strateji → fail-closed tam redaksiyon
}

export function classOf(category: string): PiiClass {
  const cat = BY_ID.get(category);
  return cat ? cat.class : "restricted"; // bilinmeyen kategori → restricted (fail-closed maskele)
}

// Tek bir PII alanını panel görüntülemesi için maskeler.
// PROHIBITED → daima maskeli (reveal YOK SAYILIR). RESTRICTED → yalnız (reveal ∧ canReveal) ham.
export function maskField(category: string, raw: string, opts: RevealOpts = {}): string {
  const cat = BY_ID.get(category);
  const cls: PiiClass = cat ? cat.class : "restricted";
  const strategy = cat ? cat.strategy : "redact_full";
  const keep = cat ? cat.keep : 0;
  if (cls === "restricted" && opts.reveal && opts.canReveal) {
    return raw; // backend-yetkili reveal — frontend KARAR VERMEZ, yalnız honor eder
  }
  return applyStrategy(strategy, raw, keep);
}

// Serbest metni (transkript) tarar ve eşleşen her PII'yi maskeler. scan_order sırasıyla; maskelenen
// haneler '•' olduğundan sonraki desenler yeniden eşleşmez → idempotent.
export function scanAndMask(text: string, opts: RevealOpts = {}): string {
  let out = text;
  for (const cid of SCAN_ORDER) {
    const cat = BY_ID.get(cid);
    const scan = cat ? cat.scan : undefined;
    if (!scan) continue;
    const flags = "g" + (scan.flags && scan.flags.indexOf("i") >= 0 ? "i" : "");
    const rx = new RegExp(scan.regex, flags);
    const target = scan.target || "match";
    out = out.replace(rx, (m: string, g1?: string) => {
      if (target === "match") return maskField(cid, m, opts);
      const val = g1 as string;
      return m.replace(val, maskField(cid, val, opts));
    });
  }
  return out;
}
