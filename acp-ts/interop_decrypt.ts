/**
 * Interop test: Python encrypts → TS decrypts (and vice versa).
 *
 * Reads a JSON file from stdin with:
 *   { "encrypted_b64": "...", "preimage_hex": "..." }
 * Outputs:
 *   { "decrypted": "...", "ok": true } or { "ok": false, "error": "..." }
 *
 * Also can generate: outputs encrypted data for Python to decrypt.
 */

import { decryptResultB64, encryptResultB64, generatePreimage } from './src/crypto.js';
import * as crypto from 'crypto';

const mode = process.argv[2] || 'decrypt';

if (mode === 'decrypt') {
  // Read JSON from stdin
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => { input += chunk; });
  process.stdin.on('end', () => {
    try {
      const data = JSON.parse(input);
      const preimage = Buffer.from(data.preimage_hex, 'hex');
      const decrypted = decryptResultB64(data.encrypted_b64, preimage);
      console.log(JSON.stringify({
        decrypted: decrypted.toString('utf8'),
        ok: true,
      }));
    } catch (e: any) {
      console.log(JSON.stringify({ ok: false, error: e.message }));
    }
  });
} else if (mode === 'encrypt') {
  // Generate preimage, encrypt a test message, output for Python to decrypt
  const result = Buffer.from('Hello from TypeScript! Encrypted for Python to decrypt.');
  const preimage = generatePreimage();
  const enc = encryptResultB64(result, preimage);
  console.log(JSON.stringify({
    encrypted_b64: enc,
    preimage_hex: preimage.toString('hex'),
    original: result.toString('utf8'),
  }));
}