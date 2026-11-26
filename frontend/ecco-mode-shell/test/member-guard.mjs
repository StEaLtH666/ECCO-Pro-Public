// The member-access guard (review round 8; not a test file; test-side only, the card is read and never changed).
//
// What it protects. A mutant of round 7 hid the alert strip in Geek Mode with the Web Animations API reached by a name built from pieces (`const fn = 'ani' + 'mate'; ui.strip[fn](...)`) and another one by walking the
// prototype chain (`Object.getPrototypeOf(...)`, `Object.getOwnPropertyNames(...)`), and both passed every node suite: the static net refused the NAME of the API in the source (`.animate(`), and a name that is not
// written is not refused. The class is "a member of an object is reached by something that is not its name", so this guard reads the STRUCTURE of the source:
//   (1) every computed member access `receiver[key]` whose key is not a number or a string literal is listed (receiver and key, as written), and the list is PINNED by the static test: a new one, or a changed
//       receiver, is refused until a person has decided it and edited the pin in the same commit. The pinned ones are lookups in plain tables and in plain data (a status word by status, an attribute by name), and
//       the three of the mode switch (`ui.opts[m]`: the two buttons of the switch, by mode);
//   (2) the prototype chain is never walked, a property is never described, and no loop enumerates inherited keys (getPrototypeOf, setPrototypeOf, getOwnPropertyNames, getOwnPropertyDescriptor(s),
//       getOwnPropertySymbols, __proto__ as a property, .constructor, .prototype, for ... in);
//   (3) no string literal of the module is the NAME of a tripwire member (a bracket with a quoted name, `strip['animate']`, is a door the name rules do not see).
// Behind it stand the tripwires of minidom.mjs (each of those members records being read or called, in the element tests) and the headless browser check.
//
// Limit (said in the design document): a static read of source cannot exclude every dynamic way to reach a member; the card already forbids eval, Function, Reflect, Proxy and globalThis, and the tripwires look at the result.

const KEYWORDS = new Set(['const', 'let', 'var', 'return', 'typeof', 'in', 'of', 'case', 'new', 'else', 'do', 'void', 'delete', 'throw', 'yield', 'await', 'instanceof', 'export', 'default']);

/**
 * The source with the CONTENT of every string, template text and regular expression removed (a string becomes '', a template becomes ``, a regular expression becomes /re/), so that the brackets that are left are
 * code. Expressions inside ${...} are kept as code. One pass, with a stack: a template pushes its text mode, and the expression of a ${ pushes a code mode that ends at its closing brace. Comments must already be stripped.
 */
export function skeleton(src) {
  let out = '';
  let i = 0;
  const n = src.length;
  let prev = ''; // the last significant token: a punctuation character, 'a' for a word or a number, or a keyword
  const regexAllowed = () => prev === '' || /^[(,=:[!&|?{};+\-*%<>~^]$/.test(prev) || KEYWORDS.has(prev);
  // the contexts: 'code' at the bottom; each ${ pushes { braces: 0 } and each ` pushes 'text'
  const stack = [{ type: 'code', braces: 0 }];
  while (i < n) {
    const ctx = stack[stack.length - 1];
    if (ctx.type === 'text') {
      const c = src[i];
      if (c === '\\') i += 2;
      else if (c === '`') {
        out += '`';
        i += 1;
        stack.pop();
        prev = '`';
      } else if (c === '$' && src[i + 1] === '{') {
        out += '${';
        i += 2;
        stack.push({ type: 'code', braces: 0 });
        prev = '{';
      } else i += 1;
      continue;
    }
    const c = src[i];
    if (c === "'" || c === '"') {
      i += 1;
      while (i < n && src[i] !== c) i += src[i] === '\\' ? 2 : 1;
      i += 1;
      out += c + c;
      prev = c;
    } else if (c === '`') {
      out += '`';
      i += 1;
      stack.push({ type: 'text' });
    } else if (c === '/' && regexAllowed() && src[i + 1] !== '/' && src[i + 1] !== '*') {
      let j = i + 1;
      let inClass = false;
      while (j < n) {
        const d = src[j];
        if (d === '\\') j += 2;
        else if (d === '\n') break;
        else if (inClass) {
          if (d === ']') inClass = false;
          j += 1;
        } else if (d === '[') {
          inClass = true;
          j += 1;
        } else if (d === '/') break;
        else j += 1;
      }
      if (j < n && src[j] === '/') {
        j += 1;
        while (j < n && /[a-z]/.test(src[j])) j += 1;
        out += '/re/';
        i = j;
        prev = ')';
      } else {
        out += c;
        i += 1;
        prev = c;
      }
    } else if (/[A-Za-z_$]/.test(c)) {
      const m = /^[A-Za-z_$][\w$]*/.exec(src.slice(i, i + 60));
      out += m[0];
      i += m[0].length;
      prev = KEYWORDS.has(m[0]) ? m[0] : 'a';
    } else if (/\d/.test(c)) {
      const m = /^[\w.]+/.exec(src.slice(i, i + 60));
      out += m[0];
      i += m[0].length;
      prev = 'a';
    } else {
      if (c === '{') ctx.braces += 1;
      else if (c === '}') {
        if (ctx.braces === 0 && stack.length > 1) {
          // the end of a ${ expression: back to the template text
          out += '}';
          i += 1;
          stack.pop();
          prev = '}';
          continue;
        }
        ctx.braces -= 1;
      }
      out += c;
      i += 1;
      if (!/\s/.test(c)) prev = c;
    }
  }
  return out;
}

/** Index of the bracket that closes the one opened at `open` in skeleton text; -1 when unbalanced. */
function closeOf(text, open) {
  const pairs = { '(': ')', '[': ']', '{': '}' };
  const stack = [pairs[text[open]]];
  for (let i = open + 1; i < text.length; i += 1) {
    const c = text[i];
    if (pairs[c]) stack.push(pairs[c]);
    else if (c === stack[stack.length - 1]) {
      stack.pop();
      if (stack.length === 0) return i;
    }
  }
  return -1;
}

/** The expression just before index `end` (an identifier path with calls and brackets), as written, with white space folded. */
function receiverBefore(text, end) {
  let i = end;
  while (i > 0 && /\s/.test(text[i - 1])) i -= 1;
  const stop = i;
  while (i > 0) {
    const c = text[i - 1];
    if (/[\w$.]/.test(c)) i -= 1;
    else if (c === ')' || c === ']') {
      const open = c === ')' ? '(' : '[';
      let depth = 0;
      let j = i - 1;
      for (; j >= 0; j -= 1) {
        if (text[j] === c) depth += 1;
        else if (text[j] === open) {
          depth -= 1;
          if (depth === 0) break;
        }
      }
      if (j < 0) break;
      i = j;
    } else if (/\s/.test(c)) {
      // white space inside a chain is only a line break next to a dot (`ui.x` newline `.y`); anywhere else it ends the receiver
      let k = i - 1;
      while (k > 0 && /\s/.test(text[k - 1])) k -= 1;
      if (text[k - 1] === '.' || text[i] === '.') i = k;
      else break;
    } else break;
  }
  return text.slice(i, stop).replace(/\s+/g, ' ').trim();
}

/** Every computed member access of the (skeleton of the) source: { receiver, key, kind } where kind is 'number', 'string' or 'expression'. */
export function computedAccesses(code) {
  const sk = skeleton(code);
  const out = [];
  for (let i = 0; i < sk.length; i += 1) {
    if (sk[i] !== '[') continue;
    let j = i;
    while (j > 0 && /\s/.test(sk[j - 1])) j -= 1;
    const prev = sk[j - 1];
    if (prev === undefined || !/[\w$)\]]/.test(prev)) continue; // an array literal, not a member access
    const receiver = receiverBefore(sk, i);
    const last = receiver.split(/[^\w$]/).filter(Boolean).pop();
    if (KEYWORDS.has(last) && receiver === last) continue; // `return [..]`, `typeof [..]`, `const [a, b]`, `of [..]`
    const close = closeOf(sk, i);
    if (close < 0) continue;
    const key = sk.slice(i + 1, close).replace(/\s+/g, ' ').trim();
    const kind = /^\d+$/.test(key) ? 'number' : key === "''" || key === '""' ? 'string' : 'expression';
    out.push({ receiver, key, kind });
  }
  return out;
}

/** The computed accesses with a key that is not a literal, as `receiver[key]` strings, sorted, with duplicates counted: ['a[b] x2', ...]. */
export function expressionAccesses(code) {
  const count = new Map();
  for (const a of computedAccesses(code)) if (a.kind === 'expression') count.set(`${a.receiver}[${a.key}]`, (count.get(`${a.receiver}[${a.key}]`) || 0) + 1);
  return [...count.entries()].sort(([x], [y]) => (x < y ? -1 : 1)).map(([k, n]) => (n > 1 ? `${k} x${n}` : k));
}

/** The prototype and descriptor doors: what the module must not use anywhere. */
export const PROTOTYPE_DOORS = Object.freeze([
  /\bgetPrototypeOf\b/, /\bsetPrototypeOf\b/, /\bgetOwnPropertyNames\b/, /\bgetOwnPropertyDescriptors?\b/, /\bgetOwnPropertySymbols\b/, /\bdefineProperty\b/, /\bdefineProperties\b/,
  /\.__proto__\b/, /\[\s*['"`]__proto__['"`]\s*\]/, /\.constructor\b/, /\.prototype\b/, /\bfor\s*\(\s*(?:const|let|var)?\s*[\w$]+\s+in\s/, /\bObject\s*\.\s*(?:entries|values|fromEntries|assign)\b.*\bprototype\b/,
  /\bSymbol\b/, /\bReflect\b/, /\bWeakRef\b/,
]);
/** The doors found in the source. The one use of a prototype that is allowed is the hasOwn helper (Object.prototype.hasOwnProperty.call), which the static test pins to exactly one place. */
export const doorsIn = (code) => {
  const sk = skeleton(code).replace(/Object\.prototype\.hasOwnProperty\.call/g, 'hasOwnCall');
  return PROTOTYPE_DOORS.filter((re) => re.test(sk)).map(String);
};
