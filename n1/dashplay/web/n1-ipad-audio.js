/* Local iPad speaker check. The original DashPlay viewer remains unchanged. */
(() => {
  const contexts = new Set();
  const NativeAudioContext = window.AudioContext || window.webkitAudioContext;
  if (!NativeAudioContext) return;
  class TrackedAudioContext extends NativeAudioContext {
    constructor(...args) { super(...args); contexts.add(this); }
  }
  window.AudioContext = TrackedAudioContext;
  if (window.webkitAudioContext) window.webkitAudioContext = TrackedAudioContext;
  function playbackSession() {
    try {
      if (navigator.audioSession) navigator.audioSession.type = "playback";
    } catch (_) {}
  }
  playbackSession();
  document.addEventListener("DOMContentLoaded", () => {
    const button = document.createElement("button");
    button.id = "n1-ipad-speaker-check";
    button.type = "button";
    button.textContent = "试听 iPad 扬声器";
    button.style.cssText = "position:fixed;left:max(12px,env(safe-area-inset-left));top:max(12px,env(safe-area-inset-top));z-index:100000;padding:10px 14px;border:0;border-radius:10px;background:#087cf0;color:white;font:600 15px system-ui;box-shadow:0 2px 12px #0005";
    button.addEventListener("click", async () => {
      playbackSession();
      let context = [...contexts].find(c => c.state !== "closed");
      if (!context) context = new TrackedAudioContext();
      // Resume synchronously within the user's gesture. The viewer also receives
      // this click and runs its own media-element unlock handler.
      const resumes = [...contexts].filter(c => c.state !== "closed").map(c => c.resume());
      try {
        await Promise.all(resumes);
        const now = context.currentTime;
        const tone = context.createOscillator();
        const gain = context.createGain();
        tone.frequency.value = 660;
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.06, now + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.18);
        tone.connect(gain).connect(context.destination);
        tone.onended = () => { tone.disconnect(); gain.disconnect(); };
        tone.start(now); tone.stop(now + 0.2);
        button.textContent = "声音已启用 · 再次试听";
      } catch (_) {
        button.textContent = "未启用声音，请再点一次";
      }
    });
    document.body.appendChild(button);
  }, { once: true });
})();
