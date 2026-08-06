/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      // Semantic tokens map to CSS variables (see style.css) so we can theme
      // the kiosk (dark/immersive) and admin (lighter) from one system.
      colors: {
        brand: {
          50: '#FFF7ED', 100: '#FFEDD5', 200: '#FED7AA', 300: '#FDBA74',
          400: '#FB923C', 500: '#F97316', 600: '#EA580C', 700: '#C2410C',
          800: '#9A3412', 900: '#7C2D12',
        },
        electric: {
          300: '#7DD3FC', 400: '#38BDF8', 500: '#0EA5E9', 600: '#2563EB', 700: '#1D4ED8',
        },
        ink: {
          950: '#070B16', 900: '#0B1020', 850: '#0F1629', 800: '#141C30', 700: '#1E283F',
        },
      },
      fontFamily: {
        display: ['Fredoka', 'system-ui', 'sans-serif'],
        sans: ['Nunito', 'system-ui', 'sans-serif'],
      },
      borderRadius: { xl2: '1.25rem', '3xl': '1.75rem' },
      boxShadow: {
        glass: '0 8px 32px rgba(2, 6, 23, 0.37)',
        glow: '0 0 40px rgba(249, 115, 22, 0.35)',
        'glow-blue': '0 0 40px rgba(56, 189, 248, 0.35)',
      },
      backdropBlur: { xs: '2px' },
      keyframes: {
        float: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-10px)' } },
        blink: { '0%,90%,100%': { transform: 'scaleY(1)' }, '95%': { transform: 'scaleY(0.1)' } },
        'pulse-ring': {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '100%': { transform: 'scale(1.6)', opacity: '0' },
        },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        'bob-soft': { '0%,100%': { transform: 'translateY(0) rotate(-1deg)' }, '50%': { transform: 'translateY(-6px) rotate(1deg)' } },
      },
      animation: {
        float: 'float 5s ease-in-out infinite',
        blink: 'blink 4s ease-in-out infinite',
        'pulse-ring': 'pulse-ring 1.8s ease-out infinite',
        'bob-soft': 'bob-soft 6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
