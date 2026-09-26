'use client';
import { useSyncExternalStore } from 'react';
import Desktop from './desktop.tsx';
import Mobile from './mobile.tsx';

// One URL for both layouts; the iOS app (ios/) loads this same page and gets the mobile one.
const QUERY = '(max-width: 760px)';
const subscribe = (cb: () => void) => {
  const mq = matchMedia(QUERY);
  mq.addEventListener('change', cb);
  return () => mq.removeEventListener('change', cb);
};

export default function Page() {
  const mobile = useSyncExternalStore(subscribe, () => matchMedia(QUERY).matches, () => null);
  if (mobile === null) return null; // server render: the map needs the browser anyway
  return mobile ? <Mobile /> : <Desktop />;
}
