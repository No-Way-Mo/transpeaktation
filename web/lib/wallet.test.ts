import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hasPhantom, isSolanaAddress, savedWallet, shortAddress } from './wallet.ts';

test('accepts base58 Solana addresses only', () => {
  assert.ok(isSolanaAddress('7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU'));
  assert.ok(isSolanaAddress(' 11111111111111111111111111111111 '));
  assert.ok(!isSolanaAddress('0x52908400098527886E0F7030069857D2E4169EE7')); // Ethereum
  assert.ok(!isSolanaAddress('7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAs0'));  // 0 isn't base58
  assert.ok(!isSolanaAddress('short'));
});

test('short form and no Phantom / storage outside a browser', () => {
  assert.equal(shortAddress('7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU'), '7xKX…gAsU');
  assert.equal(hasPhantom(), false);
  assert.equal(savedWallet(), '');
});
