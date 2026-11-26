// Tiny static server for the local preview harness (no dependencies).
// Serves this card's directory so preview/index.html can load dist/ and
// examples/. Local use only: binds 127.0.0.1.
//
//   node preview/serve.mjs [port] [assetsDir]   default 8765; assetsDir (optional) is served at /assets/
//   (used to show a locally held scene plate without copying it into the repository)

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const port = Number(process.argv[2] ?? 8765);
const assets = process.argv[3] ? resolve(process.argv[3]) : null;
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".yaml": "text/plain; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", "http://localhost");
    let path = decodeURIComponent(url.pathname);
    if (path === "/") path = "/preview/index.html";
    let base = root;
    if (path.startsWith("/assets/")) {
      if (!assets) throw new Error("no assets dir");
      base = assets;
      path = path.slice("/assets".length);
    }
    const file = normalize(join(base, path));
    if (!file.startsWith(base)) {
      res.writeHead(403).end();
      return;
    }
    const s = await stat(file);
    if (!s.isFile()) throw new Error("not a file");
    const body = await readFile(file);
    res.writeHead(200, { "content-type": types[extname(file)] ?? "application/octet-stream", "cache-control": "no-store" });
    res.end(body);
  } catch {
    res.writeHead(404, { "content-type": "text/plain" }).end("not found");
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`ECCO 3D Energy Flow preview: http://127.0.0.1:${port}/preview/index.html?s=day-export` + (assets ? `  (assets: ${assets})` : ""));
});
