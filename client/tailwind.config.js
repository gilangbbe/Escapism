/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        serif: ['"IM Fell English"', 'Georgia', 'serif'],
      },
      colors: {
        parchment: "#f4ead2",
        ink: "#1a1410",
        ember: "#c0492b",
        brass: "#b08d4b",
        sea: "#1f3a4a",
      },
    },
  },
  plugins: [],
};
