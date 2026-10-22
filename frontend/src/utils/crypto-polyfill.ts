const browserCrypto = globalThis.crypto;

if (
  browserCrypto &&
  typeof browserCrypto.randomUUID !== 'function' &&
  typeof browserCrypto.getRandomValues === 'function'
) {
  Object.defineProperty(browserCrypto, 'randomUUID', {
    configurable: true,
    writable: true,
    value: (): `${string}-${string}-${string}-${string}-${string}` => {
      const bytes = new Uint8Array(16);
      browserCrypto.getRandomValues(bytes);

      // Set the UUID v4 version and variant bits.
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;

      const hex = Array.from(
        bytes,
        byte => byte.toString(16).padStart(2, '0'),
      ).join('');

      return [
        hex.slice(0, 8),
        hex.slice(8, 12),
        hex.slice(12, 16),
        hex.slice(16, 20),
        hex.slice(20),
      ].join('-') as `${string}-${string}-${string}-${string}-${string}`;
    },
  });
}
