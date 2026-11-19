'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const helpers = require('../ext/crm')._внутр;
const code = fs.readFileSync(require.resolve('../ext/crm'), 'utf8'), FIELD = helpers.ДОМОФОН;

// Observed read-only in the MNC create form on 2026-10-19. No means 2, not 0.
const observedOptions = [
  { value: '', text: 'Наличие домофона ...' },
  { value: '2', text: 'Нет домофона' },
  { value: '1', text: 'Есть домофон' },
];
function form(value = '', options = observedOptions) {
  const elements = ['locality', 'street', 'building', 'office', 'entrance', 'floor'].map(k =>
    ({ name: 'Customer[address_' + k + ']', tagName: 'INPUT', type: 'text', value: '' }));
  elements.push({ name: FIELD, tagName: 'SELECT', value, options: options.map(o => ({ ...o })) });
  for (const e of elements) elements[e.name] = e;
  return { elements, getAttribute: () => '' };
}

test('observed CRM labels distinguish presence, absence and the unselected placeholder', () => {
  for (const [value, expected] of [['1', '1'], ['2', '0'], ['', null]]) {
    assert.equal(helpers.intercomValue(form(value).elements[FIELD]), expected);
  }
  assert.equal(helpers.intercomChoice(form(), { has_intercom: true }).value, '1');
  assert.equal(helpers.intercomChoice(form(), { has_intercom: false }).value, '2');
  assert.equal(helpers.intercomChoice(form('1'), { has_intercom: null }).value, null);
});

test('only explicit known labels are accepted; numeric ids are never guessed', () => {
  for (const text of ['Есть домофон', ' ЕСТЬ\u00a0ДОМОФОН ', 'Да', 'yes']) {
    assert.equal(helpers.intercomChoice(form('', [{ value: 'opaque', text }]), { has_intercom: true }).value, 'opaque');
  }
  for (const text of ['Нет домофона', ' НЕТ\u00a0ДОМОФОНА ', 'Нет', 'no']) {
    assert.equal(helpers.intercomChoice(form('', [{ value: 'opaque', text }]), { has_intercom: false }).value, 'opaque');
  }
  for (const text of ['Наличие домофона ...', 'Неизвестно', 'Да / Нет', 'Домофон']) {
    for (const wanted of [true, false]) {
      const choice = helpers.intercomChoice(form('', [{ value: '1', text }, { value: '2', text }]), { has_intercom: wanted });
      assert.equal(choice.value, null); assert.ok(choice.error);
    }
  }
  assert.ok(helpers.intercomChoice(form('', [{ value: '1', text: 'Есть домофон', disabled: true }]), { has_intercom: true }).error);
});

for (const [wanted, initial, expected] of [[true, '2', '1'], [false, '1', '2']]) {
  test(`profile plan and readback use actual CRM ids: presence=${wanted}`, () => {
    const f = form(initial), plan = helpers.планКлиента(f, { has_intercom: wanted }, []);
    assert.equal(plan.error, ''); assert.equal(plan.ставим[FIELD], expected);
    assert.deepEqual(Array.from(plan.changed), ['домофон']);
    assert.deepEqual(Array.from(helpers.несохранено(f, plan.ставим)), ['домофон']);
    helpers.setVal(f, FIELD, expected);
    assert.equal(helpers.serializeForm(f).get(FIELD), expected);
    assert.equal(helpers.несохранено(f, plan.ставим).length, 0);
    assert.equal(Object.keys(helpers.планКлиента(f, { has_intercom: wanted }, []).ставим).length, 0);
    assert.equal(Object.keys(helpers.планКлиента(f, { has_intercom: null }, []).ставим).length, 0);
  });

  test(`profile update sends once and verifies the saved CRM label: presence=${wanted}`, async () => {
    const start = code.indexOf('  async function обновитьКлиента('), end = code.indexOf('  /* АДРЕС КЛИЕНТА ПО ЗАЯВКЕ', start);
    for (const saves of [true, false]) {
      let reads = 0, posts = 0, submitted;
      const s = { ...helpers, URL, URL_КЛИЕНТА: () => 'https://synthetic.invalid/customer/1', формаКлиента: d => d,
        тел10: x => String(x).replace(/\D/g, '').slice(-10), маскаТел: x => x, БЕЗ_ОТВЕТА: new Map(), записьБезОтвета: () => null, суть: e => e.message,
        fetchDoc: async () => form(++reads === 1 || !saves ? initial : expected),
        записьКлиента: async (_url, body) => { posts++; submitted = new URLSearchParams(body); return { status: 200, ok: true, headers: { get: () => '' }, text: async () => '' }; },
        formErrors: () => [], DOMParser: class { parseFromString() { return { querySelector: () => null }; } } };
      vm.createContext(s); vm.runInContext(code.slice(start, end) + ';globalThis.update=обновитьКлиента;', s);
      const result = await s.update('https://synthetic.invalid', '1', { addr: { has_intercom: wanted } });
      assert.equal(posts, 1); assert.equal(submitted.get(FIELD), expected); assert.equal(result.ok, saves);
      if (!saves) assert.match(result.error, /не сохранила.*домофон/);
    }
  });

  test(`request verification reads the customer profile, including stale and unknown states: presence=${wanted}`, async () => {
    const start = code.indexOf('  async function verifyCreated('), end = code.indexOf('  /* СОЗДАНИЕ —', start);
    for (const actual of [expected, initial, '']) {
      let reads = 0;
      const s = { ...helpers, intercomElement: f => f.elements[FIELD], полеФормы: (f, n) => f.elements[n], полеВидаУслуг: () => null,
        АДРЕС_КЛИЕНТА: {}, одно: () => false, цифры: x => String(x).replace(/\D/g, ''), суть: e => e.message,
        клиентЗаявкиИз: () => '1', URL_КЛИЕНТА: () => 'https://synthetic.invalid/customer/1', формаКлиента: d => d,
        fetchDoc: async url => { reads++; return url.includes('customer-request') ? { querySelector: () => form(expected) } : form(actual); } };
      vm.createContext(s); vm.runInContext(code.slice(start, end) + ';globalThis.verify=verifyCreated;', s);
      const result = await s.verify('https://synthetic.invalid', '2', new URLSearchParams({ _intercom_presence_expected: wanted ? '1' : '0' }));
      assert.equal(reads, 2); assert.equal(result.fields.includes('домофон'), actual === expected);
      assert.equal(result.diffs.length === 0, actual === expected);
    }
  });

  for (const existing of [false, true]) {
    test(`actual create path serializes observed CRM value once: presence=${wanted}, existing=${existing}`, async () => {
      const start = code.indexOf('  async function создатьЗаявку('), marker = code.indexOf('  // адрес и комментарий в карточке', start);
      const end = marker > start ? marker : code.indexOf('\n  async function ', start + 10);
      const f = form();
      for (const name of ['Customer[phone]', 'Customer[first_name]', 'CustomerRequest[city_id]', 'CustomerRequest[comments]', 'CustomerRequest[customer_id]']) {
        const e = { name, tagName: 'INPUT', type: 'text', value: '' }; f.elements.push(e); f.elements[name] = e;
      }
      let posts = 0, updates = 0, verified = 0, submitted;
      const s = { ...helpers, URL, URLSearchParams, BASES: { mnc: 'https://synthetic.invalid' }, CREATE: '/admin/domain/customer-request/create', ИМЯ: { mnc: 'МНЧ' },
        DOMParser: class { parseFromString() { return { querySelector: () => null, querySelectorAll: () => [] }; } },
        customerRequestIds: async () => [],
        заранее: p => () => p, searchAllBases: async () => ({ found: [], unchecked: [] }), findCustomerId: async () => existing ? { id: '11' } : {}, customerStatuses: async () => [],
        ЖИВЫЕ: /active/, МОДЕРАЦИЯ: /moderation/, fetchDoc: async () => ({ querySelector: () => f }), pickOption: () => '', pickNumber: () => '', полеВидаУслуг: () => null,
        fetch: async (_url, o) => { posts++; submitted = new URLSearchParams(o.body); return { status: 302, text: async () => '', headers: { get: n => n === 'X-Redirect' ? '/admin/domain/customer-request/update?id=999' : '' } }; },
        обновитьКлиента: async (_base, id, o) => { updates++; assert.equal(id, '11'); assert.equal(o.addr.has_intercom, wanted); return { ok: true, changed: ['домофон'], warnings: [] }; },
        verifyCreated: async (_base, id, body) => { verified++; assert.equal(id, 999); assert.equal(body.get('_intercom_presence_expected'), wanted ? '1' : '0'); return { fields: ['домофон'], diffs: [] }; },
        АДРЕС_НЕ_ТОТ: '', суть: e => e.message };
      vm.createContext(s); vm.runInContext(code.slice(start, end) + ';globalThis.run=создатьЗаявку;', s);
      const result = await s.run({ dir: 'mnc', lead: { phone: '9001112233', name: 'Иван', addr: { has_intercom: wanted }, comment: 'Сборка' }, sel: { cityId: '1' } }, { отправлено: false });
      assert.equal(result.ok, true); assert.equal(posts, 1); assert.equal(updates, existing ? 1 : 0); assert.equal(verified, 1);
      assert.equal(submitted.get(FIELD), expected); assert.equal(submitted.has('_intercom_presence_expected'), false);
    });
  }
}
