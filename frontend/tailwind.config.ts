import type { Config } from 'tailwindcss';
import animate from 'tailwindcss-animate';

// Tesla-minimal (DESIGN.md): pure-white UI panels on a dark video canvas, single
// accent #3E6AE1, NO shadows (elevation via border/spacing), 4px radius, 0.33s motion.
// Colors resolve to CSS variables defined in src/styles/globals.css.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--canvas)',
        border: 'var(--border)',
        'border-strong': 'var(--axp-border-strong)',
        input: 'var(--input)',
        ring: 'var(--ring)',
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        placeholder: 'var(--axp-placeholder)',
        primary: { DEFAULT: 'var(--primary)', foreground: 'var(--primary-foreground)' },
        secondary: { DEFAULT: 'var(--secondary)', foreground: 'var(--secondary-foreground)' },
        muted: { DEFAULT: 'var(--muted)', foreground: 'var(--muted-foreground)' },
        accent: { DEFAULT: 'var(--accent)', foreground: 'var(--accent-foreground)' },
        destructive: { DEFAULT: 'var(--destructive)', foreground: 'var(--destructive-foreground)' },
        card: { DEFAULT: 'var(--card)', foreground: 'var(--card-foreground)' },
        popover: { DEFAULT: 'var(--popover)', foreground: 'var(--popover-foreground)' },
      },
      borderRadius: {
        lg: '12px',
        md: '4px',
        sm: '2px',
        DEFAULT: '4px',
      },
      transitionTimingFunction: {
        axp: 'cubic-bezier(0.5, 0, 0, 0.75)',
      },
      transitionDuration: {
        axp: '330ms',
      },
      fontFamily: {
        sans: ['Pretendard', '-apple-system', 'BlinkMacSystemFont', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [animate],
} satisfies Config;
