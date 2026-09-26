import type { Metadata, Viewport } from 'next';
import 'leaflet/dist/leaflet.css';
import './globals.css';

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
