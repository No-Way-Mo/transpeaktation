'use client';
import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { CLOSED, MENU, open, PAGE_TITLES, SECTIONS, toggle, type Nav, type Page, type Panel, type Section } from '@/lib/nav.ts';
import { LOCATION_MODES } from '@/lib/location.ts';
import { LAYERS, layerOn, overlaysOn, STYLES } from '@/lib/map-prefs.ts';
import type { ThemePref } from '@/lib/theme.ts';
import type { useRoutePlanner } from '@/lib/use-route-planner.ts';
import { useMapPrefs } from '@/lib/use-map-prefs.ts';
import { useTheme } from '@/lib/use-theme.ts';
import { AiPrivacy, EventKey, Icon, Logo, Toggle, type IconName } from './parts.tsx';

// Logo menu, Map layers button, Settings and the menu's pages. Shared by desktop (centred dialogs) and mobile
// (full-screen pages). Which one is open lives in lib/nav.ts: one at a time, Esc or a click outside closes it.

type Planner = ReturnType<typeof useRoutePlanner>;
export type NavApi = ReturnType<typeof useNav>;

/** Open / close state for every overlay here. `wide` = desktop layout (Settings opens on its first section). */
export function useNav(wide: boolean) {
  const [nav, setNav] = useState<Nav>(CLOSED);
  const isOpen = !!nav.panel;
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setNav(CLOSED); };
    addEventListener('keydown', onKey);
    return () => removeEventListener('keydown', onKey);
  }, [isOpen]);
  return {
    nav,
    open: (panel: Panel, section?: Section) => setNav(open(panel, section, wide)),
    toggle: (panel: 'menu') => setNav(n => toggle(n, panel)),
    section: (section: Section | null) => setNav(n => ({ ...n, section })),
    close: () => setNav(CLOSED),
  };
}

/** Closing an overlay puts focus back where it was (or on ☰, if that spot is gone, e.g. a menu item). */
function useFocusReturn() {
  useEffect(() => {
    const from = document.activeElement as HTMLElement | null;
    return () => {
      const to = from?.isConnected ? from : document.querySelector<HTMLElement>('[data-nav-home]');
      to?.focus({ preventScroll: true });
    };
  }, []);
}

/** Menu popover: a press anywhere outside `wrap` (the button + popover) closes it. */
function useOutside(wrap: RefObject<HTMLElement | null>, onClose: () => void, on: boolean) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (!on) return;
    const down = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) close.current(); };
    document.addEventListener('pointerdown', down);
    return () => document.removeEventListener('pointerdown', down);
  }, [on]);
}

/** Keep Tab inside a modal dialog. */
function trapTab(e: React.KeyboardEvent<HTMLElement>) {
  if (e.key !== 'Tab') return;
  const all = [...e.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), summary, [href], [tabindex="0"]')];
  if (!all.length) return;
  const first = all[0], last = all[all.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

// ---------- ☰ main menu ----------

/** The menu bar across the top of the page: the app icon is the menu button, the menu drops down under it. */
export function AppBar({ n, className = '' }: { n: NavApi; className?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const on = n.nav.panel === 'menu';
  useOutside(wrap, n.close, on);
  return (
    <header className={`app-bar ${className}`}>
      <div className="nav-wrap" ref={wrap}>
        <button className="logo-btn" data-nav-home aria-label="Main menu" title="Menu" aria-expanded={on} aria-haspopup="dialog"
          onClick={() => n.toggle('menu')}>
          <Logo size={26} />
        </button>
        {on && <Popover label="Main menu" className="menu-pop"><MenuList n={n} /></Popover>}
      </div>
      <span className="wordmark">transPEAKtation</span>
    </header>
  );
}

function Popover({ label, className, children }: { label: string; className: string; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useFocusReturn();
  useEffect(() => { box.current?.querySelector<HTMLElement>('button:not([disabled])')?.focus({ preventScroll: true }); }, []);
  return <div className={`pop ${className}`} role="dialog" aria-label={label} ref={box}>{children}</div>;
}

function MenuList({ n }: { n: NavApi }) {
  return (
    <nav className="menu-list" aria-label="Main menu">
      <div className="menu-brand"><Logo size={18} stroke={3} /><span>transPEAKtation</span></div>
      {MENU.map((m, i) => m
        ? <button key={m.id} className="menu-item" onClick={() => n.open(m.id)}><Icon name={m.icon} size={18} className="lead" /><span>{m.label}</span></button>
        : <hr key={i} className="menu-sep" />)}
    </nav>
  );
}

// ---------- map layers ----------

/** Floating layers button on the map's right edge: one tap shows or hides the map's layers (event pins + route
 *  traffic). The map style and each layer on its own are in Settings → Map & Routing. While event pins show, a small
 *  key button beside it opens what the pin colours / glyphs mean; an outside tap or Escape closes it. */
export function MapLayers({ className = '' }: { className?: string }) {
  const { prefs, setOverlays } = useMapPrefs();
  const on = overlaysOn(prefs);
  const [keyOpen, setKeyOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null), popId = useId();
  const showKey = keyOpen && prefs.eventPins;
  useEffect(() => {
    if (!showKey) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !wrap.current?.contains(e.target as Node)) setKeyOpen(false);
    };
    addEventListener('pointerdown', close); addEventListener('keydown', close);
    return () => { removeEventListener('pointerdown', close); removeEventListener('keydown', close); };
  }, [showKey]);
  return (
    <div ref={wrap} className={`layers-wrap ${className}`}>
      <button className="layers-btn" aria-label="Map layers" aria-pressed={on} title={on ? 'Hide map layers' : 'Show map layers'}
        onClick={() => setOverlays(!on)}>
        <Icon name={on ? 'layers' : 'layersOff'} size={18} />
      </button>
      {prefs.eventPins && (
        <button className="layers-btn key-btn" aria-label="Event types" aria-expanded={showKey} aria-controls={popId} title="Event types"
          onClick={() => setKeyOpen(o => !o)}>
          <Icon name="info" size={18} />
        </button>
      )}
      {showKey && <div id={popId} className="key-pop" role="group" aria-label="Event types"><h4 className="eyebrow">Event types</h4><EventKey /></div>}
    </div>
  );
}

/** Standard / Satellite as native radios (arrow keys work). */
function StylePicker({ value, onChange, legend }: { value: string; onChange(v: 'standard' | 'satellite'): void; legend: string }) {
  const name = useId();
  return (
    <fieldset className="choice">
      <legend className="eyebrow">{legend}</legend>
      <div className="style-opts">
        {STYLES.map(s => (
          <label key={s.id} className={`style-opt s-${s.id}`}>
            <span className="swatch" aria-hidden="true" />
            <span className="style-name"><input type="radio" name={name} value={s.id} checked={value === s.id} onChange={() => onChange(s.id)} />{s.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

// ---------- dialogs: Settings + the menu's pages ----------

/** Centred dialog on desktop, full screen on a phone. Esc (useNav), the × / Done button or the backdrop closes it. */
function Dialog({ title, onClose, wide, big, back, children }: {
  title: string; onClose(): void; wide: boolean; big?: boolean; back?: () => void; children: ReactNode;
}) {
  const id = useId(), box = useRef<HTMLDivElement>(null);
  useFocusReturn();
  useEffect(() => box.current?.focus({ preventScroll: true }), []);
  return createPortal(
    <>
      {wide && <div className="nav-backdrop" onClick={onClose} />}
      <div className={`dialog${wide ? '' : ' full'}${big ? ' big' : ''}`} role="dialog" aria-modal="true" aria-labelledby={id} ref={box} tabIndex={-1} onKeyDown={trapTab}>
        <header className="dialog-head">
          {back && <button className="round-btn" aria-label="Back" title="Back" onClick={back}><Icon name="back" size={18} /></button>}
          <h2 id={id} className="dialog-title grow">{title}</h2>
          {wide
            ? <button className="close-btn" aria-label="Close" title="Close" onClick={onClose}><Icon name="close" size={16} /></button>
            : <button className="link-btn" onClick={onClose}>Done</button>}
        </header>
        {children}
      </div>
    </>, document.body);
}

/** Whatever the menu opened: Settings or one of the pages. Renders nothing while only a popover (or nothing) is open. */
export function NavDialogs({ n, p, wide }: { n: NavApi; p: Planner; wide: boolean }) {
  const { panel, section } = n.nav;
  if (panel === 'settings') return <Settings n={n} p={p} wide={wide} section={section} />;
  if (panel === 'saved' || panel === 'history' || panel === 'help' || panel === 'about') {
    return <Dialog title={PAGE_TITLES[panel]} onClose={n.close} wide={wide}><div className="dialog-body prose">{PAGES[panel]}</div></Dialog>;
  }
  return null;
}

const SECTION_ICONS: Record<Section, IconName> = { appearance: 'sun', map: 'layers', privacy: 'shield', notifications: 'bell' };

/** Desktop: section list on the left, the section on the right. Phone: the list, then one section with Back. */
function Settings({ n, p, wide, section }: { n: NavApi; p: Planner; wide: boolean; section: Section | null }) {
  const current = SECTIONS.find(s => s.id === section);
  const heading = current && (current.id === 'privacy' ? 'AI & privacy' : current.label); // the panel's own title, kept
  const tabs = (
    <nav className="settings-nav" aria-label="Settings sections">
      {SECTIONS.map(s => (
        <button key={s.id} className="settings-tab" aria-current={s.id === section ? 'page' : undefined} onClick={() => n.section(s.id)}>
          <Icon name={SECTION_ICONS[s.id]} size={18} className="lead" /><span className="grow">{s.label}</span>
          {!wide && <Icon name="chevron" size={14} rotate={-90} className="lead" />}
        </button>
      ))}
    </nav>
  );
  if (!wide) {
    return (
      <Dialog title={heading || 'Settings'} onClose={n.close} wide={false} back={current ? () => n.section(null) : undefined}>
        <div className="dialog-body">{current ? <SectionBody s={current.id} p={p} /> : tabs}</div>
      </Dialog>
    );
  }
  return (
    <Dialog title="Settings" onClose={n.close} wide big>
      <div className="settings">
        {tabs}
        <div className="settings-body" key={section}>
          {current && <h3 className="settings-h">{heading}</h3>}
          {current && <SectionBody s={current.id} p={p} />}
        </div>
      </div>
    </Dialog>
  );
}

function SectionBody({ s, p }: { s: Section; p: Planner }) {
  if (s === 'appearance') return <Appearance />;
  if (s === 'map') return <MapDefaults />;
  if (s === 'privacy') return <AiPrivacy p={p} />;
  return <Notifications />;
}

const SYSTEM_THEME = { id: 'system', label: 'System', sub: 'Match this device’s light or dark setting.' } as const;
const MANUAL_THEMES: { id: ThemePref; label: string; icon: IconName }[] = [
  { id: 'light', label: 'Light', icon: 'sun' },
  { id: 'dark', label: 'Dark', icon: 'moon' },
];

/** System on its own row, then Light / Dark side by side. One radio group, so arrow keys move through all three. */
function Appearance() {
  const { pref, setPref } = useTheme();
  const name = useId();
  const radio = (id: ThemePref) => <input type="radio" name={name} value={id} checked={pref === id} onChange={() => setPref(id)} />;
  return (
    <fieldset className="choice">
      <legend className="eyebrow">Theme</legend>
      <div className="choice-list">
        <label className="choice-row">
          {radio(SYSTEM_THEME.id)}
          <span className="stack grow"><span className="name">{SYSTEM_THEME.label}</span><span className="sub">{SYSTEM_THEME.sub}</span></span>
        </label>
      </div>
      <p className="sub choice-or">or choose manually</p>
      <div className="theme-opts">
        {MANUAL_THEMES.map(t => (
          <label key={t.id} className="theme-opt">
            {radio(t.id)}
            <Icon name={t.icon} size={18} /><span>{t.label}</span>
          </label>
        ))}
      </div>
      <p className="sub set-foot">Remembered in this browser.</p>
    </fieldset>
  );
}

/** Same state as the Map layers button: changing either changes both, and it's remembered on this device. */
function MapDefaults() {
  const { prefs, toggle, setStyle, setLocation } = useMapPrefs();
  const name = useId();
  return (
    <div className="set-stack">
      <fieldset className="choice">
        <legend className="eyebrow">Location mode</legend>
        <div className="choice-list">
          {LOCATION_MODES.map(m => (
            <label key={m.id} className="choice-row">
              <input type="radio" name={name} value={m.id} checked={prefs.location === m.id} onChange={() => setLocation(m.id)} />
              <span className="stack grow"><span className="name">{m.label}</span><span className="sub">{m.sub}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      <StylePicker value={prefs.style} onChange={setStyle} legend="Default map style" />
      <section className="layer-group" aria-label="Default map layers">
        <h4 className="eyebrow">Default map layers</h4>
        <div className="aip-switches">
          {LAYERS.filter(l => l.key).map(l => <Toggle key={l.id} label={l.label} detail={l.detail} on={layerOn(prefs, l)} onChange={() => toggle(l.id)} />)}
        </div>
      </section>
      <section className="layer-group" aria-label="Event types">
        <h4 className="eyebrow">Event types</h4>
        <EventKey />
      </section>
      <p className="sub set-foot">The layers button on the map turns these on or off together. Remembered in this browser.
 Event Activity and Road Disruptions aren’t available yet.</p>
    </div>
  );
}

function Notifications() {
  return (
    <div className="set-stack">
      <div className="soon-row" aria-disabled="true">
        <Icon name="bell" size={18} className="lead" />
        <span className="stack grow">
          <span className="switch-head"><span className="name">Routine disruption alerts</span><span className="tag off">Coming soon</span></span>
          <span className="sub">Get a heads-up when an upcoming event or road closure may affect a route you regularly take.</span>
        </span>
      </div>
      <p className="sub set-foot">Not built yet: there are no notifications, and nothing learns your routine.</p>
    </div>
  );
}

// ---------- the menu's pages (only what this app really does) ----------

const PAGES: Record<Page, ReactNode> = {
  saved: (
    <div className="empty">
      <Icon name="star" size={28} className="lead" />
      <b>No saved places yet.</b>
      <p>Saving places isn’t available yet. When it is, places you save, like home or work, will appear here.</p>
    </div>
  ),
  history: (
    <div className="empty">
      <Icon name="history" size={28} className="lead" />
      <b>No trip history.</b>
      <p>Trips aren’t kept on this device. With <i>Save my trips</i> on, an area-level record of each trip goes to our
        server for crowd forecasts, but it isn’t linked to you, so it can’t be shown back here.</p>
    </div>
  ),
  help: (
    <>
      <h3>Planning a route</h3>
      <p>Search under <i>Where to?</i> or pick a recent place. You get the transPEAKtation route, which accounts for events,
        closures and traffic, plus the normal routes. Use <i>Leave now</i> to plan for a later departure or an arrival time.</p>
      <p>With <i>Voice requests</i> on, tap the mic and say a trip, like “Chase Center at 6:30”.</p>
      <h3>Using the map</h3>
      <p>Tap a route line or its time bubble to select it. The compass recenters the map (north is always up); on a
        phone you can drag it out of the way.</p>
      <h3>Understanding event information</h3>
      <p>Pins show events during your trip, coloured by kind. Tap one for its venue, time and estimated crowd. The dashed
        ring around it is an estimated area where traffic may slow. Route cards say when an event or closure adds time.</p>
      <h3>Map layers</h3>
      <p>One tap on the layers button on the map hides or shows event pins and route traffic colours. Settings → Map
        &amp; Routing switches each one on its own and picks the standard or satellite map.</p>
      <h3>Feedback</h3>
      <p>There’s no feedback form in the app yet.</p>
    </>
  ),
  about: (
    <>
      <p>transPEAKtation helps you understand how events and transportation conditions may affect movement around San
        Francisco, and picks a route that accounts for them.</p>
      <h3>Data sources</h3>
      <ul>
        <li><b>Routes and place search:</b> Mapbox, with OSRM on OpenStreetMap as a fallback.</li>
        <li><b>Map:</b> Esri basemap and satellite tiles.</li>
        <li><b>Events:</b> PredictHQ.</li>
        <li><b>Closures and incidents:</b> DataSF (street closures, street-use and excavation permits, police dispatch), Caltrans lane closures and CHP incidents.</li>
        <li><b>Traffic:</b> Mapbox, TomTom, and Muni vehicle positions from 511.org.</li>
        <li><b>Road network:</b> OpenStreetMap.</li>
        <li><b>AI:</b> Google Gemini for route explanations, ElevenLabs for voice requests. See Settings → AI &amp; Privacy.</li>
      </ul>
    </>
  ),
};
