import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CLOSED, MENU, open, SECTIONS, toggle } from './nav.ts';

test('☰ opens and a second press closes it', () => {
  const a = toggle(CLOSED, 'menu');
  assert.equal(a.panel, 'menu');
  assert.deepEqual(toggle(a, 'menu'), CLOSED);
});

test('only one panel at a time: a menu page or Settings replaces the menu', () => {
  const menu = toggle(CLOSED, 'menu');
  assert.equal(open('settings').panel, 'settings');
  assert.equal(open('help').panel, 'help');
  assert.equal(toggle(open('settings'), 'menu').panel, 'menu'); // the logo from Settings opens the menu instead
  assert.equal(menu.section, null);
});

test('menu entries, in order, with the two dividers', () => {
  assert.deepEqual(MENU.map(m => m?.label ?? '---'),
    ['Saved Places', 'Saved Events', 'Trip History', '---', 'Add Event', 'My Events', '---', 'Settings', 'Help & Feedback', '---', 'About us']);
  const ids = MENU.flatMap(m => m && !('href' in m) && !('host' in m) ? [m.id] : []);
  assert.deepEqual(ids.map(id => open(id).panel), ids); // every panel entry opens its own page
  assert.deepEqual(MENU.flatMap(m => m && 'href' in m ? [m.href] : []), ['/about']); // About us: the /about page (new tab)
  assert.ok(!MENU.some(m => m && /account|profile|sign in|avatar/i.test(m.label)));
});

test('settings sections and where Settings opens', () => {
  assert.deepEqual(SECTIONS.map(s => s.label), ['Appearance', 'Map & Routing', 'AI & Privacy', 'Rewards Wallet', 'Notifications']);
  assert.deepEqual(open('settings'), { panel: 'settings', section: 'appearance' });           // desktop: first section
  assert.deepEqual(open('settings', null, false), { panel: 'settings', section: null });       // phone: the section list
  assert.deepEqual(open('settings', 'privacy', false), { panel: 'settings', section: 'privacy' }); // route card's trace strip
  assert.equal(open('help', 'privacy').section, null); // sections only mean something in Settings
});

test('community section: Add Event (emphasised, +) and My Events open hosting views, not menu pages', () => {
  const host = MENU.flatMap(m => m && 'host' in m ? [m] : []);
  assert.deepEqual(host.map(m => [m.id, m.label, m.icon, !!m.accent]),
    [['savedEvents', 'Saved Events', 'bookmark', false], ['addEvent', 'Add Event', 'plus', true], ['myEvents', 'My Events', 'calendar', false]]);
  assert.equal(MENU[MENU.findIndex(m => m?.id === 'saved') + 1]?.id, 'savedEvents'); // right under Saved Places
  const i = MENU.findIndex(m => m?.id === 'addEvent');
  assert.equal(MENU[i - 1], null);   // its own section, between Trip History...
  assert.equal(MENU[i + 2], null);   // ...and Settings
});
