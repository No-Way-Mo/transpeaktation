import type { Metadata } from 'next';
import Link from 'next/link';
import { Logo } from '../parts.tsx';
import { Framed } from './framed.tsx';
import { Player } from './player.tsx';

export const metadata: Metadata = {
  title: 'transPEAKtation · About',
  description: 'Event-aware routing for San Francisco: the story, and the product running live.',
};

const POINTS = [
  { k: 'Sees the event coming', v: 'Concerts, games, parades and closures from PredictHQ and DataSF, mapped onto the road segments they will clog.' },
  { k: 'Forecasts the crush', v: 'Live Mapbox, TomTom and Muni traffic plus a forecast model predict each segment’s delay before the doors open.' },
  { k: 'Routes around it', v: 'Every trip gets the transPEAKtation route next to the normal ones, with a plain-language note on why it wins.' },
];

// 100 riders from A to B, three routes (top, middle, bottom). Illustrative numbers, not measured.
const ROUTES = [
  { d: 'M24 80C90 12 230 12 296 80', y: 22 },
  { d: 'M24 80H296', y: 64 },
  { d: 'M24 80C90 148 230 148 296 80', y: 150 },
];
const SPLITS = {
  alone: { title: 'Every rider for themselves', sub: 'Google Maps, Waze', riders: [0, 100, 0], mins: [22, 38, 23],
    note: 'All 100 get the same “fastest” route, and it stops being fast.' },
  crowd: { title: 'Routed together', sub: 'transPEAKtation', riders: [30, 45, 25], mins: [22, 20, 23],
    note: 'Riders are spread out, and each one arrives within a few minutes of the best case.' },
};

function Split({ kind }: { kind: keyof typeof SPLITS }) {
  const k = SPLITS[kind];
  return (
    <figure className={`split ${kind}`}>
      <figcaption><b>{k.title}</b><span className="sub">{k.sub}</span></figcaption>
      <svg viewBox="0 0 320 164" role="img" aria-label={`${k.title}: ${k.riders.map((n, i) => `${n} riders, ${k.mins[i]} min`).join('; ')}`}>
        {ROUTES.map((r, i) => (
          <g key={i}>
            <path d={r.d} className={k.riders[i] ? (kind === 'alone' ? 'jam' : 'on') : 'off'}
              style={{ strokeWidth: k.riders[i] ? 3 + k.riders[i] / 10 : 2 }} />
            <text x="160" y={r.y} className={k.riders[i] ? '' : 'faint'}>{k.riders[i] ? `${k.riders[i]} riders` : 'empty'} · {k.mins[i]} min</text>
          </g>
        ))}
        <circle cx="24" cy="80" r="9" className="end" /><text x="24" y="84" className="end-t">A</text>
        <circle cx="296" cy="80" r="9" className="end" /><text x="296" y="84" className="end-t">B</text>
      </svg>
      <p>{k.note}</p>
    </figure>
  );
}

export default function About() {
  return (
    <div className="about">
      <header className="app-bar about-bar">
        <Link href="/" className="about-home" aria-label="transPEAKtation home">
          <Logo size={32} />
          <img className="wordmark wordmark-light" src="/wordmark-light.svg" alt="" />
          <img className="wordmark wordmark-dark" src="/wordmark-dark.svg" alt="" />
          <img className="wordmark wordmark-pride" src="/wordmark-pride.svg" alt="" />
        </Link>
        <span className="grow" />
        <nav className="about-nav" aria-label="About page">
          <a href="#story">Story</a>
          <a href="#crowd">How it’s different</a>
          <a href="#live">Live app</a>
        </nav>
        <Link href="/" className="btn">Open the app</Link>
      </header>

      <main>
        <section className="about-hero">
          <p className="about-eyebrow">Event-aware routing · San Francisco</p>
          <h1>Beat the crowd <span>before</span> it forms.</h1>
          <p className="about-lead">When the fireworks end, every car wants the same fast route home.{' '}
            <b className="about-hi">transPEAKtation spreads the trips across the city before the gridlock starts.</b></p>
        </section>

        <section id="story" className="about-sec">
          <h2>The story in under a minute</h2>
          <p className="sub">A simulation of July 4 on San Francisco’s real street network: first everyone takes the fastest route,
            then <b className="about-hi">transPEAKtation routes the crowd together</b>.</p>
          <Player title="transPEAKtation demo" />
        </section>

        <section id="crowd" className="about-sec">
          <h2>It routes the crowd, not just your car.</h2>
          <p className="about-sec-lead">Map apps plan each trip on its own, so when 100 people leave the same place for the same
            destination, all 100 get the same fastest route and jam it.</p>
          <p className="about-sec-lead about-hi">transPEAKtation knows where its riders are headed, so it spreads them across
            several good routes. Nobody gets sent far out of their way, and no single street takes the whole crowd.</p>
          <div className="splits"><Split kind="alone" /><Split kind="crowd" /></div>
          <p className="sub about-note">Illustration: 100 riders from A to B. Minutes are example travel times with that many riders on each route.</p>
        </section>

        <ul className="about-points">
          {POINTS.map(p => <li key={p.k}><b>{p.k}</b><p>{p.v}</p></li>)}
        </ul>

        <section id="live" className="about-sec">
          <h2>Try it live</h2>
          <p className="sub">This is the real app, not a recording. Search a destination and compare routes.</p>
          <Framed src="/" title="transPEAKtation app" className="app" />
        </section>
      </main>

      <footer className="about-foot sub">transPEAKtation by <b>YoWayMo</b> · Built at ShellHacks 2026 · Maps: Esri, OpenStreetMap · Data: DataSF, PredictHQ, Mapbox, TomTom, 511.org</footer>
    </div>
  );
}
