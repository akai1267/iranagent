const isDev = import.meta.env.DEV

export const API_BASE = import.meta.env.VITE_API_BASE || (isDev ? 'http://localhost:8000' : '')
