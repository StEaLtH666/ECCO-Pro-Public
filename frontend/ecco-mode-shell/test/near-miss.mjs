// The near-miss texts of review round 7 (not a test file): units that are the start of a match of some value rule, or a character a rule treats as a boundary, and that never complete. A text is a unit
// repeated to the length asked. perf.test.mjs times every rule on them; scan.test.mjs checks the rules still withhold what they withheld before.

/** The near-miss families. Each unit is the start of a match of some rule (or a character a rule treats as a boundary) that never completes; the text is the unit repeated to the length asked. */
export const UNITS = Object.freeze([
  // separators and runs that every dotted, hyphenated or segmented rule walks
  'a.', 'a-', 'ab-', 'a_', '0.', '1.1.', '0123.', '0123.4567.', '0.0.0.', '.1', 'a.b', 'a-b.', 'a%', 'a+', 'a b', ' ', 'a\n', 'ab:', 'ab:cd:', '0a:0a:', 'aa-aa-', 'ff', 'Ab1', 'aB+/',
  // starts of the rules with a prefix word
  'eyJ', 'eyJ-', 'eyJab.', 'eyJabcd.abcd', '-----BEGIN ', '-----BEGIN A', 'a://', 'a://u', 'a://u:p', '://', '://a:1', 'ws://a', 'postgres:', 'ssh:a:', '?k', '?key', '?key=', '&token', '&token=a',
  'password', 'password  ', 'token:', 'token=', 'api_key', 'Server=', 'Server=a', 'Server= a', 'host=', ';host=', ' host=', 'Pwd=', 'Data Source=', 'uid=',
  'pass', 'pass"', '"pass', '"pass": ', '"a_pass"', "'pw'", 'pw=', 'pass=', 'a_pass=', 'a_a_a_pass=', 'xpass=', 'WIFI:', 'WIFI:S:', 'Bearer ', 'Bearer abc', 'ghp_', 'xoxb-', 'sk_live_', 'AKIA', 'AIza',
  '@', 'a@', 'a@a', 'a@a.', 'a@a.a', 'a.b@', '@a.', '1.2345,', '1.2345, ', '1.2345, 1.2345', 'lat ', 'lat: 1.', '1 N', '1 N, 1', '/api/webhook/', 'hooks.', 'hooks.a.b/', 'hooks.a/services/',
  'x.local', '.local', '.lan', '.home.arpa', '1:2:', 'ff:ff:', 'aabb.', 'aabb.ccdd.', '1234.5678.', 'aa ', 'aa bb cc dd ee ', '10 ',
  // a long run of one separator or one quote (a run of a single character that some rule treats as a boundary)
  '.', '-', ':', '=', '/', ';', '"', "'", '?', '#', '+', '%',
  // two of them together, and the reviewer's own shape
  'a.b.c@d:/x=pass 0123.4567.89ab ', ' .local @ x ', '0123.@', 'a-@', 'http://a.', ':a@',
]);

/** The unit repeated to exactly n characters. */
export const textOf = (unit, n) => unit.repeat(Math.ceil(n / unit.length)).slice(0, n);
