/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#f0f4ff",
          100: "#dbe4ff",
          500: "#4361ee",
          600: "#3451d1",
          700: "#2840b8",
        },
      },
    },
  },
  plugins: [],
};
