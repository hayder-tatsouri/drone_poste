(() => {
  const listeners = [];
  let last = null;

  const $ = (id) => document.getElementById(id);
  const num = (v, d = 1) => (v == null || Number.isNaN(v) ? "n/a" : Number(v).toFixed(d));

  function toast(text, kind = "ok") {
    let box = $("toasts");
    if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = text;
    box.appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  async function api(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      let msg = data.detail;
      if (Array.isArray(msg)) msg = "Altitude must be between 1 and " + (last ? last.max_alt : "the limit") + " m";
      throw new Error(msg || "Request failed (" + res.status + ")");
    }
    return data;
  }

  function setLink(stateName, text) {
    const el = $("link");
    if (!el) return;
    el.dataset.state = stateName;
    el.querySelector(".text").textContent = text;
  }

  function render(d) {
    if (d.connected) setLink("ok", "Drone linked");
    else setLink("warn", "Drone offline");

    const set = (id, text, cls) => {
      const el = $(id);
      if (!el) return;
      el.textContent = text;
      el.classList.remove("ok", "warn");
      if (cls) el.classList.add(cls);
    };
    set("s-batt", d.battery_v == null ? "n/a" : num(d.battery_v, 2) + " V");
    const fix = d.fix ? d.fix.replace(/_/g, " ").toLowerCase() : "no data";
    set("s-gps", d.sats == null ? "n/a" : d.sats + " sats, " + fix, d.global_ok ? "ok" : "warn");
    set("s-alt", d.rel_alt == null ? "n/a" : num(d.rel_alt, 1) + " m");
    set("s-speed", d.speed == null ? "n/a" : num(d.speed, 1) + " m/s");
    set("s-mode", d.mode || "n/a");
    set("s-armed", d.armed ? "Armed" : "Disarmed", d.armed ? "warn" : null);
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const ws = new WebSocket(proto + location.host + "/ws");
    ws.onmessage = (ev) => {
      last = JSON.parse(ev.data);
      render(last);
      listeners.forEach((fn) => fn(last));
    };
    ws.onclose = () => { setLink("bad", "Server offline"); setTimeout(connect, 1500); };
    ws.onerror = () => ws.close();
  }

  window.DronePi = { $, num, api, toast, onTelemetry: (fn) => listeners.push(fn), last: () => last };
  connect();
})();
