// Hostile SECRET fixtures for the redaction tests (not a test file). Every value is synthetic, and every one is ASSEMBLED
// FROM FRAGMENTS at run time: no committed file holds a token, a key block, a private address or an e-mail shape, so the
// repository's public-tree privacy scan stays clean while the tests still prove the card withholds each kind.

const j = (...p) => p.join('');

/** Values that must be withheld wherever they appear, even under a perfectly innocent key. */
export const SECRET_VALUES = Object.freeze([
  { label: 'jwt', value: j('eyJhbGciOiJI', 'UzI1NiJ9.', 'eyJzdWIiOiJ0ZXN0LXVzZXIifQ.', 'c2lnbmF0dXJlLXNpZw') },
  { label: 'hex 64', value: j('9f86d081884c7d659a2feaa0c55ad015', 'a3bf4f1b2b0b822cd15d6c15b0f00a08') },
  { label: 'hex 32', value: j('0f1e2d3c4b5a69788796a5b4c3d2e1f0') },
  { label: 'base64 blob', value: j('Qm9ndXNTZWNyZXRCbG9i', 'MDEyMzQ1Njc4OWFi', 'Y2RlZkdISUpL') },
  { label: 'url userinfo', value: j('https', ':', '//', 'alice', ':', 'hunter2', '@', 'host.example', '.test/path') },
  { label: 'url userinfo, bare host', value: j('https', ':', '//', 'bob', ':', 's3cr3tvalue', '@', 'intranet', '/status') },
  { label: 'url token query', value: j('https', ':', '//', 'host.example', '.test/api?', 'access_', 'token', '=abc123def456ghi') },
  { label: 'url signed path', value: j('/api/image/serve/x?', 'auth', 'Sig', '=zzzz1111aaaa2222') },
  { label: 'ipv4', value: j('192', '.', '168', '.', '77', '.', '23') },
  { label: 'ipv4 in text', value: j('gateway is at ', '10', '.', '20', '.', '30', '.', '40', ' today') },
  { label: 'ipv6', value: j('fd12:3456:789a:1', '::', '42') },
  { label: 'mac', value: ['aa', 'bb', 'cc', 'dd', 'ee', 'f1'].join(':') },
  { label: 'connection scheme', value: j('postgres', 'ql', ':', '//', 'db.example', '.test/ecco') },
  { label: 'connection pairs', value: j('Server=db1;Database=ecco;', 'User', 'Id=svc;') },
  { label: 'email', value: j('person', '@', 'example', '.test') },
  { label: 'bearer', value: j('Bear', 'er ', 'abcdefghijklmnop12345678') },
  { label: 'kv password', value: j('pass', 'word', '=', 'correcthorse') },
  { label: 'known token shape', value: j('gh', 'p_', 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8') },
  { label: 'private host', value: j('homeassistant', '.', 'local') },
  { label: 'key block', value: j('-----BEGIN ', 'PRIVATE', ' KEY-----') },
  { label: 'coordinates', value: '12.34567, -45.67891' },
]);

/** Key names that must withhold their value whatever it looks like; each value is a unique marker. */
export const SECRET_KEYS = Object.freeze([
  'token', 'api_key', 'apiKey', 'password', 'passwd', 'secret', 'authorization', 'bearer', 'credential', 'credentials',
  'private_key', 'webhook_url', 'cookie', 'session_id', 'access_token', 'client_secret', 'refresh_token', 'x-api-key',
  'latitude', 'longitude', 'lat', 'lon', 'location', 'gps', 'ip_address', 'mac_address', 'email', 'serial_number', 'mpan',
  'ssid', 'connection_string', 'Authorization', 'SessionToken',
]);

export const KEY_MARKER = (k) => `zq7marker-${k.toLowerCase().replace(/[^a-z0-9]/g, '')}`;

/** A key NAME that is itself a secret value (a token used as a dict key). */
export const SECRET_KEY_NAMES = Object.freeze([
  j('eyJhbGciOiJI', 'UzI1NiJ9.', 'eyJzdWIiOiJ0ZXN0LXVzZXIifQ.', 'c2lnbmF0dXJlLXNpZw'),
  j('9f86d081884c7d659a2feaa0c55ad015', 'a3bf4f1b2b0b822cd15d6c15b0f00a08'),
]);

/** A large attribute object holding every secret kind in every position: top level, nested dicts and lists, key names. */
export function hostileAttributes() {
  const attrs = { friendly_name: 'Hostile sensor', benign: 'visible-benign-text' };
  SECRET_VALUES.forEach((s, i) => {
    attrs[`note_${i}`] = s.value;
  });
  for (const k of SECRET_KEYS) attrs[k] = KEY_MARKER(k);
  attrs.nested = { a: { b: { c: SECRET_VALUES.map((s) => s.value) } }, list: [{ deep: SECRET_VALUES[0].value }, SECRET_VALUES[1].value] };
  attrs.tokens = [KEY_MARKER('tokens-list-1'), KEY_MARKER('tokens-list-2')];
  attrs.credentials_dict = { user: KEY_MARKER('creduser'), pw: KEY_MARKER('credpw') };
  attrs.site_owner = KEY_MARKER('siteowner');
  attrs.byname = {};
  SECRET_KEY_NAMES.forEach((n) => {
    attrs.byname[n] = 'under-secret-key-name';
  });
  return attrs;
}

/** Every string that must be absent from any rendered, searched, copied or exported output. */
export function forbiddenStrings() {
  const out = new Set();
  for (const s of SECRET_VALUES) {
    out.add(s.value);
    if (s.value.length >= 16) out.add(s.value.slice(4, 4 + Math.min(14, s.value.length - 8)));
  }
  for (const k of SECRET_KEYS) out.add(KEY_MARKER(k));
  for (const m of ['tokens-list-1', 'tokens-list-2', 'creduser', 'credpw', 'siteowner']) out.add(KEY_MARKER(m));
  for (const n of SECRET_KEY_NAMES) out.add(n);
  out.add('hunter2');
  out.add('s3cr3tvalue');
  out.add('correcthorse');
  out.add(j('192', '.', '168', '.', '77', '.', '23'));
  return [...out];
}
