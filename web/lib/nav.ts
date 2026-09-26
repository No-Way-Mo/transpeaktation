// The ☰ menu, the Map layers panel, Settings and the menu's pages: which one is open. Only one at a time, so opening
// any of them replaces whatever was open. Plain TS so `node --test` can run it; the React side is app/menu.tsx.

export type Page = 'saved' | 'history' | 'help' | 'about';
export type Section = 'appearance' | 'map' | 'privacy' | 'notifications';
export type Panel = 'menu' | 'layers' | 'settings' | Page;
/** `section` = the open Settings section; null on a phone means the section list (stacked navigation). */
export type Nav = { panel: Panel | null; section: Section | null };
export const CLOSED: Nav = { panel: null, section: null };

export const SECTIONS: { id: Section; label: string }[] = [
  { id: 'appearance', label: 'Appearance' },
  { id: 'map', label: 'Map & Routing' },
  { id: 'privacy', label: 'AI & Privacy' },
  { id: 'notifications', label: 'Notifications' },
];

/** ☰ menu entries in order; `null` = divider. */
export const MENU: ({ id: Panel; label: string; icon: 'star' | 'history' | 'settings' | 'help' | 'info' } | null)[] = [
  { id: 'saved', label: 'Saved Places', icon: 'star' },
  { id: 'history', label: 'Trip History', icon: 'history' },
  null,
  { id: 'settings', label: 'Settings', icon: 'settings' },
  { id: 'help', label: 'Help & Feedback', icon: 'help' },
  null,
  { id: 'about', label: 'About transPEAKtation', icon: 'info' },
];

export const PAGE_TITLES: Record<Page, string> = {
  saved: 'Saved Places', history: 'Trip History', help: 'Help & Feedback', about: 'About transPEAKtation',
};

/** Open `panel` (closing anything else). Settings opens at `section`, or the first section on a wide screen. */
export function open(panel: Panel, section: Section | null = null, wide = true): Nav {
  return { panel, section: panel === 'settings' ? section ?? (wide ? 'appearance' : null) : null };
}

/** The ☰ and layers buttons: a second press closes their own panel; from anything else it opens theirs. */
export const toggle = (nav: Nav, panel: 'menu' | 'layers'): Nav => (nav.panel === panel ? CLOSED : open(panel));
