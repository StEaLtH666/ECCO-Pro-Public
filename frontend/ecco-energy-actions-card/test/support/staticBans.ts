// The static bans of the read-only plan adapter, in one place so the test that uses them and the test that proves them cannot drift apart.
//
// History: until 17 Nov 2026 five of these were written with a literal BACKSPACE byte (0x08) where the regex word boundary \b was meant, so
// they matched nothing and the adapter's "no hass, clock, fetch, document or window" proof was vacuous. They are \b-style patterns now, and
// each is written so that it fires on real use and not on prose (a reason text may say "there is no charge window."). test/testSourcesClean.test.ts
// proves both halves: the old defect is detected, and every pattern below fires on a violating snippet.
export const ADAPTER_BANS: readonly RegExp[] = [
  /callService/,
  /\bhass\b/,
  /\bDate\b/,
  /localStorage/,
  /\bfetch\s*\(/,
  /\bdocument\.[A-Za-z_$]|\bdocument\[/,
  /\bwindow\.[A-Za-z_$]|\bwindow\[|\btypeof\s+window\b|[(,=]\s*window\s*[;,)]/,
  /innerHTML/,
  /from "lit/,
  /Math.random/,
];

// A control character other than tab, line feed and carriage return: never legitimate in a source file of this repository.
export const CONTROL_CHARS = /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/;
