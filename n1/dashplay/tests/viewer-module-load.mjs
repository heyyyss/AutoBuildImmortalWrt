// Run the real bootstrap modules with inert player bodies: count initialization
// without needing a browser DOM, a receiver token, or a live CarPlay connection.
import {mkdtemp, readFile, writeFile, readdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const dist = resolve(process.argv[2]);
const html = await readFile(join(dist, 'index.html'), 'utf8');
const entry = html.match(/<script type="module"[^>]+src="\.\/assets\/([^"/]+)"/);
assert.ok(entry, 'Expected module entry in actual HTML');
const dir = await mkdtemp(join(tmpdir(), 'n1-viewer-modules-'));
try {
  await writeFile(join(dir, 'package.json'), '{"type":"module"}');
  for (const name of await readdir(join(dist, 'assets'))) {
    if (!name.endsWith('.js')) continue;
    let code = await readFile(join(dist, 'assets', name), 'utf8');
    if (name.startsWith('main-')) {
      const imports = code.match(/import\{[^}]+\}from["']\.\/index-[^"']+["'];/g);
      assert.equal(imports?.length, 1, 'Player must retain its actual loader import');
      assert.ok(code.includes('w&&Y.connect()'), 'Pinned player starts its socket at top level');
      code = imports.join('\n') + `\nglobalThis.playerStarts.push(${JSON.stringify(name)});\n`;
    }
    await writeFile(join(dir, name), code);
  }
  globalThis.document = {createElement: () => ({relList: {supports: () => true}})};
  globalThis.playerStarts = [];
  let ready, failure;
  const started = new Promise((resolve, reject) => {ready = resolve; failure = reject;});
  let readyCalls = 0;
  globalThis.window = {F50BrowserCheck: {done: true, allowed: true,
    appReady() {readyCalls++; ready();}, appFailed() {failure(new Error('Bootstrap failed'));}}};
  globalThis.fetch = async () => ({ok: false});
  await import(pathToFileURL(join(dir, entry[1])).href);
  await Promise.race([started, new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error('Bootstrap timed out')), 5000);
    timer.unref();
  })]);
  // Both loaders start asynchronous imports; let all their continuations finish.
  await new Promise(resolve => setTimeout(resolve, 150));
  assert.equal(playerStarts.length, 1, `Expected one player, started: ${playerStarts.join(', ')}`);
  assert.equal(readyCalls, 1, 'Expected one bootstrap completion');
  console.log(JSON.stringify({playerStarts, readyCalls}));
} finally {
  await rm(dir, {recursive: true, force: true});
}
