import * as Dialog from '@radix-ui/react-dialog';
import * as Progress from '@radix-ui/react-progress';
import * as Switch from '@radix-ui/react-switch';
import * as Tooltip from '@radix-ui/react-tooltip';
import { motion } from 'framer-motion';
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react';
import { cn } from '../lib/utils';

export function LogoLockup({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <img src="/treeo-logo.jpg" alt="" className={cn('rounded-md object-cover ring-1 ring-[var(--line)]', compact ? 'h-8 w-8' : 'h-10 w-10')} />
      <div className="min-w-0">
        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">Treeo VC</div>
        <div className={cn('truncate font-display font-semibold tracking-[-0.01em]', compact ? 'text-base' : 'text-xl')}>Scout</div>
      </div>
    </div>
  );
}

export function Button({ className, variant = 'primary', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger' }) {
  const variants = {
    primary: 'bg-[var(--text)] text-[var(--bg)] hover:opacity-90',
    secondary: 'bg-[var(--accent)] text-white hover:bg-[var(--accent-strong)]',
    ghost: 'border border-[var(--line)] bg-transparent text-[var(--text)] hover:border-[var(--line-strong)] hover:bg-[color-mix(in_srgb,var(--surface)_70%,transparent)]',
    danger: 'bg-red-600 text-white hover:bg-red-700',
  };
  return (
    <button
      // Emil Kowalski rule: buttons must feel responsive to press. Tactile
      // scale and custom ease-out curve under 200ms keep the UI in lockstep
      // with the click.
      style={{ transition: 'transform 160ms var(--ease-emil), opacity 160ms var(--ease-emil), background-color 160ms var(--ease-emil), border-color 160ms var(--ease-emil)' }}
      className={cn(
        'focus-ring inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50 active:scale-[0.98]',
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

export function IconButton({ className, label, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }) {
  return (
    <Tooltip.Provider delayDuration={250}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            aria-label={label}
            style={{ transition: 'transform 160ms var(--ease-emil), border-color 160ms var(--ease-emil), color 160ms var(--ease-emil)' }}
            className={cn('focus-ring inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--line)] text-[var(--muted)] hover:border-[var(--line-strong)] hover:text-[var(--text)] active:scale-[0.96]', className)}
            {...props}
          >
            {children}
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content sideOffset={8} className="z-50 rounded-md bg-charcoal px-2.5 py-1.5 text-xs text-white shadow-panel">
            {label}
            <Tooltip.Arrow className="fill-charcoal" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('surface rounded-md p-4', className)} {...props} />;
}

export function Badge({ className, tone = 'neutral', ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: 'neutral' | 'cyan' | 'teal' | 'warn' | 'success' }) {
  const tones = {
    neutral: 'border-[var(--line)] text-[var(--muted)]',
    cyan: 'border-[var(--accent-muted)] bg-[var(--accent-soft)] text-[var(--accent-strong)] dark:text-[var(--accent-light)]',
    teal: 'border-[var(--accent-muted)] bg-[var(--accent-soft)] text-[var(--accent)]',
    warn: 'border-amber-400/45 bg-amber-400/10 text-amber-700 dark:text-amber-300',
    success: 'border-emerald-400/45 bg-emerald-400/10 text-emerald-700 dark:text-emerald-300',
  };
  return <span className={cn('inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold', tones[tone], className)} {...props} />;
}

export function Metric({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return (
    <div className="rounded-md border border-[var(--line)] bg-[color-mix(in_srgb,var(--surface-strong)_84%,transparent)] p-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">{label}</div>
      <div className="data-font mt-1 text-2xl font-semibold tracking-[-0.02em] text-[var(--text)]">{value}</div>
      {detail ? <div className="mt-1 text-xs text-[var(--muted)]">{detail}</div> : null}
    </div>
  );
}

/**
 * ScoreRing renders the 0..100 deal score as a radial gauge. The `confidence`
 * (0..1) shows as a muted outer band so the analyst sees uncertainty at a
 * glance. Has an aria-label so the SVG is announceable.
 */
export function ScoreRing({ score, confidence, size = 86 }: { score: number; confidence?: number; size?: number }) {
  const radius = 34;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.max(0, Math.min(100, score)) / 100) * circumference;
  const confidenceLabel = typeof confidence === 'number' ? ` with ${Math.round(confidence * 100)} percent confidence` : '';
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }} role="img" aria-label={`Score ${score} out of 100${confidenceLabel}`}>
      <svg viewBox="0 0 80 80" className="absolute inset-0">
        <circle cx="40" cy="40" r={radius} fill="none" stroke="var(--line)" strokeWidth="8" />
        {typeof confidence === 'number' ? (
          <circle
            cx="40"
            cy="40"
            r={radius + 5}
            fill="none"
            stroke="var(--accent-muted)"
            strokeWidth="2"
            strokeDasharray={`${(confidence * 2 * Math.PI * (radius + 5)).toFixed(2)} ${(2 * Math.PI * (radius + 5)).toFixed(2)}`}
            transform="rotate(-90 40 40)"
            opacity={0.6}
          />
        ) : null}
        <motion.circle
          cx="40"
          cy="40"
          r={radius}
          fill="none"
          stroke="url(#treeoScore)"
          strokeLinecap="round"
          strokeWidth="8"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 0.65, ease: 'easeOut' }}
          transform="rotate(-90 40 40)"
        />
        <defs>
          <linearGradient id="treeoScore" x1="0" x2="1" y1="0" y2="1">
            <stop stopColor="var(--accent-light)" />
            <stop offset="1" stopColor="var(--accent)" />
          </linearGradient>
        </defs>
      </svg>
      <span className="data-font text-xl font-semibold">{score}</span>
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean; helperText?: string }) {
  const { invalid, helperText, className, ...rest } = props;
  return (
    <span className="flex flex-col gap-1">
      <input
        {...rest}
        aria-invalid={invalid || undefined}
        className={cn(
          'focus-ring h-10 rounded-md border bg-[var(--surface-strong)] px-3 text-sm text-[var(--text)] placeholder:text-[var(--muted)]',
          invalid ? 'border-red-500' : 'border-[var(--line)]',
          className,
        )}
      />
      {helperText ? (
        <span className={cn('text-xs', invalid ? 'text-red-500' : 'text-[var(--muted)]')}>{helperText}</span>
      ) : null}
    </span>
  );
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean; helperText?: string }) {
  const { invalid, helperText, className, ...rest } = props;
  return (
    <span className="flex flex-col gap-1">
      <textarea
        {...rest}
        aria-invalid={invalid || undefined}
        className={cn(
          'focus-ring min-h-24 rounded-md border bg-[var(--surface-strong)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--muted)]',
          invalid ? 'border-red-500' : 'border-[var(--line)]',
          className,
        )}
      />
      {helperText ? (
        <span className={cn('text-xs', invalid ? 'text-red-500' : 'text-[var(--muted)]')}>{helperText}</span>
      ) : null}
    </span>
  );
}

/** Title-cases a snake/underscore recommendation label exactly once. */
export function recommendationLabel(value: string): string {
  if (!value) return 'Unknown';
  const cleaned = value.replace(/_/g, ' ').toLowerCase();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

export function Recommendation({ value }: { value: string }) {
  const v = String(value);
  const tone = v === 'immediate_outreach' || v === 'take_meeting'
    ? 'success'
    : v === 'partner_review'
      ? 'teal'
      : v === 'monitor'
        ? 'warn'
        : 'neutral';
  return <Badge tone={tone}>{recommendationLabel(v)}</Badge>;
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'animate-pulse rounded-md bg-[var(--surface-strong)]',
        className,
      )}
    />
  );
}

export function Toast({ tone = 'neutral', children, action }: { tone?: 'neutral' | 'error' | 'success'; children: ReactNode; action?: ReactNode }) {
  const tones = {
    neutral: 'border-[var(--line)] bg-[var(--surface)] text-[var(--text)]',
    error: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-200',
    success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200',
  };
  return (
    <div role="status" aria-live="polite" className={cn('flex items-start gap-3 rounded-md border p-3 text-sm', tones[tone])}>
      <div className="flex-1">{children}</div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export const RadixDialog = Dialog;
export const RadixProgress = Progress;
export const RadixSwitch = Switch;
export const RadixTooltip = Tooltip;
