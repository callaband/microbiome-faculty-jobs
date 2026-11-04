// Visitor statistics for this site, using GoatCounter (https://www.goatcounter.com):
// free for non-commercial sites, no cookies, no personal data collected.
//
// To turn it on, put your GoatCounter site code between the quotes below. It's the
// part before ".goatcounter.com" in your dashboard's address: for
// https://mfjobs.goatcounter.com you would write "mfjobs".
// Leave it empty to turn counting off.
const GOATCOUNTER_CODE = "mfjobs";

(() => {
  const code = GOATCOUNTER_CODE.trim();
  // Pages that fill in their content after loading (a position page) count themselves
  // once the content is known, so the dashboard shows the position's title.
  const manual = !!(document.currentScript && document.currentScript.dataset.manual === "true");
  window.MFJ_track = () => {};
  if (!/^[a-z0-9-]+$/i.test(code)) return;
  if (location.protocol === "file:" || /^(localhost|127\.|\[::1\])/.test(location.hostname)) return; // don't count local previews

  window.goatcounter = manual ? { no_onload: true } : {};
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://gc.zgo.at/count.js";
  s.setAttribute("data-goatcounter", "https://" + code + ".goatcounter.com/count");
  const ready = new Promise(resolve => { s.onload = resolve; s.onerror = () => resolve(); });
  document.head.appendChild(s);

  window.MFJ_track = title => ready.then(() => {
    const gc = window.goatcounter;
    if (gc && typeof gc.count === "function") {
      gc.count({ path: location.pathname + location.search, title: title || document.title });
    }
  });
})();
