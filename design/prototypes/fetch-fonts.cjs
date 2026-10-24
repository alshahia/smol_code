
const fs = require('fs'); const path = require('path');
const https = require('https');
const outDir = process.argv[2];
const families = {
  'Archivo': 'wght@400;500;600;700',
  'Courier Prime': 'wght@400;700',
  'Public Sans': 'wght@400;500;600;700;800;900',
  'Source Serif 4': 'ital,wght@0,400;0,600;1,400',
  'Karla': 'wght@400;500;600;700',
  'JetBrains Mono': 'wght@400;500;600',
};
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';
function get(url) { return new Promise((res, rej) => { https.get(url, { headers: { 'User-Agent': UA } }, r => { let d = ''; r.on('data', c => d += c); r.on('end', () => res({ status: r.statusCode, body: d })); }).on('error', rej); }); }
function dl(url, file) { return new Promise((res, rej) => { const f = fs.createWriteStream(file); https.get(url, { headers: { 'User-Agent': UA } }, r => { r.pipe(f); f.on('finish', () => f.close(() => res(r.statusCode))); }).on('error', rej); }); }
(async () => {
  let cssOut = '';
  for (const [fam, spec] of Object.entries(families)) {
    const url = 'https://fonts.googleapis.com/css2?family=' + encodeURIComponent(fam) + ':' + spec + '&display=swap';
    const r = await get(url);
    if (r.status !== 200) { console.error('FAIL', fam, r.status); continue; }
    const urls = [...r.body.matchAll(/url\((https:[^)]+\.woff2)\)/g)].map(m => m[1]);
    let css = r.body;
    let i = 0;
    for (const u of urls) {
      i++;
      const name = fam.replace(/[^a-z0-9]+/gi, '-').toLowerCase() + '-' + i + '.woff2';
      await dl(u, path.join(outDir, name));
      css = css.split(u).join(name);
    }
    cssOut += css + '\n';
    console.log('OK', fam, urls.length, 'files');
  }
  fs.writeFileSync(path.join(outDir, 'fonts.css'), cssOut);
  console.log('WROTE fonts.css');
})().catch(e => { console.error(e); process.exit(1); });
