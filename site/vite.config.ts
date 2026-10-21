import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Project site: https://chrislernunes.github.io/chronos/
export default defineConfig({
  base: "/chronos/",
  plugins: [react(), tailwindcss()],
});
