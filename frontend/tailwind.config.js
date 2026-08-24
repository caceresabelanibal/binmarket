/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#2563eb",
        testnet: "#d97706",
        live: "#dc2626",
      },
    },
  },
  plugins: [],
};
