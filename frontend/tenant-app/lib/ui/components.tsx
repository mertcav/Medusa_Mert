// WBS 13.1.3 — RMC komponent kütüphanesi (presentasyonel primitive'ler).
//
// ÇEKİRDEK İLKELER:
//  - PRESENTASYONEL + locale-AGNOSTİK: bu dosya i18n import ETMEZ; tüm kullanıcı-görünür metin PROP olarak
//    gelir (çağrı yeri t() ile yerelleştirir). Bu modülde gömülü TR/EN cümle YOK (probe no-hardcoded kapısı).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): rol→permission kararı YOK; yalnız görsel kapı.
//  - ERİŞİLEBİLİR (WCAG 2.1): etkileşimli öğeler erişilebilir AD ister (children veya aria-label);
//    durum bölgeleri role=status/alert; gizli metin VisuallyHidden ile; renk tek-başına anlam taşımaz
//    (StatusPill metin + ton). Renkler design token (var(--rmc-*)); kontrast oranları token'da kapılı.
//  - RSC-uyumlu: 'use client' YOK; event handler YOK (skeleton). İnteraktivite 13.2+'da client island'larda.
import type { CSSProperties, ReactNode } from "react";

type Tone = "neutral" | "success" | "warning" | "danger" | "info";
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const TONE_FG: Record<Tone, string> = {
  neutral: "var(--rmc-text-muted)",
  success: "var(--rmc-success-fg)",
  warning: "var(--rmc-warning-fg)",
  danger: "var(--rmc-danger-fg)",
  info: "var(--rmc-info-fg)",
};
const TONE_BG: Record<Tone, string> = {
  neutral: "var(--rmc-surface-sunken)",
  success: "var(--rmc-success-bg)",
  warning: "var(--rmc-warning-bg)",
  danger: "var(--rmc-danger-bg)",
  info: "var(--rmc-info-bg)",
};

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="rmc-visually-hidden">{children}</span>;
}

export function SkipLink({ targetId, label }: { targetId: string; label: string }) {
  return (
    <a className="rmc-skip-link" href={`#${targetId}`}>
      {label}
    </a>
  );
}

export function Button({
  children,
  variant = "primary",
  type = "button",
  disabled,
  ariaLabel,
}: {
  children: ReactNode;
  variant?: ButtonVariant;
  type?: "button" | "submit";
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const base: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: "var(--rmc-space-2)",
    padding: "var(--rmc-space-2) var(--rmc-space-4)",
    borderRadius: "var(--rmc-radius-md)",
    fontSize: "var(--rmc-size-sm)",
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.55 : 1,
    border: "1px solid transparent",
  };
  const variants: Record<ButtonVariant, CSSProperties> = {
    primary: { background: "var(--rmc-brand-primary)", color: "var(--rmc-on-brand)" },
    secondary: {
      background: "var(--rmc-surface)",
      color: "var(--rmc-brand-primary)",
      border: "1px solid var(--rmc-border-strong)",
    },
    ghost: { background: "transparent", color: "var(--rmc-brand-primary)" },
    danger: { background: "var(--rmc-danger-fg)", color: "var(--rmc-on-brand)" },
  };
  return (
    <button type={type} disabled={disabled} aria-label={ariaLabel} style={{ ...base, ...variants[variant] }}>
      {children}
    </button>
  );
}

export function StatusPill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px var(--rmc-space-2)",
        borderRadius: "var(--rmc-radius-pill)",
        fontSize: "var(--rmc-size-xs)",
        fontWeight: 600,
        color: TONE_FG[tone],
        background: TONE_BG[tone],
      }}
    >
      {children}
    </span>
  );
}

export function Card({ children, title }: { children: ReactNode; title?: ReactNode }) {
  return (
    <section
      style={{
        background: "var(--rmc-surface)",
        border: "1px solid var(--rmc-border-subtle)",
        borderRadius: "var(--rmc-radius-lg)",
        boxShadow: "var(--rmc-shadow-sm)",
        padding: "var(--rmc-space-5)",
      }}
    >
      {title != null && (
        <h2 style={{ margin: 0, marginBottom: "var(--rmc-space-3)", fontSize: "var(--rmc-size-lg)" }}>
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  description,
  code,
}: {
  title: ReactNode;
  description?: ReactNode;
  code?: string;
}) {
  return (
    <header style={{ marginBottom: "var(--rmc-space-5)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-2)" }}>
        <h1 style={{ margin: 0, fontSize: "var(--rmc-size-2xl)", color: "var(--rmc-text-primary)" }}>{title}</h1>
        {code && <StatusPill tone="info">{code}</StatusPill>}
      </div>
      {description != null && (
        <p style={{ margin: "var(--rmc-space-2) 0 0", color: "var(--rmc-text-muted)" }}>{description}</p>
      )}
    </header>
  );
}

export function Alert({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  // role: danger → alert (assertive), aksi → status (polite). Renk + metin (renk tek-başına değil).
  const role = tone === "danger" ? "alert" : "status";
  return (
    <div
      role={role}
      style={{
        padding: "var(--rmc-space-3) var(--rmc-space-4)",
        borderRadius: "var(--rmc-radius-md)",
        color: TONE_FG[tone],
        background: TONE_BG[tone],
        border: `1px solid ${TONE_FG[tone]}`,
      }}
    >
      {children}
    </div>
  );
}

export function Field({
  id,
  label,
  required,
  requiredLabel,
  children,
}: {
  id: string;
  label: ReactNode;
  required?: boolean;
  requiredLabel?: string; // erişilebilir "zorunlu" metni (locale çağrı yerinde)
  children: ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--rmc-space-1)" }}>
      <label htmlFor={id} style={{ fontSize: "var(--rmc-size-sm)", fontWeight: 500 }}>
        {label}
        {required && (
          <span aria-hidden="true" style={{ color: "var(--rmc-danger-fg)" }}>
            {" *"}
          </span>
        )}
        {required && requiredLabel && <VisuallyHidden>{requiredLabel}</VisuallyHidden>}
      </label>
      {children}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  // Yükleniyor durumu — görünür metin yok; erişilebilir AD zorunlu.
  return (
    <span role="status" aria-live="polite" style={{ color: "var(--rmc-text-muted)" }}>
      <VisuallyHidden>{label}</VisuallyHidden>
      <span aria-hidden="true">⏳</span>
    </span>
  );
}

export function EmptyState({ message }: { message: ReactNode }) {
  return (
    <p style={{ color: "var(--rmc-text-muted)", textAlign: "center", padding: "var(--rmc-space-6)" }}>
      {message}
    </p>
  );
}

export function Table({ caption, children }: { caption: ReactNode; children: ReactNode }) {
  // caption erişilebilirlik için zorunlu (tablo özeti).
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--rmc-size-sm)" }}>
      <caption className="rmc-visually-hidden">{caption}</caption>
      {children}
    </table>
  );
}

export function LangSwitcher({
  current,
  locales,
  hrefFor,
  label,
  localeLabel,
}: {
  current: string;
  locales: readonly string[];
  hrefFor: (locale: string) => string;
  label: string; // a11y: "Dil seçimi"
  localeLabel: (locale: string) => string;
}) {
  return (
    <nav aria-label={label} style={{ display: "flex", gap: "var(--rmc-space-2)" }}>
      {locales.map((loc) => {
        const isCurrent = loc === current;
        return (
          <a
            key={loc}
            href={hrefFor(loc)}
            hrefLang={loc}
            aria-current={isCurrent ? "true" : undefined}
            style={{
              fontSize: "var(--rmc-size-sm)",
              fontWeight: isCurrent ? 600 : 400,
              color: isCurrent ? "var(--rmc-brand-primary)" : "var(--rmc-text-muted)",
              textDecoration: isCurrent ? "underline" : "none",
            }}
          >
            {localeLabel(loc)}
          </a>
        );
      })}
    </nav>
  );
}
