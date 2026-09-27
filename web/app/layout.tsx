import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import 'leaflet/dist/leaflet.css';
import { THEME_SCRIPT } from '@/lib/theme.ts';
import './globals.css';

// Variable Inter (every weight 100-900, so the 550 / 650 in globals.css render as written), exposed as --font-inter
// for --sans. Self-hosted by next/font at build time: the browser never calls Google.
const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const metadata: Metadata = {
  title: 'transPEAKtation · Directions',
  description: 'Event-aware routing for San Francisco.',
  appleWebApp: { capable: true, title: 'transPEAKtation', statusBarStyle: 'default' },
};
// viewportFit=cover lets the page draw under the notch; CSS pads with env(safe-area-inset-*).
export const viewport: Viewport = { width: 'device-width', initialScale: 1, viewportFit: 'cover', themeColor: [
  { media: '(prefers-color-scheme: light)', color: '#FFFFFF' },
  { media: '(prefers-color-scheme: dark)', color: '#0F2233' },
] };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // THEME_SCRIPT sets data-theme on <html> while the HTML is parsed (no light/dark flash); the DOM wins on hydration.
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
