#!/usr/bin/env node
// Development server: esbuild watch + HTTP server

import esbuild from 'esbuild';
import esbuildSvelte from 'esbuild-svelte';
import tailwindcss from 'esbuild-plugin-tailwindcss';
import { createServer } from 'http';
import { readFile } from 'fs/promises';
import { fileURLToPath } from 'url';
import { dirname, resolve, join, extname } from 'path';
import { existsSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PORT = 5173;
const HOST = 'localhost';

const CONTENT_TYPES = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ico': 'image/x-icon',
};

// Start esbuild in watch mode
const ctx = await esbuild.context({
  entryPoints: [resolve(__dirname, 'src/main.ts')],
  bundle: true,
  outdir: resolve(__dirname, 'dist'),
  format: 'esm',
  splitting: true,
  sourcemap: true,
  target: ['es2022'],
  plugins: [
    esbuildSvelte({
      compilerOptions: {
        css: 'injected',
      },
    }),
    tailwindcss(),
  ],
  alias: {
    '$lib': resolve(__dirname, 'src/lib'),
    '$components': resolve(__dirname, 'src/components'),
  },
  logLevel: 'info',
});

await ctx.watch();
console.log('esbuild watching for changes...');

// Start HTTP server
const server = createServer(async (req, res) => {
  let urlPath = req.url.split('?')[0];

  // Serve index.html for root and all routes (SPA behavior)
  if (urlPath === '/' || !urlPath.includes('.')) {
    urlPath = '/index.html';
  }

  // Try to serve from dist first, then from root
  let filePath = join(__dirname, 'dist', urlPath);
  if (!existsSync(filePath)) {
    filePath = join(__dirname, urlPath);
  }

  try {
    const content = await readFile(filePath);
    const ext = extname(filePath);
    res.setHeader('Content-Type', CONTENT_TYPES[ext] || 'application/octet-stream');
    res.writeHead(200);
    res.end(content);
  } catch (err) {
    if (err.code === 'ENOENT') {
      res.writeHead(404);
      res.end('Not found: ' + urlPath);
    } else {
      res.writeHead(500);
      res.end('Server error: ' + err.message);
    }
  }
});

server.listen(PORT, HOST, () => {
  console.log(`\nDev server running at http://${HOST}:${PORT}/\n`);
});

// Handle shutdown
process.on('SIGINT', async () => {
  console.log('\nShutting down...');
  await ctx.dispose();
  server.close();
  process.exit(0);
});
