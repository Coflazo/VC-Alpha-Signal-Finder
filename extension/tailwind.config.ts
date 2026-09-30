import type { Config } from 'tailwindcss';

/**
 * The single source of truth for color is the CSS-var palette declared in
 * `src/styles/globals.css` (light/dark via `[data-theme="dark"]`). Tailwind
 * only re-exports a small set of structural colors used by primitives that
 * cannot read CSS vars directly (Radix Tooltip portal etc.).
 *
 * Type and spacing scales follow a 4-step ladder so the UI cannot drift into
 * ad-hoc utility soup.
 */
export default {
  content: ['./src/**/*.{ts,tsx,html}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        charcoal: '#111827',
      },
      fontFamily: {
        sans: ['Geist', 'Satoshi', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Geist', 'Satoshi', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['SF Mono', 'ui-monospace', 'Menlo', 'monospace'],
      },
      fontSize: {
        // 4-step type scale: micro, body, lede, display
        micro: ['12px', { lineHeight: '16px' }],
        body: ['14px', { lineHeight: '20px' }],
        lede: ['16px', { lineHeight: '24px' }],
        display: ['22px', { lineHeight: '28px' }],
      },
      spacing: {
        // 4-step spacing scale on top of Tailwind defaults
        gutter: '12px',
        section: '24px',
        deck: '40px',
        hero: '64px',
      },
      borderRadius: {
        DEFAULT: '8px',
        deck: '12px',
      },
      boxShadow: {
        panel: '0 12px 32px rgba(5, 25, 35, 0.12)',
        deck: '0 24px 60px rgba(5, 25, 35, 0.16)',
      },
    },
  },
  plugins: [],
} satisfies Config;
