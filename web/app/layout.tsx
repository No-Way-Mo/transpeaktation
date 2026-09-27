import type { Metadata, Viewport } from 'next';
import 'leaflet/dist/leaflet.css';
import { THEME_SCRIPT } from '@/lib/theme.ts';
import './globals.css';

export const metadata: Metadata = {
  title: 'transPEAKtation · Directions',
  description: 'Event-aware routing for San Francisco.',
  appleWebApp: { capable: true, title: 'transPEAKtation', statusBarStyle: 'default' },
};
// viewportFit=cover lets the page draw under the notch; CSS pads with env(safe-area-inset-*). maximumScale 1: iOS
// otherwise zooms the whole page on input focus / double-tap and leaves it stuck zoomed (the map has its own pinch zoom).
export const viewport: Viewport = { width: 'device-width', initialScale: 1, maximumScale: 1, viewportFit: 'cover', themeColor: [
  { media: '(prefers-color-scheme: light)', color: '#FFFFFF' },
  { media: '(prefers-color-scheme: dark)', color: '#0F2233' },
] };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // THEME_SCRIPT sets data-theme on <html> while the HTML is parsed (no light/dark flash); the DOM wins on hydration.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
