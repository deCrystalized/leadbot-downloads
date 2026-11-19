/* МОДУЛИ РАСШИРЕНИЯ БЕЗ ИЗМЕНЕНИЙ: те же файлы, что в ext/ (extract.js, address.js, territory.js…), исполняются в vm —
   как importScripts в фоне расширения и как в тестах. Так правила разбора на сервере и на экране — одни и те же.
   В собранном dist/index.js тексты модулей встроены (__LC_EXT); при разработке и в тестах — читаются из ../ext. */
'use strict';
const vm = require('vm');

// порядок — как importScripts в background.js (без config.js и avito.js: ключей и Авито у мозга нет)
const ФАЙЛЫ = ['cityslugs.js', 'extract.js', 'avito.js', 'reglament.js', 'pick.js', 'addrrules.js', 'address.js', 'checklist.js', 'tg.js', 'territory.js', 'workflow.js'];
const ИМЕНА = ['LC_CITY_SLUGS', 'LC_EXTRACT', 'LC_AVITO', 'LC_REGLAMENT', 'LC_PICK', 'LC_ADDR_RULES', 'LC_ADDRESS', 'LC_CHECK', 'LC_TG', 'LC_TERRITORY', 'LC_WORKFLOW'];

function источники(dir) {
  /* global __LC_EXT */
  if (!dir && typeof __LC_EXT !== 'undefined') return __LC_EXT;
  const fs = require('fs'), path = require('path');
  const d = dir || process.env.BRAIN_EXT_DIR || path.join(__dirname, '..', 'ext');
  const out = {};
  for (const f of ФАЙЛЫ) out[f] = fs.readFileSync(path.join(d, f), 'utf8');
  return out;
}

function загрузитьМодули(dir) {
  const src = источники(dir);
  const ctx = vm.createContext({ console, URL, URLSearchParams, setTimeout, clearTimeout, encodeURIComponent, decodeURIComponent, Intl, Date, JSON, Promise });
  for (const f of ФАЙЛЫ) vm.runInContext(src[f], ctx, { filename: 'ext/' + f });
  const M = {};
  for (const n of ИМЕНА) M[n] = vm.runInContext('typeof ' + n + ' !== "undefined" ? ' + n + ' : null', ctx);
  // версия правил разбора — в ключ кэша: после выпуска исправленного extract.js старые ответы ИИ не берём
  M.версияРазбора = require('crypto').createHash('sha256').update(src['cityslugs.js'] + '\u0001' + src['extract.js']).digest('hex').slice(0, 16);
  return M;
}

module.exports = { загрузитьМодули, источники, ФАЙЛЫ };
