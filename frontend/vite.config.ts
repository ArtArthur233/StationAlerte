/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Politique de sécurité du site (CSP, V8.3) : le navigateur refuse tout ce qui n'est pas listé ici.
// Seulement sur la version compilée (npm run build puis npm run preview, http://localhost:4173) :
// en développement, Vite injecte des scripts dans la page pour le rechargement à chaud, que cette règle bloquerait.
// Copie identique dans frontend/docker/nginx.conf (site lancé avec Docker) : modifier les deux.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'", // aucun script dans la page ni venu d'ailleurs (d'où public/theme.js en fichier)
  "style-src 'self' 'unsafe-inline'", // Leaflet place la carte avec des styles écrits sur les éléments
  "img-src 'self' data: https://data.geopf.fr", // tuiles du Plan IGN
  'connect-src http://localhost:8000', // l'API
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'", // le site ne peut pas être affiché dans le cadre d'un autre site
].join('; ')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  preview: {
    port: 4173,
    strictPort: true, // autre port = autre origine, refusée par l'API (CORS)
    headers: {
      'Content-Security-Policy': CONTENT_SECURITY_POLICY,
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
    },
  },
  test: {
    environment: 'jsdom', // simule un navigateur pour tester les composants
    setupFiles: './src/setupTests.ts',
  },
})
