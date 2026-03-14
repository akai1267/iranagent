import typography from '@tailwindcss/typography'

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      borderRadius: {
        sm: '2px',
        md: '4px',
        DEFAULT: '2px',
      },
    },
  },
  plugins: [typography],
}
