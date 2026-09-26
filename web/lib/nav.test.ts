import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CLOSED, MENU, open, SECTIONS, toggle } from './nav.ts';

test('☰ opens and a second press closes it', () => {
  const a = toggle(CLOSED, 'menu');
  assert.equal(a.panel, 'menu');
  assert.deepEqual(toggle(a, 'menu'), CLOSED);
});

test('only one panel at a time: layers replaces the menu, settings replaces both', () => {
  const menu = toggle(CLOSED, 'menu');
  const layers = toggle(menu, 'layers');
  assert.equal(layers.panel, 'layers');
  assert.equal(toggle(layers, 'menu').panel, 'menu');
  assert.equal(open('settings').panel, 'settings');
  // from Settings, the layers button opens layers (Settings closes)
  assert.equal(toggle(open('settings'), 'layers').panel, 'layers');
});

test('menu entries, in order, with the two dividers', () => {
  assert.deepEqual(MENU.map(m => m?.label ?? '---'),
    ['Saved Places', 'Trip History', '---', 'Settings', 'Help & Feedback', '---', 'About transPEAKtation']);
  const ids = MENU.flatMap(m => m ? [m.id] : []);
  assert.deepEqual(ids.map(id => open(id).panel), ids); // every entry opens its own page
  assert.ok(!MENU.some(m => m && /account|profile|sign in|avatar/i.test(m.label)));
});

test('settings sections and where Settings opens', () => {
  assert.deepEqual(SECTIONS.map(s => s.label), ['Appearance', 'Map & Routing', 'AI & Privacy', 'Notifications']);
  assert.deepEqual(open('settings'), { panel: 'settings', section: 'appearance' });           // desktop: first section
  assert.deepEqual(open('settings', null, false), { panel: 'settings', section: null });       // phone: the section list
  assert.deepEqual(open('settings', 'privacy', false), { panel: 'settings', section: 'privacy' }); // route card's trace strip
  assert.equal(open('help', 'privacy').section, null); // sections only mean something in Settings
});
