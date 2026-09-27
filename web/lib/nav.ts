// The logo menu, Settings and the menu's pages: which one is open. Only one at a time, so opening
// any of them replaces whatever was open. Plain TS so `node --test` can run it; the React side is app/menu.tsx.

export type Page = 'saved' | 'history' | 'help';
export type Section = 'appearance' | 'map' | 'privacy' | 'wallet' | 'notifications';
export type Panel = 'menu' | 'settings' | Page;
/** `section` = the open Settings section; null on a phone means the section list (stacked navigation). */
export type Nav = { panel: Panel | null; section: Section | null };
export const CLOSED: Nav = { panel: null, section: null };

export const SECTIONS: { id: Section; label: string }[] = [
  { id: 'appearance', label: 'Appearance' },
  { id: 'map', label: 'Map & Routing' },
  { id: 'privacy', label: 'AI & Privacy' },
  { id: 'wallet', label: 'Rewards Wallet' }, // iOS app only (app/menu.tsx)
  { id: 'notifications', label: 'Notifications' },
];

/** Community events (app/host.tsx): Add Event, My Events (hosted in this browser) and Saved Events (saved in this
 *  browser) open over the map, not as menu pages. */
export type HostAction = 'addEvent' | 'myEvents' | 'savedEvents';

/** ☰ menu entries in order; `null` = divider. An entry with `href` is a link (opens in a new tab), one with `host` a
 *  hosting view (`accent` = the slightly emphasised Add Event), any other a panel. */
type MenuIcon = 'star' | 'history' | 'settings' | 'help' | 'info' | 'plus' | 'calendar' | 'bookmark';
export type MenuEntry =
  | { id: Panel; label: string; icon: MenuIcon }
  | { id: string; label: string; icon: MenuIcon; href: string }
  | { id: HostAction; label: string; icon: MenuIcon; host: true; accent?: boolean };
export const MENU: (MenuEntry | null)[] = [
  { id: 'saved', label: 'Saved Places', icon: 'star' },
  { id: 'savedEvents', label: 'Saved Events', icon: 'bookmark', host: true },
  { id: 'history', label: 'Trip History', icon: 'history' },
  null,
  { id: 'addEvent', label: 'Add Event', icon: 'plus', host: true, accent: true },
  { id: 'myEvents', label: 'My Events', icon: 'calendar', host: true },
  null,
  { id: 'settings', label: 'Settings', icon: 'settings' },
  { id: 'help', label: 'Help & Feedback', icon: 'help' },
  null,
  { id: 'about', label: 'About us', icon: 'info', href: '/about' },
];

export const PAGE_TITLES: Record<Page, string> = {
  saved: 'Saved Places', history: 'Trip History', help: 'Help & Feedback',
};

/** Open `panel` (closing anything else). Settings opens at `section`, or the first section on a wide screen. */
export function open(panel: Panel, section: Section | null = null, wide = true): Nav {
  return { panel, section: panel === 'settings' ? section ?? (wide ? 'appearance' : null) : null };
}

/** The logo button: a second press closes the menu; from anything else it opens it. */
export const toggle = (nav: Nav, panel: 'menu'): Nav => (nav.panel === panel ? CLOSED : open(panel));
