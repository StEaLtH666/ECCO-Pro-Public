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
  // ---- review round 1: edge shapes (every one is assembled from fragments, so no committed file holds a secret-shaped text)
  { label: 'json credential pair (double quotes)', value: j('{"to', 'ken":"abc', '123def"}') },
  { label: 'python credential pair (single quotes)', value: j("{'api_", "key': 'abc", "123def'}") },
  { label: 'coordinates separated by words', value: j('lat ', '51.5074', ' lon ', '-0.1278') },
  { label: 'latitude word and one number', value: j('latitude: ', '51.5074') },
  { label: 'jwt split by a zero-width character', value: j('eyJhbGciOiJI', '\u200b', 'UzI1NiJ9.', 'eyJzdWIiOiJ0ZXN0LXVzZXIifQ.', 'c2lnbmF0dXJlLXNpZw') },
  { label: 'password split by a zero-width character', value: j('pass', '\u200b', 'word', '=', 'correcthorse') },
  { label: 'password with a homoglyph letter', value: j('p', '\u0430', 'ssword', '=', 'correcthorse') },
  { label: 'token with a Greek omicron', value: j('t', '\u03bf', 'ken', ': ', 'abc123def456') },
  { label: 'internal host name without a suffix', value: j('ws', ':', '//', 'homeassistant', ':', '8123', '/api/websocket') },
  { label: 'internal host name, bare', value: j('http', ':', '//', 'nas', '/share') },
  { label: 'coordinates with hemisphere letters', value: j('home ', '52.1', ' N ', '0.12', ' W') },
  // ---- review round 2: a webhook (the id in the path is the credential) in its three shapes, each assembled from fragments
  { label: 'webhook url', value: j('https', ':', '//', 'hooks.example', '.test/api/', 'web', 'hook/', 'abcdef123456') },
  { label: 'webhook path alone', value: j('/api/', 'web', 'hook/', 'q1w2e3r4t5y6') },
  { label: 'chat services webhook path', value: j('hooks.example', '.test/', 'services/', 'team-alpha/chan-beta/abcdefghijkl') },
]);

/**
 * Review round 3: the shapes the round-three reviewer found shown. They are kept in their own list (not appended to SECRET_VALUES) so that the
 * round-one and round-two tests, which address SECRET_VALUES by position, keep reading exactly the values they read. hostileAttributes() and
 * forbiddenStrings() carry them, so every end-to-end hostile test covers them too.
 */
export const SECRET_VALUES_R3 = Object.freeze([
  { label: 'MAC address with no separator', value: j('aabb', 'ccdd', 'eeff') },
  { label: 'MAC address with no separator, upper case', value: j('A1B2', 'C3D4', 'E5F6') },
  { label: 'MAC address, dotted (three groups of four)', value: j('aabb', '.', 'ccdd', '.', 'eeff') },
  { label: 'coordinate pair with three decimals', value: j('51.507', ', ', '-0.127') },
  { label: 'coordinate pair with three decimals, semicolon', value: j('-33.865', ';', '151.209') },
  { label: 'Wi-Fi QR text', value: j('WIFI', ':S:', 'Home', ';T:WPA;P:', 'hunter22', ';;') },
  { label: 'Wi-Fi QR text, lower case', value: j('wifi', ':T:WPA;S:', 'Home', ';P:', 'hunter22', ';;') },
  { label: 'JSON pair with a pass key', value: j('{"pa', 'ss": "hun', 'ter22"}') },
  { label: 'JSON pair with a pw key (single quotes)', value: j("{'p", "w': 'hun", "ter22'}") },
  { label: 'pass equals value', value: j('pa', 'ss=hun', 'ter22x') },
  { label: 'qualified pass equals value', value: j('wifi_pa', 'ss=hun', 'ter22x') },
  { label: 'pw equals value, quoted', value: j('db-p', 'w="hun', 'ter22x"') },
]);

/**
 * Review round 4: a MAC address written with spaces between the six bytes (the shape a reviewer's probe found shown). Its own list for the same reason as
 * SECRET_VALUES_R3: the older tests address the earlier lists by position. hostileAttributes() and forbiddenStrings() carry it.
 */
export const SECRET_VALUES_R4 = Object.freeze([
  { label: 'MAC address with spaces, upper case', value: j('AA BB', ' CC DD', ' EE FF') },
  { label: 'MAC address with spaces, lower case', value: j('a1 b2 ', 'c3 d4 ', 'e5 f6') },
  { label: 'MAC address with spaces inside a sentence', value: j('seen on aa 1b cc ', 'dd e5 07', ' today') },
]);

/** Key names that must withhold their value whatever it looks like; each value is a unique marker. */
export const SECRET_KEYS = Object.freeze([
  'token', 'api_key', 'apiKey', 'password', 'passwd', 'secret', 'authorization', 'bearer', 'credential', 'credentials',
  'private_key', 'webhook_url', 'cookie', 'session_id', 'access_token', 'client_secret', 'refresh_token', 'x-api-key',
  'latitude', 'longitude', 'lat', 'lon', 'location', 'gps', 'ip_address', 'mac_address', 'email', 'serial_number', 'mpan',
  'ssid', 'connection_string', 'Authorization', 'SessionToken',
  // ---- review round 1: a qualifier plus a key word, and short values
  'encryption_key', 'ssh_key', 'wifi_key', 'license_key', 'pin', 'psk', 'encryptionKey', 'wifi-psk', 'pin_code',
  // ---- review round 2: a login name after a qualifier
  'mqtt_user', 'db_login', 'serviceUser', 'ha-login', 'sftp_users',
]);

/** Review round 3: a short password word after a qualifier ("pass"), "pw" anywhere, and the compact forms. Kept apart from SECRET_KEYS for the same reason. */
export const SECRET_KEYS_R3 = Object.freeze(['wifi_pass', 'mqttPass', 'db-pw', 'pw', 'wifipass', 'wifipw', 'ADMIN_PASS', 'svc_pw_hash']);

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
  SECRET_VALUES_R3.forEach((s, i) => {
    attrs[`note_r3_${i}`] = s.value;
  });
  for (const k of SECRET_KEYS_R3) attrs[k] = KEY_MARKER(k);
  SECRET_VALUES_R4.forEach((s, i) => {
    attrs[`note_r4_${i}`] = s.value;
  });
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
  for (const s of SECRET_VALUES_R3) out.add(s.value);
  for (const s of SECRET_VALUES_R4) out.add(s.value);
  for (const k of SECRET_KEYS_R3) out.add(KEY_MARKER(k));
  for (const m of ['tokens-list-1', 'tokens-list-2', 'creduser', 'credpw', 'siteowner']) out.add(KEY_MARKER(m));
  for (const n of SECRET_KEY_NAMES) out.add(n);
  out.add('hunter2');
  out.add('hunter22');
  out.add('s3cr3tvalue');
  out.add('correcthorse');
  out.add(j('192', '.', '168', '.', '77', '.', '23'));
  return [...out];
}

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 5: the same kinds of secret, hidden DEEP inside a long string. A redactor that reads only the start of a long text (the first 64, 300 or 1000
// characters) or only its end passes every short test, because every hostile value above sits at the start of its string. Each kind below is therefore
// placed at four offsets of a string that stays within the card's 4000-character cap (the longest string it keeps whole), and every end-to-end test runs them
// all: row, raw view, search index, copy and export. Every value is assembled from fragments, like the ones above.
// ---------------------------------------------------------------------------------------------------------------------------
export const POSITION_CAP = 4000;

/** The innocent text around a secret: no digit, no address, no key: nothing any redaction rule takes for a secret. */
export const FILLER = 'The planner checked the overnight window and the tariff boundary before it chose, and the details follow here. ';

/** `n` characters of filler (never more, never less). */
export const filler = (n) => (n <= 0 ? '' : FILLER.repeat(Math.ceil(n / FILLER.length)).slice(0, n));

/** The eight kinds named by the owner's review: each has a probe, a stretch of the secret that must never be seen anywhere. */
export const POSITIONED_KINDS = Object.freeze([
  { label: 'jwt', value: j('eyJhbGciOiJI', 'UzI1NiJ9.', 'eyJzdWIiOiJwb3NpdGlvbmVkIn0.', 'cG9zaXRpb25lZHNpZw'), probe: j('eyJzdWIiOiJwb3Np') },
  { label: 'ipv4', value: j('172', '.', '16', '.', '88', '.', '41'), probe: j('172', '.', '16', '.', '88') },
  { label: 'password pair', value: j('pass', 'word', '=', 'plumbus4242'), probe: j('plumbus', '4242') },
  { label: 'mac', value: ['de', 'ad', 'be', 'ef', '00', '1c'].join(':'), probe: ['ad', 'be', 'ef', '00'].join(':') },
  { label: 'email', value: j('someone', '@', 'example', '.test'), probe: j('someone', '@', 'exam') },
  { label: 'bearer token', value: j('Bear', 'er ', 'zyxwvutsrqponmlk98765432'), probe: j('zyxwvutsrqpo', 'nmlk') },
  { label: 'long hex blob', value: j('b3a1c0de5eed4bad', 'f00d1e57ab1e0dd5', 'a11ceb00c1e5ba5e', 'd00dfeedc0ffee42'), probe: j('f00d1e57', 'ab1e0dd5') },
  { label: 'url with userinfo', value: j('https', ':', '//', 'carol', ':', 'plumbus', '4242', '@', 'host.example', '.test/x'), probe: j('carol', ':', 'plumbus') },
]);

/** Two kinds that are short enough to START at offset 3990 and still end within the cap (10 characters or fewer). */
export const SHORT_KINDS = Object.freeze([
  { label: 'ipv4 (short)', value: j('10', '.', '20', '.', '30', '.', '4'), probe: j('10', '.', '20', '.', '30') },
  { label: 'email (short)', value: j('me', '@', 'x', '.org'), probe: j('me', '@', 'x.') },
]);

/**
 * `value` set into a string of filler at the offsets of the review: it STARTS at 100 and at 1500, ENDS at 3990 and at 4000 (so the longest text the card keeps
 * whole carries it in its last characters), and, when it is short enough to fit, STARTS at 3990. A space before and after it (the end of the string for the last
 * one) keeps every word-boundary rule of the card honest. Every text is at most POSITION_CAP characters, so none of them is cut before it is read.
 */
export function placements(value) {
  const make = (label, start, total) => {
    const head = `${filler(start - 1)} `;
    const rest = total - start - value.length;
    const text = rest > 0 ? `${head}${value} ${filler(rest - 1)}` : `${head}${value}`;
    if (text.length !== total || text.slice(start, start + value.length) !== value) throw new Error(`placement ${label} is wrong`);
    return { label, text, start, end: start + value.length };
  };
  const out = [make('starts at offset 100', 100, 3999), make('starts at offset 1500', 1500, 3999), make('ends at offset 3990', 3990 - value.length, 3999),
    make('ends at offset 4000', POSITION_CAP - value.length, POSITION_CAP)];
  if (value.length <= 10) out.push(make('starts at offset 3990', 3990, POSITION_CAP));
  return out;
}

/** Every kind at every offset: [{ id, label, text, probe }], `id` a safe suffix for an entity id. */
export function positionedCases() {
  const out = [];
  [...POSITIONED_KINDS, ...SHORT_KINDS].forEach((k, ki) => {
    placements(k.value).forEach((p, pi) => out.push({ id: `${ki}_${pi}`, label: `${k.label}, ${p.label}`, text: p.text, probe: k.probe, kind: k.label, start: p.start, end: p.end }));
  });
  return out;
}

/** The control: the same length and the same offsets, with a harmless marker word where a secret would be. It is shown whole, so a search for a marker finds it at every offset. */
export const BENIGN_MARKERS = Object.freeze(['zqmarkerhundred', 'zqmarkerfifteen', 'zqmarkernearend', 'zqmarkerattheend']);
export function benignControl() {
  let t = filler(POSITION_CAP);
  const at = (marker, start) => {
    t = `${t.slice(0, start)}${marker}${t.slice(start + marker.length)}`;
  };
  at(BENIGN_MARKERS[0], 100);
  at(BENIGN_MARKERS[1], 1500);
  at(BENIGN_MARKERS[2], 3950);
  at(BENIGN_MARKERS[3], POSITION_CAP - BENIGN_MARKERS[3].length);
  return t;
}

/** A string over the cap whose only secret lies wholly beyond it: the card drops everything past the cap before it reads, and says so. */
export function beyondCap(value) {
  const text = `${filler(4099)} ${value} ${filler(150)}`;
  return { text, probe: value };
}

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 6: the SWEEP. Round 5 placed each kind at four offsets and the round-6 reviewer showed that four offsets are an instance, not the class: a reader that skips the first
// character of a long text (S01), reads the last 3999 characters (S02), or reads the text in chunks of 500 or 1000 characters with no overlap (S06, S07) passes all four. The class is "the
// card reads every character of a string, whatever the scan looks like", so the fixtures below put every kind at EVERY offset that matters (and the others at a stride), in carriers of
// every length that matters, and the tests run them on every path. A prefix, suffix, window, chunk, per-line, split-at-space or off-by-one reader fails at least one of them.
// ---------------------------------------------------------------------------------------------------------------------------

/** Carrier lengths: 1500 (the reviewer's), 3999 and 4000 (just under and at the display cap), 4500 (over it: the text is cut for display, and the secret may cross the cut), 12000 and 20000 (the hard bound of what is read). */
export const SWEEP_CARRIERS = Object.freeze([1500, 3999, 4000, 4500]);
export const SWEEP_LONG_CARRIERS = Object.freeze([12000, 20000]);

/** Offsets at which a naive window or chunk would end or begin: the powers of two near the buffer sizes people use, the round numbers of the reviewer's chunks, the display cap and its neighbours. */
export const SWEEP_BOUNDARIES = Object.freeze([0, 1, 2, 255, 256, 257, 499, 500, 501, 511, 512, 513, 999, 1000, 1001, 1023, 1024, 1025, 2047, 2048, 2049, 3990, 3999, 4000, 4001]);

/** Two kinds that a per-line reader or a split-at-spaces reader misses: the secret itself holds a newline, or spaces, between its words. */
export const SPLIT_KINDS = Object.freeze([
  { label: 'password pair across a newline', value: j('pass', 'word', '=\n', 'plumbus4242'), probe: j('plumbus', '4242') },
  { label: 'password pair with spaces around the equals sign', value: j('pass', 'word', ' = ', 'plumbus4242'), probe: j('plumbus', '4242') },
]);

/** Every kind of the sweep: the eight of round 5, its two short ones, and the two split ones. */
export const SWEEP_KINDS = Object.freeze([...POSITIONED_KINDS, ...SHORT_KINDS, ...SPLIT_KINDS]);

/** A kind of 24 characters or fewer is "short": it is swept at EVERY offset (stride one), the others at the boundaries and a stride of 37. */
export const isShortKind = (k) => k.value.length <= 24;

/** A text of exactly `total` characters: filler, then `value` starting at exactly `start`, then filler. A space sits on each side of the secret when there is room, so no word-boundary rule is helped or hindered. */
export function carrier(value, start, total) {
  const end = start + value.length;
  if (!(start >= 0 && end <= total)) throw new Error(`a carrier of ${total} cannot hold ${value.length} characters at ${start}`);
  const head = start > 0 ? `${filler(start - 1)} ` : '';
  const tail = total - end > 0 ? ` ${filler(total - end - 1)}` : '';
  const text = `${head}${value}${tail}`;
  if (text.length !== total || text.slice(start, end) !== value) throw new Error(`carrier(${start}, ${total}) is wrong`);
  return text;
}

/**
 * The start offsets of one kind in one carrier. dense: every offset. Otherwise: every start at which the secret ends before, ends at, crosses, begins at or begins after each boundary (three
 * either side), a stride of 37 across the whole carrier, and the last four starts that fit (the secret ends at the end of the text).
 */
export function sweepStarts(valueLength, total, { dense = false, stride = 37 } = {}) {
  const maxStart = total - valueLength;
  const out = new Set();
  if (dense) for (let s = 0; s <= maxStart; s += 1) out.add(s);
  else {
    for (let s = 0; s <= maxStart; s += stride) out.add(s);
    for (const b of SWEEP_BOUNDARIES) for (let s = b - valueLength - 3; s <= b + 3; s += 1) out.add(s);
    for (let s = maxStart - 3; s <= maxStart; s += 1) out.add(s);
  }
  return [...out].filter((s) => s >= 0 && s <= maxStart).sort((a, b) => a - b);
}

/** A reduced set for the paths that build whole rows (a snapshot, a DOM): at each of a few boundaries, the starts at which the secret ends just before, ends at, crosses and begins at it, plus both ends. */
export function pathStarts(valueLength, total, bounds = [0, 256, 500, 1000, 1024, 2048, 3990, 4000]) {
  const maxStart = total - valueLength;
  const out = new Set([0, 1, maxStart - 1, maxStart]);
  for (const b of bounds) for (const s of [b - valueLength - 1, b - valueLength, b - Math.ceil(valueLength / 2), b - 1, b, b + 1]) out.add(s);
  return [...out].filter((s) => s >= 0 && s <= maxStart).sort((a, b) => a - b);
}

/** Every swept case of the given carriers, one at a time (a generator: the dense sweep is over a hundred thousand texts of several thousand characters): { kind, label, text, probe, value, start, total, id }. `pick` chooses the starts of a kind in a carrier. */
export function* sweepCases(carriers, pick) {
  for (let ki = 0; ki < SWEEP_KINDS.length; ki += 1) {
    const k = SWEEP_KINDS[ki];
    for (const total of carriers) {
      for (const start of pick(k, total)) yield { id: `${ki}_${total}_${start}`, kind: k.label, label: `${k.label}, in ${total} characters, at offset ${start}`, text: carrier(k.value, start, total), probe: k.probe, value: k.value, start, total };
    }
  }
}

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 7: the LONG kinds. The round-6 sweep put twelve SHORT kinds (the longest is 74 characters) at every offset, so a reader that scans overlapping chunks passed it whenever its overlap was longer
// than the longest kind: mutants N31, N32 and N33 read a string in chunks of 3000, 1024 and 4000 characters that overlap by 200, 128 and 400, and a secret of up to 74 characters always lay whole inside one
// of them. The class is "a secret that is only recognised WHOLE, and is longer than any overlap a chunked reader would leave". The kinds below are such secrets: only one rule recognises each, and only when it
// sees the whole text, because every cut of it (a head, a tail, a piece) holds nothing any other rule takes for a secret. They are swept at a stride below their length, in carriers of 4500, 12000 and 20000
// characters, so every chunk edge and every step size of every window is crossed by some start. Every value is assembled from fragments, as above.
// ---------------------------------------------------------------------------------------------------------------------------
export const LONG_PASSWORD_LENGTHS = Object.freeze([150, 300, 600, 1200, 3000]);
export const LONG_CONNECTION_LENGTHS = Object.freeze([400, 3000]);
export const LONG_CARRIERS = Object.freeze([4500, 12000, 20000]);

/** `n` characters of a password that no rule reads as a secret on its own: letters, a digit and an exclamation mark (a run of letters and digits is never longer than three), ending in the exclamation mark (so that, in a URL, what stands before the at sign is not an e-mail local part). */
export const longPassword = (n) => `${'Ab1!'.repeat(Math.ceil(n / 4)).slice(0, n - 1)}!`;

export const LONG_KINDS = Object.freeze([
  ...LONG_PASSWORD_LENGTHS.map((n) => ({ label: `url with a ${n}-character password`, rule: 'url credentials', value: j('https', ':', '//', 'dana', ':', longPassword(n), '@', 'host.example', '.test/x'), probe: longPassword(32).slice(0, 28) })),
  ...LONG_CONNECTION_LENGTHS.map((n) => ({ label: `connection pairs with a ${n}-character value`, rule: 'connection pairs', value: j('Server', '=', longPassword(n), ';'), probe: longPassword(32).slice(0, 28) })),
]);

/** The stride of the long sweep for a kind: a twelfth of its length, never less than 7, so that the starts hit every window a chunked reader could leave a secret of that length straddling (the width of such a window is the secret's length less the reader's overlap). */
export const longStride = (len) => Math.max(7, Math.floor(len / 12));

/** Every start of a long kind in a carrier: every `longStride` characters from 0, and the last four that fit. */
export function longStarts(len, total) {
  const maxStart = total - len;
  const out = new Set();
  for (let s = 0; s <= maxStart; s += longStride(len)) out.add(s);
  for (let s = maxStart - 3; s <= maxStart; s += 1) out.add(s);
  return [...out].filter((s) => s >= 0 && s <= maxStart).sort((a, b) => a - b);
}

/** Every swept case of the long kinds, one at a time: { kind, label, text, probe, value, start, total, id }. */
export function* longCases(carriers = LONG_CARRIERS, pick = longStarts) {
  for (let ki = 0; ki < LONG_KINDS.length; ki += 1) {
    const k = LONG_KINDS[ki];
    for (const total of carriers) {
      for (const start of pick(k.value.length, total)) yield { id: `l${ki}_${total}_${start}`, kind: k.label, label: `${k.label}, in ${total} characters, at offset ${start}`, text: carrier(k.value, start, total), probe: k.probe, value: k.value, start, total };
    }
  }
}
