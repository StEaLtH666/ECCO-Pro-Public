// Opt-in headless-browser check of the alert strip (review round 3). Not part of `node --test`: it needs Chrome or Edge and runs on request.
//
//   node preview/check-strip.mjs                          check the card as it is
//   node preview/check-strip.mjs --card <file>            check a copy of ecco-mode-shell.js instead
//   node preview/check-strip.mjs --selftest               prove the check is not vacuous: it must PASS the card and FAIL each of the deliberately broken copies (31 since round 4)
//   node preview/check-strip.mjs --json                   print the full report as JSON
//   node preview/check-strip.mjs --require                exit 3, not 0, when no browser is found (for a pipeline that must not skip silently)
//   ECCO_CHROME=<path to chrome.exe or msedge.exe>        use this browser
//
// What it does: serves frontend/ecco-mode-shell on the loopback address (read only, one port the system picks, closed at the end), starts a headless Chrome or
// Edge against preview/strip-check.html, and reads back what the browser computed for the alert strip in Production and Geek Mode, light and dark, with and
// without Home Assistant's theme variables, at two widths and in two window sizes. strip-check-lib.mjs judges the numbers: the strip box has a real size, is inside
// the viewport and its card, is fully opaque, is not transformed, filtered, masked or clipped, is not covered, has text at least 12 px with at least 4.5 : 1
// contrast, and is the SAME box with the same lines in both modes. It never reads the stylesheet: the static net (test/static.test.mjs) stays the mandatory one,
// and this is the net that does not depend on how a rule is written. No network (loopback only), no write outside a temporary browser profile it deletes.
//
// Exit codes: 0 all checks passed (or SKIPPED because there is no browser: loud, and 3 with --require), 1 a check failed, 2 the page did not report.
import { createServer } from 'node:http';
import { existsSync, readFileSync, writeFileSync, mkdtempSync, rmSync, statSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { evaluateAll } from './strip-check-lib.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const cardDir = path.resolve(here, '..');
const arg = (name) => { const i = process.argv.indexOf(name); return i === -1 ? null : process.argv[i + 1] || ''; };
const flag = (name) => process.argv.includes(name);

/** The browser to use: ECCO_CHROME, then the standard install places of Chrome and Edge on Windows, macOS and Linux. */
export function findBrowser(env = process.env, exists = existsSync) {
  const win = [env.ProgramFiles, env['ProgramFiles(x86)'], env.LOCALAPPDATA].filter(Boolean);
  const list = [
    env.ECCO_CHROME,
    ...win.flatMap((d) => [path.join(d, 'Google', 'Chrome', 'Application', 'chrome.exe'), path.join(d, 'Microsoft', 'Edge', 'Application', 'msedge.exe')]),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge',
  ].filter(Boolean);
  return list.find((p) => exists(p)) || null;
}

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8' };

/** A read-only static server for the card folder, plus the card file under test (if any) at /__card/ecco-mode-shell.js. The file served there is read afresh per request. */
function serve(getCardFile) {
  const root = cardDir + path.sep;
  const server = createServer((req, res) => {
    try {
      const url = new URL(req.url, 'http://127.0.0.1');
      const cardFile = getCardFile();
      let file = null;
      if (req.method !== 'GET') file = null;
      else if (cardFile && url.pathname === '/__card/ecco-mode-shell.js') file = cardFile;
      else if (url.pathname.startsWith('/frontend/ecco-mode-shell/')) file = path.resolve(cardDir, `.${url.pathname.slice('/frontend/ecco-mode-shell'.length)}`);
      if (!file || (file !== cardFile && !file.startsWith(root)) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404);
        res.end('not found');
        return;
      }
      res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
      res.end(readFileSync(file));
    } catch {
      res.writeHead(500);
      res.end('error');
    }
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port })));
}

/** Run a process to completion. It must be an ASYNC spawn: this process also serves the page, and a blocked event loop would never answer the browser. */
function runProcess(cmd, args, ms) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; child.kill(); }, ms);
    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr = (stderr + d).slice(-4000); });
    child.on('error', (e) => { clearTimeout(timer); resolve({ status: -1, stdout, stderr: String(e), timedOut }); });
    child.on('close', (status) => { clearTimeout(timer); resolve({ status, stdout, stderr, timedOut }); });
  });
}

async function runBrowser(browser, port, windowSize, widths, card) {
  const profile = mkdtempSync(path.join(tmpdir(), 'ecco-strip-check-'));
  try {
    const page = `http://127.0.0.1:${port}/frontend/ecco-mode-shell/preview/strip-check.html?widths=${widths}${card ? '&card=/__card/ecco-mode-shell.js' : ''}`;
    const args = ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-sync', '--disable-component-update',
      '--disable-background-networking', `--user-data-dir=${profile}`, `--window-size=${windowSize}`, '--virtual-time-budget=20000', '--dump-dom', page];
    const r = await runProcess(browser, args, 120000);
    const m = /<pre id="strip-check-result">([A-Za-z0-9+/=]*)<\/pre>/.exec(r.stdout || '');
    if (!m || !m[1]) return { error: `the page reported nothing (exit ${r.status}${r.timedOut ? ', timed out' : ''}, ${String(r.stdout || '').length} bytes of DOM)`, states: [] };
    const rep = JSON.parse(Buffer.from(m[1], 'base64').toString('utf8'));
    return rep.error ? { error: rep.error, states: rep.states || [] } : { error: null, states: rep.states };
  } finally {
    try {
      rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    } catch {
      // a temporary profile that cannot be removed right now is left for the operating system's temp cleaning
    }
  }
}

/** One full check of one card file (null = the real card): { errors, measured, report }. */
async function check(browser, port, useCard) {
  const measured = [];
  const errors = [];
  // a narrow window (a phone) with the narrow card, and a wide one with a narrow and a wide card; Chrome clamps a headless window to about 500 px, so 520 is the narrowest
  for (const [windowSize, widths] of [['520,1500', '390'], ['1100,1500', '390,1000']]) {
    const r = await runBrowser(browser, port, windowSize, widths, useCard);
    if (r.error) errors.push(`window ${windowSize}: ${r.error}`);
    measured.push(...r.states);
  }
  return { errors, measured, report: errors.length ? null : evaluateAll(measured) };
}

/** The deliberately broken copies of the card for --selftest: [id, text to find in the stylesheet or the source, replacement]. Each one must make the check FAIL. */
const GEEK_LINE = "    ui.geekBody.hidden = mode !== 'geek';";
const ANCHOR = '.alert-head{font-weight:700}';
const css = (rule) => [ANCHOR, `${ANCHOR}\n${rule}`];
export const BROKEN = Object.freeze([
  ['R3-C1 role=region rotated edge-on in Geek Mode (upper-case DATA-MODE)', ...css('.shell[DATA-MODE="geek"]>[role=region]{transform:rotateX(90deg)}')],
  ['R3-C2 tiny font in Geek Mode', ...css('.shell[DATA-MODE=geek]>[aria-live]{font-size:.01px}')],
  ['R3-C3 transparent text in both modes', ...css('div[aria-live]{color:rgba(0,0,0,0)}')],
  ['R3-C4 scaled to a thousandth', ...css('[aria-live]{transform:scale(.001)}')],
  ['R3-C5 ordered below the Geek body in Geek Mode', ...css('.shell[DATA-MODE=geek]>[aria-live]{order:99}')],
  ['R3-C6 pushed off screen by :has() and a negative margin in Geek Mode', ...css('.shell:has(> .region:last-child:not([hidden])) .alerts{margin-left:-200vw}')],
  ['R3-C7 blurred', ...css('[aria-live]{filter:blur(40px)}')],
  ['display none in Geek Mode', ...css('.shell[data-mode="geek"] .alerts{display:none}')],
  ['visibility hidden', ...css('.alerts{visibility:hidden}')],
  ['opacity .02', ...css('.alerts{opacity:.02}')],
  ['height 0 with overflow hidden', ...css('.alerts{height:0;overflow:hidden}')],
  ['positioned off screen', ...css('.alerts{position:absolute;left:-9999px}')],
  ['clip-path circle(0)', ...css('[role=region]{clip-path:circle(0)}')],
  ['masked with a transparent gradient', ...css('.shell>[aria-live]{-webkit-mask-image:linear-gradient(transparent,transparent)}')],
  ['line-height 0 and clipped lines', ...css('.alert{line-height:0;overflow:hidden;max-height:2px}')],
  ['text colour equal to the background', '.alert-action{margin:0;color:var(--ecco-fg2);', '.alert-action{margin:0;color:var(--ecco-surface);'],
  ['theme colours: text and surface set to the same (each is an allowed colour, so the stylesheet reader accepts it)', ...css('.shell{--ecco-fg:#ffffff;--ecco-surface:#ffffff;--ecco-fg2:#ffffff}')],
  ['faint text colour (contrast below 4.5)', ...css('.alert-head{color:rgba(120,120,120,1)}')],
  ['covered by a positioned block above it', ...css('.shell>.top{position:relative;z-index:5;margin-bottom:-90px;min-height:240px;background:#000}')],
  ['moved sideways by a margin', ...css('.alerts{position:relative;left:60px}')],
  ['content-visibility hidden', ...css('.shell>*{content-visibility:hidden}')],
  ['size containment collapses it', ...css('.alerts{contain:size}')],
  ['an inline style on the strip', "'aria-label': 'Safety and status alerts', 'aria-live': 'polite' });", "'aria-label': 'Safety and status alerts', 'aria-live': 'polite', style: 'height:0;overflow:hidden' });"],
  ['the strip hidden by the code in Geek Mode', "    ui.geekBody.hidden = mode !== 'geek';", "    ui.geekBody.hidden = mode !== 'geek';\n    ui.strip.hidden = mode === 'geek';"],
  ['only the first alert shown in Geek Mode', "    ui.geekBody.hidden = mode !== 'geek';", "    ui.geekBody.hidden = mode !== 'geek';\n    renderAlertStrip(this.ownerDocument, ui.strip, mode === 'geek' ? this._alerts.slice(0, 1) : this._alerts);"],
  // review round 4: the ARIA attributes that pixels cannot show (reviewer mutants J2 and J5 survived every offline suite and the round 3 browser check, which looked only at the pixels)
  ['J2 aria-hidden on the strip in Geek Mode', GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false');`],
  ['J5 aria-live off in Geek Mode', GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('aria-live', mode === 'geek' ? 'off' : 'polite');`],
  ['aria-hidden on the shell that holds the strip, in Geek Mode', GEEK_LINE, `${GEEK_LINE}\n    ui.shell.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false');`],
  ['inert on the card element in Geek Mode', GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') this.setAttribute('inert', '');`],
  ['role presentation on the strip in Geek Mode', GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('role', mode === 'geek' ? 'presentation' : 'region');`],
  ['every alert line given role presentation (both modes)', "role: critical ? 'alert' : 'status' })", "role: 'presentation' })"],
]);

async function main() {
  const browser = findBrowser();
  if (!browser) {
    const bar = '!'.repeat(96);
    const msg = `\n${bar}\n!! SKIPPED: no Chrome or Edge found. The headless alert-strip check did NOT run, so nothing was checked in a browser.\n!! Install one, or set ECCO_CHROME to its path. The static net (node --test) still ran separately.\n${bar}\n`;
    process.stdout.write(msg);
    process.stderr.write(msg);
    process.exit(flag('--require') ? 3 : 0);
  }
  const cardArg = arg('--card');
  let cardFile = cardArg ? path.resolve(cardArg) : null;
  if (cardFile && !existsSync(cardFile)) {
    process.stderr.write(`no such card file: ${cardFile}\n`);
    process.exit(2);
  }
  const { server, port } = await serve(() => cardFile);
  try {
    if (flag('--selftest')) {
      const real = readFileSync(path.join(cardDir, 'ecco-mode-shell.js'), 'utf8');
      const dir = mkdtempSync(path.join(tmpdir(), 'ecco-strip-selftest-'));
      let wrong = 0;
      try {
        cardFile = path.join(dir, 'card.js');
        writeFileSync(cardFile, real);
        const base = await check(browser, port, true);
        const baseOk = !base.errors.length && base.report.failed === 0;
        process.stdout.write(`the unbroken card: ${baseOk ? 'PASS (as it must)' : `DID NOT PASS (${base.errors.join('; ') || `${base.report.failed} checks failed`})`}\n`);
        if (!baseOk) wrong += 1;
        for (const [id, find, repl] of BROKEN) {
          const n = real.split(find).length - 1;
          if (n !== 1) {
            process.stdout.write(`  BAD   ${id}: the text to break was found ${n} times\n`);
            wrong += 1;
            continue;
          }
          writeFileSync(cardFile, real.replace(find, () => repl));
          const r = await check(browser, port, true);
          const caught = r.errors.length > 0 || r.report.failed > 0;
          process.stdout.write(`  ${caught ? 'caught' : 'MISSED'} ${id}${r.errors.length ? ' (the page did not run)' : `: ${r.report.failed} of ${r.report.total} checks fail`}\n`);
          if (!caught) wrong += 1;
        }
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
      process.stdout.write(`\n${wrong === 0 ? 'SELFTEST PASS' : 'SELFTEST FAIL'}: the check passes the real card and catches ${BROKEN.length - wrong} of ${BROKEN.length} broken copies\n`);
      process.exit(wrong === 0 ? 0 : 1);
    }
    const r = await check(browser, port, Boolean(cardFile));
    if (r.errors.length) {
      process.stderr.write(`the page did not finish:\n  ${r.errors.join('\n  ')}\n`);
      process.exit(2);
    }
    if (flag('--json')) {
      process.stdout.write(`${JSON.stringify({ browser, report: r.report, measured: r.measured }, null, 1)}\n`);
    } else {
      process.stdout.write(`browser: ${browser}\ncard: ${cardFile || path.join(cardDir, 'ecco-mode-shell.js')}\nstates measured: ${r.report.states.length} (${r.report.pairs.length} Production / Geek pairs)\n`);
      for (const g of [...r.report.states, ...r.report.pairs]) {
        const bad = g.checks.filter((c) => !c.ok);
        process.stdout.write(`  ${bad.length ? 'FAIL' : 'ok  '} ${g.id}  (${g.checks.length - bad.length}/${g.checks.length})\n`);
        for (const c of bad) process.stdout.write(`        - ${c.name}: ${c.detail}\n`);
      }
      process.stdout.write(`\n${r.report.failed === 0 ? 'PASS' : 'FAIL'}: ${r.report.total - r.report.failed} of ${r.report.total} checks hold${r.report.failed ? `; ${r.report.failed} do not` : ''}\n`);
    }
    process.exit(r.report.failed === 0 ? 0 : 1);
  } finally {
    server.close();
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) await main();
