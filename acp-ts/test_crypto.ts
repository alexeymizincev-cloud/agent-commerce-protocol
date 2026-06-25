import { AgentIdentity } from './src/identity.js';
import { generatePreimage, hashPreimage, encryptResultB64, decryptResultB64, verifyPreimage } from './src/crypto.js';

const a = AgentIdentity.generate();
console.log('Identity:', a.toString());

const K = generatePreimage();
const H = hashPreimage(K);
console.log('Preimage:', K.toString('hex').slice(0, 32) + '...');
console.log('Hash:    ', H.toString('hex').slice(0, 32) + '...');

const result = Buffer.from('Hello from TypeScript!');
const enc = encryptResultB64(result, K);
const dec = decryptResultB64(enc, K);
console.log('Original: ', result.toString());
console.log('Decrypted:', dec.toString());
console.log('Match:', result.equals(dec));
console.log('Verify:', verifyPreimage(K, H));
console.log('TS crypto OK');
