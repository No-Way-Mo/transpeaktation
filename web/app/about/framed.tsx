'use client';
import { useRef } from 'react';
import { Icon } from '../parts.tsx';

/** An embedded page with a Fullscreen button (Esc exits, the browser's own control). */
export function Framed({ src, title, className }: { src: string; title: string; className: string }) {
  const box = useRef<HTMLDivElement>(null);
  return (
    <figure className={`framed ${className}`}>
      <div className="framed-box" ref={box}>
        <iframe src={src} title={title} allow="fullscreen; microphone; geolocation" />
      </div>
      <figcaption>
        <span className="sub">{title}</span>
        <span className="grow" />
        <a className="btn ghost" href={src} target="_blank" rel="noopener">Open in new tab</a>
        <button className="btn" onClick={() => box.current?.requestFullscreen()}>
          <Icon name="expand" size={16} /> Fullscreen
        </button>
      </figcaption>
    </figure>
  );
}
