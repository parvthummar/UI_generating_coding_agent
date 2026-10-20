import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const sandboxRoot = path.dirname(fileURLToPath(import.meta.url));

// The preview may only talk to itself. Remote http(s), websockets, and fonts stay blocked.
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' ws://localhost:5174 http://localhost:5174",
  "frame-ancestors http://localhost:5173",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

export default defineConfig({
  envDir: sandboxRoot,
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    fs: {
      strict: true,
      allow: [sandboxRoot],
    },
    headers: {
      'Content-Security-Policy': CONTENT_SECURITY_POLICY,
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
      'Referrer-Policy': 'no-referrer',
      'X-Content-Type-Options': 'nosniff',
    },
    hmr: {
      overlay: false,
    },
    watch: {
      ignored: ['**/.staging/**', '**/.snapshots/**'],
    },
  },
});
