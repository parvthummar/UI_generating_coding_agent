import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const sandboxRoot = path.dirname(fileURLToPath(import.meta.url));
const stagingRoot = path.join(sandboxRoot, '.staging');

// Builds sandbox/.staging, not the committed sandbox/src tree the preview serves.
export default defineConfig({
  root: stagingRoot,
  envDir: sandboxRoot,
  cacheDir: path.join(sandboxRoot, 'node_modules', '.vite-staging'),
  publicDir: false,
  plugins: [react(), tailwindcss()],
  build: {
    outDir: path.join(stagingRoot, 'dist'),
    emptyOutDir: true,
    sourcemap: true,
    minify: false,
    cssMinify: false,
  },
  server: {
    fs: {
      strict: true,
      allow: [sandboxRoot],
    },
  },
});
