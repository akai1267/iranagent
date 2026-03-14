import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './index.css'

// Browser compatibility shims for older Safari/Chromium builds.
if (!Object.hasOwn) {
  Object.hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(Object(value), key)
}

if (typeof window !== 'undefined' && window.crypto && !window.crypto.randomUUID) {
  window.crypto.randomUUID = () => {
    const bytes = new Uint8Array(16)
    window.crypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0'))
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
