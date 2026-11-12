"use client";

import {
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import { ChevronDown, X } from "lucide-react";
import { useEffect, useRef } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  className = "",
  children,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      className={`button button-${variant} button-${size} ${className}`.trim()}
      type={type}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`card ${className}`.trim()} {...props}>{children}</section>;
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`text-input ${props.className ?? ""}`} {...props} />;
}

export function SelectInput({
  className = "",
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={`select-wrap ${className}`.trim()}>
      <select className="select-input" {...props} />
      <ChevronDown size={14} aria-hidden="true" />
    </span>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "violet" | "green" | "amber" | "cyan" | "pink";
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function IconButton({
  label,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
}) {
  return (
    <button
      className={`icon-button ${className}`.trim()}
      type="button"
      aria-label={label}
      title={label}
      {...props}
    >
      {children}
    </button>
  );
}

export function Dialog({
  title,
  description,
  onClose,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const dialog = dialogRef.current;
    const focusable = () => dialog?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const autoFocusTarget = dialog?.querySelector<HTMLElement>("[autofocus]");
    (autoFocusTarget ?? focusable()?.[0])?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items?.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, []);

  return (
    <div
      className="dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        aria-describedby={description ? "dialog-description" : undefined}
        aria-labelledby="dialog-title"
        aria-modal="true"
        className={`dialog ${className}`.trim()}
        ref={dialogRef}
        role="dialog"
      >
        <header className="dialog-header">
          <div>
            <h2 id="dialog-title">{title}</h2>
            {description ? <p id="dialog-description">{description}</p> : null}
          </div>
          <IconButton label="Close dialog" onClick={onClose}>
            <X size={17} />
          </IconButton>
        </header>
        {children}
      </section>
    </div>
  );
}
