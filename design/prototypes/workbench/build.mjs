import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const css = fs.readFileSync(path.join(here, '_style.css'), 'utf8');
const body = fs.readFileSync(path.join(here, '_body.html'), 'utf8');
const js = fs.readFileSync(path.join(here, '_app.js'), 'utf8');

const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0f1719">
  <meta name="description" content="smolcode workbench — a single-run glass cockpit for local, Docker-sandboxed coding agents.">
  <title>smolcode · workbench</title>
  <link rel="stylesheet" href="../fonts/fonts.css">
  <style>
${css}
  </style>
</head>
<body>
${body.replace('/* __APP_JS__ */', () => js)}
</body>
</html>
`;

fs.writeFileSync(path.join(here, 'index.html'), html);
console.log(`built index.html: ${html.length.toLocaleString()} bytes`);
