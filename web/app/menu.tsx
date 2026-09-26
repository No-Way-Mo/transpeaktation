'use client';
import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { CLOSED, MENU, open, PAGE_TITLES, SECTIONS, toggle, type Nav, type Page, type Panel, type Section } from '@/lib/nav.ts';
import { LAYERS, layerOn, STYLES } from '@/lib/map-prefs.ts';
import type { ThemePref } from '@/lib/theme.ts';
import type { useRoutePlanner } from '@/lib/use-route-planner.ts';
import { useMapPrefs } from '@/lib/use-map-prefs.ts';
import { useTheme } from '@/lib/use-theme.ts';
import { AiPrivacy, Icon, Logo, Toggle, type IconName } from './parts.tsx';

// ☰ menu, Map layers, Settings and the menu's pages. Shared by desktop (popovers + centred dialogs) and mobile (bottom
// sheets + full-screen pages). Which one is open lives in lib/nav.ts: one at a time, Esc or a click outside closes it.

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
    toggle: (panel: 'menu' | 'layers') => setNav(n => toggle(n, panel)),
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

/** Desktop popover: a press anywhere outside `wrap` (the button + popover) closes it. */
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

const stop = (e: React.SyntheticEvent) => e.stopPropagation();

/** Phone bottom sheet with a dimmed backdrop (tap it to close). Portalled: the start sheet's blur would trap `fixed`. */
function BottomSheet({ label, onClose, children }: { label: string; onClose(): void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useFocusReturn();
  useEffect(() => box.current?.focus({ preventScroll: true }), []);
  return createPortal(
    <>
      <div className="nav-backdrop" onPointerDown={stop} onClick={e => { stop(e); onClose(); }} />
      {/* Portal events still bubble up the React tree: keep them away from the start sheet's drag handle. */}
      <div className="nav-sheet" role="dialog" aria-modal="true" aria-label={label} ref={box} tabIndex={-1} onKeyDown={trapTab}
        onPointerDown={stop} onPointerMove={stop} onPointerUp={stop} onClick={stop}>
        <div className="grabber static" />
        {children}
      </div>
    </>, document.body);
}

// ---------- ☰ main menu ----------

/** ☰ button + the menu. Desktop: a popover under the button. Phone: a bottom sheet. */
export function MainMenu({ n, sheet, className = '' }: { n: NavApi; sheet?: boolean; className?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const on = n.nav.panel === 'menu';
  useOutside(wrap, n.close, on && !sheet);
  const list = <MenuList n={n} />;
  return (
    <div className="nav-wrap" ref={wrap}>
      <button className={`menu-btn ${className}`} data-nav-home aria-label="Main menu" title="Menu" aria-expanded={on} aria-haspopup="dialog"
        onClick={() => n.toggle('menu')}>
        <Icon name="menu" size={20} />
      </button>
      {on && (sheet ? <BottomSheet label="Main menu" onClose={n.close}>{list}</BottomSheet> : <Popover label="Main menu" className="menu-pop">{list}</Popover>)}
    </div>
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

/** Floating layers button on the map's right edge + its panel (popover on desktop, bottom sheet on a phone). */
export function MapLayers({ n, sheet, className = '' }: { n: NavApi; sheet?: boolean; className?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const on = n.nav.panel === 'layers';
  useOutside(wrap, n.close, on && !sheet);
  const body = <LayersBody onClose={n.close} />;
  return (
    <div className={`nav-wrap layers-wrap ${className}`} ref={wrap}>
      <button className="layers-btn" aria-label="Map layers" title="Map layers" aria-expanded={on} aria-haspopup="dialog" onClick={() => n.toggle('layers')}>
        <Icon name="layers" size={20} />
      </button>
      {on && (sheet ? <BottomSheet label="Map layers" onClose={n.close}>{body}</BottomSheet> : <Popover label="Map layers" className="layers-pop">{body}</Popover>)}
    </div>
  );
}

function LayersBody({ onClose }: { onClose(): void }) {
  const { prefs, toggle, setStyle } = useMapPrefs();
  const groups = [...new Set(LAYERS.map(l => l.group))];
  return (
    <div className="layers">
      <div className="pop-head"><span className="pop-title">Map layers</span>
        <button className="close-btn" aria-label="Close map layers" onClick={onClose}><Icon name="close" size={14} /></button>
      </div>
      {groups.map(g => (
        <section key={g} className="layer-group" aria-label={g}>
          <h3 className="eyebrow">{g}</h3>
          <div className="aip-switches">
            {LAYERS.filter(l => l.group === g).map(l => (
              <Toggle key={l.id} label={l.label} detail={l.detail} on={layerOn(prefs, l)} status={l.status} onChange={() => toggle(l.id)} />
            ))}
          </div>
        </section>
      ))}
      <StylePicker value={prefs.style} onChange={setStyle} legend="Map style" />
    </div>
  );
}

/** Standard / Satellite as native radios (arrow keys work). */
function StylePicker({ value, onChange, legend }: { value: string; onChange(v: 'standard' | 'satellite'): void; legend: string }) {
  const name = useId();
  return (
    <fieldset className="choice style-choice">
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

const THEMES: { id: ThemePref; label: string; sub: string }[] = [
  { id: 'system', label: 'System', sub: 'Match this device’s light or dark setting.' },
  { id: 'light', label: 'Light', sub: '' },
  { id: 'dark', label: 'Dark', sub: '' },
];

function Appearance() {
  const { pref, setPref } = useTheme();
  const name = useId();
  return (
    <fieldset className="choice">
      <legend className="eyebrow">Theme</legend>
      <div className="choice-list">
        {THEMES.map(t => (
          <label key={t.id} className="choice-row">
            <input type="radio" name={name} value={t.id} checked={pref === t.id} onChange={() => setPref(t.id)} />
            <span className="stack grow"><span className="name">{t.label}</span>{t.sub && <span className="sub">{t.sub}</span>}</span>
          </label>
        ))}
      </div>
      <p className="sub set-foot">Remembered in this browser.</p>
    </fieldset>
  );
}

/** Same state as the Map layers button: changing either changes both, and it's remembered on this device. */
function MapDefaults() {
  const { prefs, toggle, setStyle } = useMapPrefs();
  return (
    <div className="set-stack">
      <StylePicker value={prefs.style} onChange={setStyle} legend="Default map style" />
      <section className="layer-group" aria-label="Default map layers">
        <h4 className="eyebrow">Default map layers</h4>
        <div className="aip-switches">
          {LAYERS.filter(l => l.key).map(l => <Toggle key={l.id} label={l.label} detail={l.detail} on={layerOn(prefs, l)} onChange={() => toggle(l.id)} />)}
        </div>
      </section>
      <p className="sub set-foot">These are the same switches as the Map layers button on the map, remembered in this browser.
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
      <p>The layers button on the map turns event pins and route traffic colours on or off and switches between the
        standard and satellite map. Settings → Map &amp; Routing holds the same choices.</p>
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
