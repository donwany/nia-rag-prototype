/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Ghana flag palette, used sparingly for accents.
        nia: {
          green: '#006b3f',
          gold: '#fcd116',
          red: '#ce1126',
          ink: '#0f1b17',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
