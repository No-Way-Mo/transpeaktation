// The rider's Solana address for route rewards. Receiving needs only the address, so nothing is signed:
// Phantom (browser extension / in-app browser) fills it in, or the rider pastes one (e.g. in the iOS app).
// Plain TS so `node --test` can run it.

const KEY = 'tp-wallet';
// base58 (no 0, O, I, l); a 32-byte public key is 32-44 characters
const ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

export const isSolanaAddress = (s: string) => ADDRESS.test(s.trim());
/** "7xKX…gAsU" */
export const shortAddress = (s: string) => s.length > 10 ? `${s.slice(0, 4)}…${s.slice(-4)}` : s;

type Phantom = { isPhantom?: boolean; connect(): Promise<{ publicKey: { toString(): string } }> };
const phantom = (): Phantom | undefined => {
  const w = globalThis as { phantom?: { solana?: Phantom }; solana?: Phantom };
  const p = w.phantom?.solana ?? w.solana;
  return p?.isPhantom ? p : undefined;
};
export const hasPhantom = () => !!phantom();

/** Ask Phantom for the rider's address (it shows its own approve prompt). */
export async function connectPhantom(): Promise<string> {
  const p = phantom();
  if (!p) throw new Error('Phantom not found');
  return (await p.connect()).publicKey.toString();
}

/** The last address used on this device, so a rider doesn't paste it every trip. Storage may be blocked: ignore. */
export function savedWallet(): string {
  try { const v = localStorage.getItem(KEY) ?? ''; return isSolanaAddress(v) ? v : ''; } catch { return ''; }
}
export function saveWallet(v: string) {
  try { localStorage.setItem(KEY, v); } catch { /* private mode: just don't remember */ }
}
