import type { Metadata, Viewport } from 'next';
import { Instrument_Sans } from 'next/font/google';
import 'leaflet/dist/leaflet.css';
import './globals.css';

const sans = Instrument_Sans({ subsets: ['latin'], variable: '--font-sans' });

export const metadata: Metadata = {
  title: 'transPEAKtation · Directions',
  description: 'Event-aware routing for San Francisco.',
  appleWebApp: { capable: true, title: 'transPEAKtation', statusBarStyle: 'black-translucent' },
};
// viewportFit=cover lets the page draw under the notch; CSS pads with env(safe-area-inset-*).
export const viewport: Viewport = { width: 'device-width', initialScale: 1, viewportFit: 'cover', themeColor: '#060C17' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable}>
      <body>{children}</body>
    </html>
  );
}
