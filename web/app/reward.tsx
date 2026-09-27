'use client';
import { useState } from 'react';
import type { useRoutePlanner } from '@/lib/use-route-planner.ts';
import { connectPhantom, hasPhantom, isSolanaAddress, savedWallet, shortAddress } from '@/lib/wallet.ts';

type Planner = ReturnType<typeof useRoutePlanner>;

export const solText = (n: number) => `${+n.toFixed(4)} SOL`;

/** After arriving on the transPEAKtation route: claim its reward to a wallet (paid right away), then what happened.
 *  The route list shows only the amount (a tag on the transPEAKtation card). */
export function RewardPanel({ p }: { p: Planner }) {
  const offer = p.rewardOffer, r = p.reward;
  const [wallet, setWallet] = useState(savedWallet);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!offer) return null;

  const claim = async (address: string) => {
    setBusy(true); setError('');
    try { await p.claim(address); } catch (e) { setError(e instanceof Error ? e.message : 'Couldn’t claim the reward.'); }
    setBusy(false);
  };
  const phantom = async () => {
    try { await claim(await connectPhantom()); } catch { setError('Phantom didn’t connect.'); }
  };

  if (r) {
    return (
      <div className={`reward ${r.status}`} role="status">
        {r.status === 'paid' && (
          <span>Paid <b>{solText(r.sol)}</b> to {shortAddress(r.wallet)}. Thanks for riding with transPEAKtation.{' '}
            {r.explorer && <a href={r.explorer} target="_blank" rel="noreferrer">View on Solana Explorer</a>}</span>
        )}
        {r.status === 'too_soon' && <span>No reward: the trip ended too soon after you left.</span>}
        {r.status === 'failed' && <span>The payout didn’t go through this time.</span>}
      </div>
    );
  }

  return (
    <div className="reward">
      <span className="reward-head"><b>You earned {solText(offer.sol)}</b><span className="sub">devnet</span></span>
      <span className="reward-why">Trip complete on the transPEAKtation route. Where should we send it?</span>
      {hasPhantom() && <button className="pill-btn" disabled={busy} onClick={phantom}>Send to Phantom</button>}
      <form className="reward-form" onSubmit={e => { e.preventDefault(); claim(wallet); }}>
        <input aria-label="Solana wallet address" placeholder="Solana wallet address" value={wallet} spellCheck={false}
          autoCapitalize="off" autoCorrect="off" onChange={e => { setWallet(e.target.value); setError(''); }} />
        <button className="pill-btn" disabled={busy || !isSolanaAddress(wallet)}>{busy ? 'Sending…' : 'Claim'}</button>
      </form>
      {error && <span className="reward-error" role="alert">{error}</span>}
      <span className="sub">Your address is saved with this trip only to pay you, and payments are public on Solana.</span>
    </div>
  );
}
