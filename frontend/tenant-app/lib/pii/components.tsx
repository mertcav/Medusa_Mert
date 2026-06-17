// WBS 13.1.4 — PII maskeleme presentasyonel komponentleri. SUNUM-KATMANI; lib/pii/mask.ts saf çekirdeğini
// kullanır. PRESENTASYONEL + locale-AGNOSTİK: kullanıcı-görünür etiket (redaksiyon ipucu) PROP olarak gelir
// (çağrı yeri t() ile yerelleştirir → bu dosyada gömülü TR/EN cümle YOK). İŞ MANTIĞI/AUTHZ YOK (A8): reveal/
// canReveal yalnız PROP; permission kararı 12.2.x backend. WCAG 2.1: maskeli içerik için ekran-okuyucu ipucu
// (.rmc-visually-hidden) + aria-label; ham haneler aria-hidden değil (gösterilen son-4 erişilebilir kalır).
import type { ReactNode } from "react";
import { maskField, scanAndMask, type RevealOpts } from "./mask";

// Tek bir PII alanını (kart/e-posta/telefon/...) maskeli gösterir. Maskeliyse ekran-okuyucuya redaksiyon
// ipucu verilir; gösterilen değer aria-label ile etiketlenir.
export function Masked({
  category,
  value,
  reveal,
  canReveal,
  redactedLabel,
}: {
  category: string;
  value: string;
  reveal?: boolean;
  canReveal?: boolean;
  redactedLabel: string; // a11y: "gizlenmiş PII" (locale çağrı yerinde)
}): ReactNode {
  const opts: RevealOpts = { reveal, canReveal };
  const shown = maskField(category, value, opts);
  const isMasked = shown !== value;
  return (
    <span
      data-pii={category}
      data-masked={isMasked ? "true" : "false"}
      aria-label={isMasked ? redactedLabel : undefined}
    >
      {isMasked && <span className="rmc-visually-hidden">{redactedLabel}</span>}
      <span aria-hidden={isMasked ? "true" : undefined}>{shown}</span>
    </span>
  );
}

// Serbest metni (transkript) maskeleyerek gösterir — gömülü kart/OTP/e-posta/IBAN/telefon/kimlik desenleri
// scanAndMask ile değiştirilir (FR-REC-004/005 panel karşılığı). Varsayılan maskeli; reveal backend-yetkili.
export function MaskedTranscript({
  text,
  reveal,
  canReveal,
}: {
  text: string;
  reveal?: boolean;
  canReveal?: boolean;
}): ReactNode {
  return <span data-pii="transcript">{scanAndMask(text, { reveal, canReveal })}</span>;
}
