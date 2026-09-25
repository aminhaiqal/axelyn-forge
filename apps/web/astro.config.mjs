import clerk from "@clerk/astro";
import node from "@astrojs/node";
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  adapter: node({ mode: "standalone" }),
  integrations: [clerk()],
  output: "server",
  vite: {
    plugins: [tailwindcss()],
    server: {
      proxy: {
        "/api": "http://127.0.0.1:8000",
      },
    },
  },
});
