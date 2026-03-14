const isDev = import.meta.env.DEV

export const API_BASE = import.meta.env.VITE_API_BASE || (isDev ? 'http://localhost:8000' : '')

export const WS_URL =
  import.meta.env.VITE_WS_URL ||
  (isDev
    ? 'ws://localhost:8000/ws/observatory'
    : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/observatory`)
