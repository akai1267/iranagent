import { defineConfig } from 'vite'

export default defineConfig({
  esbuild: {
    jsxInject: "import React from 'react'",
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
  },
})
