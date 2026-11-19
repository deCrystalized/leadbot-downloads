#!/usr/bin/env node
/* СБОРКА МОЗГА В ОДИН ФАЙЛ: brain/*.js + страница владельца + модули расширения (ext/*.js, те же файлы без изменений)
   → dist/index.js для вставки в редактор консоли Yandex Cloud (точка входа index.handler). Печатает SHA-256 —
   после вставки сверить с тем, что покажет консоль/скрипт сверки.
   node build.js [папка расширения] [файл результата] */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { ФАЙЛЫ } = require('./modules');

// порядок не важен (свой require), но index — точка входа
const СВОИ = ['index', 'net', 'store', 'budget', 'cache', 'ai', 'tokens', 'team', 'modules', 'ops', 'rules', 'advertiser', 'assistant', 'native-notifications'];

function собрать(extDir, outFile) {
  const ext = path.resolve(extDir || path.join(__dirname, '..', 'ext'));
  const out = path.resolve(outFile || path.join(__dirname, 'dist', 'index.js'));
  const extSrc = {};
  for (const f of ФАЙЛЫ) extSrc[f] = fs.readFileSync(path.join(ext, f), 'utf8');
  const admin = fs.readFileSync(path.join(__dirname, 'admin.html'), 'utf8');
  const версия = (fs.readFileSync(path.join(__dirname, 'index.js'), 'utf8').match(/ВЕРСИЯ = '([^']+)'/) || [])[1] || '?';
  const части = [
    "'use strict';",
    '/* lead-centre-brain ' + версия + ' — один файл для облачной функции (Node.js 22, точка входа index.handler).',
    '   Собрано brain/build.js из brain/*.js и ext/*.js. Не править руками: правки — в исходниках, потом пересобрать. */',
    'const __LC_EXT = ' + JSON.stringify(extSrc) + ';',
    'const __LC_ADMIN = ' + JSON.stringify(admin) + ';',
    'const __LC_SRC = {',
  ];
  for (const n of СВОИ) {
    const src = fs.readFileSync(path.join(__dirname, n + '.js'), 'utf8');
    части.push('  ' + JSON.stringify('./' + n) + ': function (module, exports, require) {\n' + src + '\n  },');
  }
  части.push('};',
    'const __LC_MOD = {};',
    'function __lcRequire(name) {',
    "  const k = String(name).replace(/\\.js$/, '');",
    "  if (!k.startsWith('./')) return require(name);",
    '  if (__LC_MOD[k]) return __LC_MOD[k].exports;',
    '  const m = { exports: {} };',
    '  __LC_MOD[k] = m;',
    '  __LC_SRC[k](m, m.exports, __lcRequire);',
    '  return m.exports;',
    '}',
    "module.exports = __lcRequire('./index');",
    '');
  const код = части.join('\n');
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, код);
  const sha = crypto.createHash('sha256').update(код, 'utf8').digest('hex');
  return { out, sha, bytes: Buffer.byteLength(код), версия };
}

if (require.main === module) {
  const r = собрать(process.argv[2], process.argv[3]);
  console.log('собрано: ' + r.out);
  console.log('версия:  ' + r.версия);
  console.log('размер:  ' + Math.round(r.bytes / 1024) + ' КБ');
  console.log('SHA-256: ' + r.sha);
}

module.exports = { собрать };
