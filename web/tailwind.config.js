/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Night: the street outside the porch.
        porch: {
          950: '#070b15',
          900: '#0b1020',
          850: '#0f1528',
          800: '#141a33',
          750: '#19203d',
          700: '#1f2747',
          600: '#2b355c',
          500: '#3d4874',
        },
        // The light itself.
        lamp: {
          DEFAULT: '#f59e0b',
          glow: '#ffb347',
          wash: '#ffd9a0',
          deep: '#a86a08',
        },
        cream: {
          DEFAULT: '#f4efe6',
          dim: '#cbc4b8',
          faint: '#ada79e',
        },
        // Decision-kind hues.
        sage: '#8fb996',
        ember: '#ff6b6b',
        lilac: '#b39ddb',
        dusk: '#7fa9d8',
        rust: '#f0894a',
        slate: '#8d95ab',
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'Times New Roman', 'serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: { '2xl': '1.125rem', '3xl': '1.5rem' },
      boxShadow: {
        lift: '0 1px 0 0 rgba(255,255,255,0.06) inset, 0 18px 40px -24px rgba(0,0,0,0.9)',
        halo: '0 0 0 1px rgba(245,158,11,0.28), 0 0 46px -8px rgba(255,179,71,0.42)',
        pool: '0 -30px 90px -20px rgba(255,179,71,0.16)',
      },
      keyframes: {
        'lantern-glow': {
          '0%, 100%': { opacity: '0.72', transform: 'scale(1)' },
          '50%': { opacity: '1', transform: 'scale(1.06)' },
        },
        flicker: {
          '0%, 100%': { opacity: '1' },
          '41%': { opacity: '0.86' },
          '43%': { opacity: '1' },
          '77%': { opacity: '0.92' },
        },
        'slide-in': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(14px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-dot': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(143,185,150,0.55)' },
          '70%': { boxShadow: '0 0 0 7px rgba(143,185,150,0)' },
        },
        drift: {
          '0%, 100%': { transform: 'translate3d(0,0,0)' },
          '50%': { transform: 'translate3d(-1.5%, 1.5%, 0)' },
        },
      },
      animation: {
        'lantern-glow': 'lantern-glow 3.6s ease-in-out infinite',
        flicker: 'flicker 5s linear infinite',
        'slide-in': 'slide-in 320ms cubic-bezier(0.22,1,0.36,1) both',
        'fade-up': 'fade-up 520ms cubic-bezier(0.22,1,0.36,1) both',
        'pulse-dot': 'pulse-dot 2.4s ease-out infinite',
        drift: 'drift 26s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
