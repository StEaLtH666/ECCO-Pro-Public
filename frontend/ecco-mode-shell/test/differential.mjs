// The corpus of the DIFFERENTIAL gate (review round 8; not a test file). The gate is test/differential.test.mjs: whatever the frozen round-6 rules (reference-r6.mjs) withhold, the card must still withhold.
//
// The reviewer of round 8 found the class: a rule bounded to make it linear (round 7) stops looking when a COMPONENT of the secret is longer than its bound, and the secret is shown. So the corpus is
// built by component: every family below is one kind of secret with ONE component whose length is the parameter n. Each family is generated at every length from 1 to 300 and then at 400, 600 and 1000
// (DENSE), and at the lengths that sit on either side of every bound a rule ever had (SPARSE: 63 to 66, 252 to 258, 511 to 514, 4095 to 4098 and so on), and each text is placed at the start, in the middle and
// at the end of prose, with prose of 160 characters (DENSE) and of 4000 characters (SPARSE), and with no prose at all.
//
// The fillers are chosen so that no OTHER rule can read the filler as a secret (a hex run or an encoded run would withhold the text whatever the rule under test does, and hide a regression): W() is letters from
// g to z only (no hex digit, no digit, no capital). A family that needs digits or capitals (a hex blob, an encoded value, a coordinate) says so, and its own rule is the one that reads them.
//
// Every secret-shaped text is assembled from fragments at run time (the folder scan of static.test.mjs and the privacy scan of tools/tests/test_geek_mode_privacy.py read the committed files).
import { filler } from './secrets.mjs';

const j = (...p) => p.join('');
const LETTERS = 'ghijklmnopqrstuvwxyz';
const cycle = (alphabet, n) => (n <= 0 ? '' : alphabet.repeat(Math.ceil(n / alphabet.length)).slice(0, n));
/** n letters from g to z. */
export const W = (n) => cycle(LETTERS, n);
/** A name of n characters: letters, with a hyphen, a dot, an underscore or a percent sign at every seventh place (never first or last), as a URL parameter name or a host label can have. */
const MARKS = '-._%';
export const NAME = (n) => {
  let s = '';
  for (let i = 0; i < n; i += 1) s += i % 7 === 6 && i !== n - 1 ? MARKS[Math.floor(i / 7) % 4] : LETTERS[i % 20];
  return s;
};
/** A segment of a token: letters with a hyphen or an underscore at every ninth place (never first or last). */
const SEG = (n) => {
  let s = '';
  for (let i = 0; i < n; i += 1) s += i % 9 === 8 && i !== n - 1 ? '-_'[Math.floor(i / 9) % 2] : LETTERS[i % 20];
  return s;
};
const DIGITS = (n, d = '5') => d.repeat(Math.max(0, n));
const ALNUM = (n) => cycle('Ab3dEf9hIj2lMn7pQr4tUv8xYz0', n);
const HEXRUN = (n) => cycle('0123456789abcdef', n);

const KEYWORDS = ['token', 'secret', 'passw', 'pwd', 'apikey', 'api_key', 'api-key', 'auth', 'sig', 'signature', 'credential', 'session', 'bearer', 'jwt', 'key'];
const SEPARATORS = ['?', '&', '#', ';'];
const VALUE = 'qwertyuiop';
const CONN_KEYS = ['Server', 'Data Source', 'host', 'HostName', 'uid', 'User Id', 'userid', 'Pwd', 'Password', 'Database', 'Initial Catalog'];
const CONN_CONTEXT = ['', '(', ',', '"', ' ', ';', '[', '{', ':', '/', '=', '-', '>', '\t'];
const CRED_KEYS = ['password', 'passwd', 'pwd', 'secret', 'token', 'api_key', 'apikey', 'authorization'];
const HOST_SUFFIXES = ['local', 'lan', 'internal', 'home.arpa', 'localdomain'];

/**
 * The families. `rule` names the round-6 rule the family is about (the per-rule layer compares that rule alone); `fixed` families have no length to sweep (one text, many places);
 * `make(n, i)` is the secret, n the length of the component under test and i the index of the length (it rotates the variants: the keyword, the separator, the key, the context).
 */
export const FAMILIES = Object.freeze([
  // ---- url token (the parameter name around the key word, the value)
  { id: 'url token: name before the key word', rule: 'url token', make: (n, i) => j('https://h.test/p', SEPARATORS[i % 4], NAME(n), KEYWORDS[i % 15], '=', VALUE) },
  { id: 'url token: name after the key word', rule: 'url token', make: (n, i) => j('x', SEPARATORS[i % 4], KEYWORDS[i % 15], NAME(n), '=', VALUE) },
  { id: 'url token: name on both sides', rule: 'url token', make: (n, i) => j('https://h.test/p', SEPARATORS[i % 4], NAME(n), KEYWORDS[(i + 3) % 15], NAME(n), '=', VALUE) },
  { id: 'url token: value', rule: 'url token', make: (n, i) => j('/p', SEPARATORS[i % 4], KEYWORDS[i % 15], '=', W(n + 2)) },
  // ---- connection pairs (the value, the context before the key, the spaces, a run of keys)
  { id: 'connection pairs: value', rule: 'connection pairs', make: (n, i) => j(CONN_CONTEXT[i % 14], CONN_KEYS[i % 11], [' ', '', '  '][i % 3], '=', [' ', '', '  '][(i + 1) % 3], W(n), [' ', ''][i % 2], ';') },
  { id: 'connection pairs: run before the key', rule: 'connection pairs', make: (n, i) => j(W(n), CONN_CONTEXT[1 + (i % 8)], CONN_KEYS[i % 11], '=srv;') },
  { id: 'connection pairs: spaces around the equals sign', rule: 'connection pairs', make: (n, i) => j(CONN_KEYS[i % 11], ' '.repeat(n), '=', ' '.repeat(n), 'v', ' '.repeat(n % 5), ';') },
  { id: 'connection pairs: a run of keys', rule: 'connection pairs', make: (n, i) => j('host='.repeat(n), CONN_KEYS[i % 11], '=x;') },
  // ---- jwt (the three segments, a run of starts)
  { id: 'jwt: first segment', rule: 'jwt', make: (n) => j('eyJ', SEG(n + 3), '.', SEG(40), '.', 'sig') },
  { id: 'jwt: second segment', rule: 'jwt', make: (n) => j('eyJ', SEG(10), '.', SEG(n + 3), '.', 'sig') },
  { id: 'jwt: third segment', rule: 'jwt', make: (n) => j('eyJ', SEG(10), '.', SEG(10), '.', SEG(n)) },
  { id: 'jwt: a run of starts', rule: 'jwt', make: (n) => j('eyJ-'.repeat(n), 'eyJ', 'abcd', '.', 'abcd', '.', 'sig') },
  // ---- key block, url credentials, connection string, credential pair, pass pair
  { id: 'key block: label', rule: 'key block', make: (n) => j('-----BEGIN ', cycle('OPENSSH RSA PRIVATE KEY 2 ', n), '-----') },
  { id: 'url credentials: user-info', rule: 'url credentials', make: (n) => j('https', '://', W(n), ':', 'pw', '@', 'host') },
  { id: 'url credentials: scheme', rule: 'url credentials', make: (n) => j(W(n), '://', 'u:p', '@', 'h') },
  { id: 'connection string: second part of the scheme', rule: 'connection string', make: (n) => j('jdbc:', W(n), '://', 'x') },
  { id: 'credential pair: spaces', rule: 'credential pair', make: (n, i) => j(CRED_KEYS[i % 8], ' '.repeat(n), ': ', 'qwerty') },
  { id: 'credential pair: value', rule: 'credential pair', make: (n, i) => j(CRED_KEYS[i % 8], '=', W(n + 3)) },
  { id: 'pass pair: prefix', rule: 'pass pair', make: (n, i) => (i % 2 ? j('a_'.repeat(n), 'pass=qwerty') : j('"', W(n), '_pass": "qwerty"')) },
  { id: 'pass pair: value', rule: 'pass pair', make: (n, i) => (i % 2 ? j('wifi_pw=', W(n + 3)) : j("'pw': '", W(n + 3), "'")) },
  // ---- wifi, bearer, known tokens
  { id: 'wifi credentials: name and password', rule: 'wifi credentials', make: (n) => j('WIFI:S:', W(n), ';T:WPA;P:', W(n), ';;') },
  { id: 'bearer: token', rule: 'bearer', make: (n, i) => j(['Bearer', 'Basic'][i % 2], ' ', W(n + 12)) },
  { id: 'known token: body', rule: 'known token', make: (n, i) => [j('gh', 'p_', ALNUM(n + 20)), j('xo', 'xb-', ALNUM(n + 10)), j('sk_', 'live_', ALNUM(n + 10)), j('AK', 'IA', 'ABCDEFGH', '23456789'), j('AI', 'za', ALNUM(n + 30)), j('glpat', '-', ALNUM(n + 20))][i % 6] },
  // ---- e-mail address
  { id: 'e-mail: local part', rule: 'email address', make: (n) => j(cycle('ghij.klmn_op%qr+st-uv', n), '@', 'mail', '.example', '.org') },
  { id: 'e-mail: number of domain labels', rule: 'email address', make: (n) => j('bob', '@', 'a1.'.repeat(n), 'com') },
  { id: 'e-mail: label length', rule: 'email address', make: (n) => j('bob', '@', W(n), '.org') },
  { id: 'e-mail: top-level domain', rule: 'email address', make: (n) => j('bob', '@', 'mail.', W(n + 1)) },
  // ---- addresses
  { id: 'IPv4 address', rule: 'IPv4 address', fixed: true, make: (n, i) => [j('192', '.', '168', '.', '7', '.', '9'), j('gateway at ', '10', '.', '20', '.', '30', '.', '40', ' today')][i % 2] },
  { id: 'IPv6 address', rule: 'IPv6 address', fixed: true, make: (n, i) => [j('fd12:3456:789a:1', '::', '42'), j('2001:0db8:85a3:0000:0000:8a2e:0370:7334')][i % 2] },
  { id: 'MAC address', rule: 'MAC address', fixed: true, make: (n, i) => [j('aa', ':', 'bb', ':', 'cc', ':', 'dd', ':', 'ee', ':', 'f1'), j('aa', '-', 'bb', '-', 'cc', '-', 'dd', '-', 'ee', '-', 'f1')][i % 2] },
  { id: 'MAC address (spaced)', rule: 'MAC address (spaced)', fixed: true, make: (n, i) => [j('aa bb cc dd ee f1'), j('0a 1b 2c 3d 4e 5f')][i % 2] },
  { id: 'MAC address (no separators)', rule: null, fixed: true, make: (n, i) => [j('aabbccddee', 'f1'), j('0123456789', 'ab')][i % 2] },
  { id: 'MAC address (dotted): a letter after the address', rule: 'MAC address (dotted)', make: (n, i) => (i % 2 ? j('0123.4567.8901.', '0'.repeat(n), 'a') : j('2026.1114.0900.', '9'.repeat(n), 'b')) },
  { id: 'MAC address (dotted): a letter in the address, a run before', rule: 'MAC address (dotted)', make: (n, i) => j('0.'.repeat(n), ['0123.4567.89ab', 'a123.4567.8901', '0123.45f7.8901'][i % 3]) },
  { id: 'coordinates: decimals', rule: 'coordinates', make: (n) => j('51.', DIGITS(n + 2), ', ', '-0.', DIGITS(n + 2, '1')) },
  { id: 'labelled coordinate: spaces', rule: 'labelled coordinate', make: (n, i) => j(['lat', 'latitude', 'lon', 'long', 'longitude', 'lng'][i % 6], ' '.repeat(n), ': 51.5074') },
  { id: 'hemisphere coordinates: spaces', rule: 'hemisphere coordinates', make: (n) => j('52.1 N', ' '.repeat(n), '0.12 W') },
  // ---- webhook, hosts
  { id: 'webhook path: id', rule: 'webhook path', make: (n) => j('/api/', 'web', 'hook/', W(n)) },
  { id: 'webhook path: host', rule: 'webhook path', make: (n) => j('https://hooks.', cycle('ghijklmnopqrs.tuvwxyz-', n), '.test/services/', 'T01/B02/', W(12)) },
  { id: 'webhook path: a run of hooks.', rule: 'webhook path', make: (n) => j('hooks.'.repeat(n), 'a/services/', 'abcdefghijkl') },
  { id: 'internal host name: host', rule: 'internal host name', make: (n) => j('ws://', W(n), ':8123/x') },
  { id: 'internal host name: scheme', rule: 'internal host name', make: (n) => j(W(n), '://nas') },
  { id: 'private host name: label', rule: 'private host name', make: (n, i) => j(W(n), '.', HOST_SUFFIXES[i % 5]) },
  { id: 'private host name: number of labels', rule: 'private host name', make: (n, i) => j('a.'.repeat(n), HOST_SUFFIXES[i % 5]) },
  // ---- the whole-text rules
  { id: 'long hex value', rule: null, make: (n) => HEXRUN(n) },
  { id: 'long encoded value', rule: null, make: (n) => ALNUM(n + 20) },
]);

/** Every length from 1 to 300, then 400, 600 and 1000. */
export const DENSE = Object.freeze([...Array.from({ length: 300 }, (_, i) => i + 1), 400, 600, 1000]);
/** The lengths on either side of every bound a rule has had (64, 253, 256, 512, 4096) and a spread beyond them. */
export const SPARSE = Object.freeze([1, 3, 4, 5, 8, 12, 16, 20, 31, 32, 33, 62, 63, 64, 65, 66, 100, 127, 128, 129, 200, 252, 253, 254, 255, 256, 257, 258, 300, 400, 500, 511, 512, 513, 514, 600, 1000, 2000, 4095, 4096, 4097, 4098]);

const PROSE = filler(4300);
const prose = (n) => PROSE.slice(0, n);

/** The places one secret is put: [label, text]. SHORT carriers (160 characters) for the dense sweep, LONG ones (4000) for the sparse one. */
export function placements(secret, { long = false } = {}) {
  const c = long ? 4000 : 160;
  const out = [
    ['start', `${secret} ${prose(c)}`],
    ['middle', `${prose(c / 2)} ${secret} ${prose(c / 2)}`],
    ['end', `${prose(c)} ${secret}`],
  ];
  if (!long) out.unshift(['bare', secret]);
  else out.push(['glued at the start', `${secret}${prose(c)}`], ['glued at the end', `${prose(c)}${secret}`]);
  return out;
}

/** Every case of the corpus: { family, rule, n, place, text }. The zero-width variant (one character of the secret, then U+200B) is added for every seventh length, so the fold is exercised too. */
export function* cases({ dense = true, sparse = true, only = null } = {}) {
  for (const fam of FAMILIES) {
    if (only !== null && !only(fam)) continue;
    const sweeps = [];
    if (fam.fixed) sweeps.push([[1, 2, 3, 4], false]);
    else {
      if (dense) sweeps.push([DENSE, false]);
      if (sparse) sweeps.push([SPARSE, true]);
    }
    for (const [lengths, long] of sweeps) {
      for (let li = 0; li < lengths.length; li += 1) {
        const n = lengths[li];
        let secret = fam.make(n, li);
        if (li % 7 === 3) secret = `${secret.slice(0, 1)}\u200b${secret.slice(1)}`;
        for (const [place, text] of placements(secret, { long })) yield { family: fam.id, rule: fam.rule, n, place, text };
      }
    }
  }
}
