const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const script = fs.readFileSync(__dirname + '/../web/n1-ipad-audio.js', 'utf8');

async function check(hasSession, rejectResume = false) {
  let ready, clicked, button, starts = 0, stops = 0;
  const contexts = [];
  class AudioContext {
    constructor() { this.state = 'suspended'; this.currentTime = 1; this.destination = {}; this.resumes = 0; contexts.push(this); }
    resume() { this.resumes++; if (rejectResume) return Promise.reject(new Error('blocked')); this.state = 'running'; return Promise.resolve(); }
    createOscillator() { return {frequency: {}, connect(gain) { return gain; }, disconnect() {}, start() { starts++; }, stop() { stops++; this.onended(); }}; }
    createGain() { return {gain: {setValueAtTime() {}, exponentialRampToValueAtTime() {}}, connect() {}, disconnect() {}}; }
  }
  const navigator = hasSession ? {audioSession: {type: 'auto'}} : {};
  const context = {window: {AudioContext}, navigator, document: {
    addEventListener(name, fn) { assert.equal(name, 'DOMContentLoaded'); ready = fn; },
    createElement(name) { assert.equal(name, 'button'); return {style: {}, addEventListener(name, fn) { assert.equal(name, 'click'); clicked = fn; }}; },
    body: {appendChild(node) { button = node; }}
  }};
  vm.runInNewContext(script, context);
  assert.equal(button, undefined);
  // The viewer creates its audio contexts after the classic helper script has run.
  const a = new context.window.AudioContext(), b = new context.window.AudioContext();
  ready();
  assert(button.textContent.includes('试听'));
  const promise = clicked();
  assert.equal(a.resumes, 1); assert.equal(b.resumes, 1); // Still inside the click gesture.
  await promise;
  if (hasSession) assert.equal(navigator.audioSession.type, 'playback');
  assert.equal(starts, rejectResume ? 0 : 1);
  assert.equal(stops, starts);
  assert(button.textContent.includes(rejectResume ? '再点一次' : '声音已启用'));
}

(async () => {
  await check(true); await check(false); await check(true, true);
  vm.runInNewContext(script, {window: {}}); // Browsers without Web Audio keep the viewer usable.
  console.log('iPad helper resumes viewer contexts within the click, handles unsupported/blocked audio, and plays one short tone: OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
