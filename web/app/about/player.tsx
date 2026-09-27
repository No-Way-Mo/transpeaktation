'use client';
import { useEffect, useRef, useState } from 'react';
import { Icon } from '../parts.tsx';

// The demo (../demo/index.html) as a video: poster frame + play button, then play/pause, a scrub bar and fullscreen.
// It is a live canvas animation, not a video file, so this drives the `window.player` hooks it exposes (same origin).
type Demo = { total: number; t: number; paused: boolean; play(): void; pause(): void; seek(t: number): void };
const POSTER = 57; // the end card: logo, "by YoWayMo", tagline
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function Player({ title }: { title: string }) {
  const box = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const [started, setStarted] = useState(false);
  const [s, setS] = useState({ t: 0, total: 60, paused: true, ready: false });
  const demo = () => (frame.current?.contentWindow as (Window & { player?: Demo }) | null)?.player;

  // Mirror the demo's clock (it also pauses itself on Space and stops at the end).
  useEffect(() => {
    const id = setInterval(() => {
      const d = demo();
      if (d) setS({ t: d.t, total: d.total, paused: d.paused, ready: true });
    }, 200);
    return () => clearInterval(id);
  }, []);

  const toggle = () => {
    const d = demo();
    if (!d) return;
    if (!started) { setStarted(true); d.seek(0); d.play(); }
    else if (d.paused) d.play();
    else d.pause();
  };
  const scrub = (t: number) => {
    const d = demo();
    if (!d) return;
    const playing = started && !d.paused;
    setStarted(true);
    d.seek(t);
    if (playing) d.play();
  };
  const playing = started && !s.paused;

  return (
    <figure className="framed wide">
      <div className={`framed-box player${started ? '' : ' poster'}${playing ? ' playing' : ''}`} ref={box}>
        <iframe ref={frame} src={`/demo/index.html?t=${POSTER}&paused`} title={title} tabIndex={-1} />
        <button className="player-hit" onClick={toggle} disabled={!s.ready} aria-label={playing ? 'Pause' : 'Play'}>
          {!playing && <span className="player-big"><Icon name="play" size={34} /></span>}
        </button>
        <div className="player-bar">
          <button className="player-btn" onClick={toggle} disabled={!s.ready} aria-label={playing ? 'Pause' : 'Play'}>
            <Icon name={playing ? 'pause' : 'play'} size={18} />
          </button>
          <input type="range" className="player-seek" min={0} max={s.total} step={0.1} aria-label="Seek"
            value={started ? s.t : 0} disabled={!s.ready} onChange={e => scrub(+e.target.value)}
            style={{ '--p': `${((started ? s.t : 0) / s.total) * 100}%` } as React.CSSProperties} />
          <span className="player-time">{clock(started ? s.t : 0)} / {clock(s.total)}</span>
          <button className="player-btn" aria-label="Fullscreen"
            onClick={() => document.fullscreenElement ? document.exitFullscreen() : box.current?.requestFullscreen()}>
            <Icon name="expand" size={18} />
          </button>
        </div>
      </div>
    </figure>
  );
}
