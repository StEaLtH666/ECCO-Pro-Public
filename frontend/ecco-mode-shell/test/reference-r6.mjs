// FROZEN REFERENCE (review round 8): the redactor's value rules exactly as ROUND 6 had them (commit f4e52be), before round 7 bounded their quantifiers.
//
// Why this file exists. Round 7 made the rules linear by bounding some quantifiers ({0,64}, {1,256}, {4,512}, ...). A bounded rule stops matching a secret whose component is longer than the bound,
// and the reviewer of round 8 found five inputs that round 6 withheld and round 7 SHOWED (a token parameter name of 65 characters; a connection pair after a bracket with a 300-character value; a JWT
// whose first segment is over 512 characters; a key block label of 80 characters). A performance fix must never be a privacy regression, so the rules are now gated by a DIFFERENTIAL TEST: whatever this
// reference withholds, the card must still withhold (the card may withhold MORE, never less). The test is test/differential.test.mjs and its corpus is test/differential.mjs.
//
// This file is a copy and must not be edited: it is the yardstick. It is slow (several rules are quadratic on near-miss text, which is exactly why round 7 changed them), so it is only ever run on
// the short generated corpus of the differential test, never on a long near-miss text and never by the card. It holds no secret: only patterns. (Extracted verbatim by a script from
// `git show f4e52be:frontend/ecco-mode-shell/ecco-mode-shell.js`; the RULES array, the pre-tests, the three whole-text rules and valueReason are unchanged, as is the fold they use.)

const CTRL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/g;

// Detection works on a FOLDED copy of a text: invisible, zero-width and format characters removed, compatibility forms folded (NFKC) and look-alike
// letters of other alphabets turned into the Latin letter they imitate, so a secret cannot hide behind a zero-width character or a Cyrillic "a".
// What is SHOWN is never the folded copy: cleanText still makes every such character visible. The table is written as code points so that this
// file stays plain ASCII.
const CONFUSABLES = new Map([
  [0x430, 'a'], [0x435, 'e'], [0x43e, 'o'], [0x440, 'p'], [0x441, 'c'], [0x443, 'y'], [0x445, 'x'], [0x456, 'i'], [0x458, 'j'], [0x455, 's'], [0x501, 'd'],
  [0x4bb, 'h'], [0x4cf, 'l'], [0x43a, 'k'], [0x475, 'v'], [0x51d, 'w'], [0x261, 'g'], [0x251, 'a'],
  [0x3bf, 'o'], [0x3b1, 'a'], [0x3bd, 'v'], [0x3c1, 'p'], [0x3b9, 'i'], [0x3ba, 'k'], [0x3c5, 'u'], [0x3c7, 'x'],
  [0x410, 'A'], [0x412, 'B'], [0x415, 'E'], [0x41a, 'K'], [0x41c, 'M'], [0x41d, 'H'], [0x41e, 'O'], [0x420, 'P'], [0x421, 'C'], [0x422, 'T'], [0x425, 'X'], [0x406, 'I'],
  [0x391, 'A'], [0x392, 'B'], [0x395, 'E'], [0x396, 'Z'], [0x397, 'H'], [0x399, 'I'], [0x39a, 'K'], [0x39c, 'M'], [0x39d, 'N'], [0x39f, 'O'], [0x3a1, 'P'],
  [0x3a4, 'T'], [0x3a5, 'Y'], [0x3a7, 'X'],
]);
const RE_ASCII_PLAIN = /^[\x20-\x7e]*$/;
/** A copy of `s` for matching only (see above). Plain printable ASCII, the common case, is returned as it is. */
function fold(s) {
  if (RE_ASCII_PLAIN.test(s)) return s;
  let t = s.replace(CTRL, '');
  try {
    t = t.normalize('NFKC');
  } catch {
    // a text that cannot be normalised is matched as it is
  }
  let out = '';
  for (const ch of t) out += CONFUSABLES.get(ch.codePointAt(0)) || ch;
  return out;
}

// VALUE rules: [reason, required substring or null, pattern]. The gates keep the common case (short plain strings) cheap.
const RULES = [
  ['jwt', 'eyJ', /\beyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]*/],
  ['key block', '-----', /-----BEGIN [A-Z0-9 ]+-----/],
  ['url credentials', '@', /\b[a-z][a-z0-9+.-]*:\/\/[^\s/?#@]*@/i],
  ['connection string', '://', /\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss|amqps?|mqtts?|influxdb|mssql|sqlserver|jdbc|ftps?|sftp|ssh|smb|ldaps?|couchdb)(?::[a-z0-9]+)?:\/\//i],
  ['url token', '=', /[?&#;][\w.%-]*(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key)[\w.%-]*=[^&\s]{3,}/i],
  ['credential pair', null, /\b(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization)\b["']?\s*[:=]\s*["']?[^\s,;"']{3,}/i],
  ['connection pairs', ';', /\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\s*=\s*[^;\s]+\s*;/i],
  // a password written as a pair under a short name: a quoted "pass" or "pw" key, or pass=value and pw=value (not plain prose such as "pass: true"); the same pattern as the Python scanner's PASS_PAIR
  ['pass pair', null, /["']\s*(?:[a-z0-9_-]*[_-])?(?:pass|pw)\s*["']\s*:\s*["']?[^\s,;"']{3,}|(?<![a-z0-9])(?:[a-z0-9]+[_-])*(?:pass|pw)=["']?[^\s,;&"']{3,}/i],
  // the text a phone reads from a Wi-Fi QR code: WIFI:S:<name>;T:<type>;P:<password>;;
  ['wifi credentials', ':', /\bWIFI:[A-Z]:/i],
  ['bearer', null, /\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}/i],
  ['known token', null, /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|sk_(?:live|test)_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{20,})/],
  ['email address', '@', /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b/],
  ['IPv4 address', '.', /\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/],
  ['IPv6 address', ':', /(?:^|[^0-9a-fA-F:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![0-9a-fA-F:])|(?:^|[^0-9a-zA-Z:])(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}?::(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6})?(?![0-9a-zA-Z:])/],
  ['MAC address', null, /\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b/],
  // the dotted form (three groups of four) that network equipment writes; at least one letter, so a version such as 2026.1114.0900 is not taken for one
  ['MAC address (dotted)', '.', /\b(?=[0-9a-f.]*[a-f])[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b/i],
  // the six bytes with a space between them ("aa bb cc dd ee ff"), as some tools and hex dumps print one (review round 4); at least one letter, so six two-digit numbers
  // are not taken for one. The same pattern as the Python scanner's MAC_SPACED. An all-digit address written this way is indistinguishable from six numbers and stays shown.
  ['MAC address (spaced)', ' ', /(?<![0-9a-f])(?=[0-9a-f ]{0,16}[a-f])(?:[0-9a-f]{2} ){5}[0-9a-f]{2}(?![0-9a-f])/i],
  ['coordinates', null, /(?:^|[^\d.])-?\d{1,3}\.\d{3,}\s*[,;]\s*-?\d{1,3}\.\d{3,}(?![\d.])/],
  ['labelled coordinate', null, /\b(?:lat(?:itude)?|lon(?:g|gitude)?|lng)\b[\s:=]*-?\d{1,3}\.\d{3,}/i],
  ['hemisphere coordinates', null, /\b\d{1,3}(?:\.\d+)?\s*[NS]\b[\s,;]*\d{1,3}(?:\.\d+)?\s*[EW]\b/],
  // a webhook: the id in the path IS the credential (the Home Assistant webhook path and the chat services path); the same pattern as the Python scanner's WEBHOOK_PATH
  ['webhook path', '/', /\/api\/webhook\/[A-Za-z0-9_-]{8,}|hooks\.[a-z0-9.-]+\/services\/[A-Za-z0-9/_-]{12,}/i],
  ['internal host name', '://', /\b[a-z][a-z0-9+.-]*:\/\/[a-z0-9-]+(?::\d{1,5})?(?=[/?#\s"']|$)/i],
  ['private host name', '.', /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:local|lan|internal|home\.arpa|localdomain)\b/i],
];
// Review round 6: a PRE-TEST is a cheap, linear test that every match of a rule must pass (a necessary condition, so the verdict is the same). A text is now read whole up to LIMITS.scanBound, and
// three of the rules above read ahead from every start position, so a long text that only LOOKS like the start of one of them (a dotted run of letters, a long run of ab- groups) was walked once per start:
// about a quarter of a second for one 20000-character text. The pre-test is a table of its own so that the rules above stay exactly as the Python scanner's patterns are.
const RULE_PRETESTS = {
  'pass pair': /(?:pass|pw)(?:\s*["']|=)/i,
  'MAC address (dotted)': /[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}/i,
  'private host name': /\.(?:local|lan|internal|home\.arpa|localdomain)\b/i,
};
const PRETEST = RULES.map(([reason]) => RULE_PRETESTS[reason]);
const RE_HEX = /(?:^|[^0-9a-fA-F])[0-9a-fA-F]{32,}(?![0-9a-fA-F])/;
const RE_B64 = /[A-Za-z0-9+/_-]{32,}={0,2}/g;
const RE_GIT = /^[0-9a-f]{40}$/i;
// a MAC address written with no separator: exactly twelve hex digits with at least one letter (twelve plain digits are a number)
const RE_MAC12 = /^\s*(?=[0-9a-f]*[a-f])[0-9a-f]{12}\s*$/i;

/** Why a string looks secret or private, or null. */
function valueReason(raw, digestOk, digestKey = false) {
  if (raw.length < 6) return null;
  const s = fold(raw);
  if (s.length < 6) return null;
  for (let i = 0; i < RULES.length; i += 1) {
    const [reason, gate, re] = RULES[i];
    if (gate !== null && !s.includes(gate)) continue;
    if (PRETEST[i] !== undefined && !PRETEST[i].test(s)) continue;
    if (re.test(s)) return reason;
  }
  // a revision key (commit, git_sha) may hold a short public git revision, which has the same shape
  if (!digestKey && RE_MAC12.test(s)) return 'MAC address (no separators)';
  if (s.length >= 32) {
    if (!digestOk && RE_HEX.test(s)) return 'long hex value';
    for (const t of s.match(RE_B64) || []) if (/[A-Z]/.test(t) && /[a-z]/.test(t) && /[0-9]/.test(t)) return 'long encoded value';
  }
  return null;
}

/** The round-6 table of rules: [reason, gate, pattern] and the pre-test table, for the per-rule layer of the differential test. */
export const REF_RULES = Object.freeze(RULES.map(([reason, gate, pattern], i) => Object.freeze({ reason, gate, pattern, pretest: PRETEST[i] === undefined ? null : PRETEST[i] })));
/** Why the round-6 card would have withheld a text (or null), under a key that is not a revision key. */
export const refReason = (text, digestOk = false, digestKey = false) => valueReason(text, digestOk, digestKey);
/** The round-6 verdict of one rule alone, with its gate and its pre-test (what valueReason does for that entry). */
export const refRuleHits = (rule, text) => {
  const s = fold(text);
  if (s.length < 6) return false;
  if (rule.gate !== null && !s.includes(rule.gate)) return false;
  if (rule.pretest !== null && !rule.pretest.test(s)) return false;
  return rule.pattern.test(s);
};
