/**
 * ACP Crypto — Atomic delivery primitives.
 *
 * preimage = decryption key.
 * - Generate random preimage K (32 bytes)
 * - hash H = SHA256(K) — goes into Lightning hold invoice
 * - Result encrypted with AES-256-CBC, key = K
 * - Consumer pays → provider settles → K revealed → consumer decrypts
 */

import crypto from 'crypto';

export function generatePreimage(): Buffer {
  return crypto.randomBytes(32);
}

export function hashPreimage(preimage: Buffer): Buffer {
  return crypto.createHash('sha256').update(preimage).digest();
}

/**
 * Encrypt result with AES-256-CBC using preimage as key.
 * Returns IV (16 bytes) + ciphertext.
 */
export function encryptResult(result: Buffer, preimage: Buffer): Buffer {
  const key = preimage; // 32 bytes = AES-256
  const iv = crypto.createHash('sha256').update(Buffer.concat([preimage, Buffer.from('iv')])).digest().slice(0, 16);

  const cipher = crypto.createCipheriv('aes-256-cbc', key, iv);
  const encrypted = Buffer.concat([cipher.update(result), cipher.final()]);

  return Buffer.concat([iv, encrypted]);
}

/**
 * Decrypt result with AES-256-CBC using preimage as key.
 * Input: IV (first 16 bytes) + ciphertext.
 */
export function decryptResult(encrypted: Buffer, preimage: Buffer): Buffer {
  const key = preimage;
  const iv = encrypted.slice(0, 16);
  const ct = encrypted.slice(16);

  const decipher = crypto.createDecipheriv('aes-256-cbc', key, iv);
  return Buffer.concat([decipher.update(ct), decipher.final()]);
}

/** Encrypt and return as base64 string (for Nostr event tag). */
export function encryptResultB64(result: Buffer, preimage: Buffer): string {
  return encryptResult(result, preimage).toString('base64');
}

/** Decrypt base64-encoded encrypted result. */
export function decryptResultB64(encryptedB64: string, preimage: Buffer): Buffer {
  return decryptResult(Buffer.from(encryptedB64, 'base64'), preimage);
}

/** Verify that SHA256(preimage) == expectedHash. */
export function verifyPreimage(preimage: Buffer, expectedHash: Buffer): boolean {
  return hashPreimage(preimage).equals(expectedHash);
}

/** Verify receipt preimage matches offer's preimage_hash. */
export function verifyReceipt(offerPreimageHash: Buffer, receiptPreimage: Buffer): boolean {
  return hashPreimage(receiptPreimage).equals(offerPreimageHash);
}