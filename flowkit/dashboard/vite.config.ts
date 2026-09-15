import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // NOTE: there is deliberately no '/api/opencode' entry here.
      //
      // There used to be one pointing at https://opencode.ai/zen/v1. Because
      // Vite matches the most specific key first, it shadowed the '/api' rule
      // below, so every OpenCode call went straight from the browser to
      // opencode.ai -- carrying a hardcoded API key in the JS bundle and
      // bypassing the agent. Removing it lets /api/opencode/* fall through to
      // the agent, which owns the key and resolves each model's protocol.
      '/api': 'http://127.0.0.1:8100',
      '/ws': { target: 'ws://127.0.0.1:8100', ws: true },
      '/health': 'http://127.0.0.1:8100',
    }
  },
  build: { outDir: 'dist' }
})
