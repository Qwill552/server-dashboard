"use strict";

const $ = (id) => document.getElementById(id);
const number = (value, digits = 0) => Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits });
const bytes = (value, digits = 1) => {
  if (!Number.isFinite(value)) return "—";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let amount = Math.max(0, value);
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit++; }
  return `${number(amount, amount < 10 ? digits : 0)} ${units[unit]}`;
};
const speed = (value) => `${bytes(value)}/с`;
const duration = (seconds) => {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return days ? `${days} д. ${hours} ч.` : hours ? `${hours} ч. ${minutes} мин.` : `${minutes} мин.`;
};
const setText = (id, value) => { $(id).textContent = value; };
const setProgress = (id, value) => { $(id).style.width = `${Math.min(100, Math.max(0, Number(value) || 0))}%`; };

function setConnection(state, label) {
  const badge = $("overall-badge");
  badge.classList.remove("is-online", "is-offline");
  if (state === "online" || state === "offline") badge.classList.add(`is-${state}`);
  badge.querySelector("span:last-child").textContent = label;
  $("sidebar-status").className = `status-light ${state}`;
  document.querySelector(".live-pulse").className = `live-pulse ${state}`;
  setText("connection-text", state === "online" ? "Прямой эфир" : label);
}

function linePath(values, max, height) {
  if (!values.length) return "";
  const count = values.length;
  const bounded = Math.max(1, max);
  return values.map((value, index) => {
    const x = count === 1 ? 600 : (index / (count - 1)) * 600;
    const y = height - Math.min(1, Math.max(0, value / bounded)) * (height - 2) - 1;
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
}

function renderCharts(history) {
  const points = history.slice(-240);
  const cpu = points.map((point) => point.cpu);
  const memory = points.map((point) => point.memory);
  const cpuPath = linePath(cpu, 100, 180);
  $("cpu-line").setAttribute("d", cpuPath);
  $("memory-line").setAttribute("d", linePath(memory, 100, 180));
  $("cpu-area").setAttribute("d", cpuPath ? `${cpuPath} L600 180 L0 180 Z` : "");

  const received = points.map((point) => point.network_receive);
  const sent = points.map((point) => point.network_send);
  const maxTraffic = Math.max(1024, ...received, ...sent) * 1.15;
  $("network-in-line").setAttribute("d", linePath(received, maxTraffic, 120));
  $("network-out-line").setAttribute("d", linePath(sent, maxTraffic, 120));
}

function render(data) {
  const { current: m, history } = data;
  const stale = Date.now() - m.timestamp > 15000;
  setConnection(stale ? "offline" : "online", stale ? "Данные устарели" : "Данные поступают");
  setText("sidebar-host", m.host);
  setText("hero-uptime", duration(m.uptime_seconds));
  setText("hero-cores", number(m.cpu.cores));
  setText("cpu-value", number(m.cpu.percent, 1));
  setText("cpu-sub", `${m.cpu.cores} vCPU · load ${m.cpu.load.length ? m.cpu.load[0] : "—"}`);
  setProgress("cpu-progress", m.cpu.percent);
  setText("memory-value", number(m.memory.percent, 1));
  setText("memory-sub", `${bytes(m.memory.used)} из ${bytes(m.memory.total)}`);
  setProgress("memory-progress", m.memory.percent);
  setText("disk-value", number(m.disk.percent, 1));
  setText("disk-sub", `${bytes(m.disk.used)} из ${bytes(m.disk.total)}`);
  setProgress("disk-progress", m.disk.percent);

  if (m.temperature_c == null) {
    setText("temp-value", "Н/Д");
    setText("temp-unit", "");
    setText("temp-sub", "Датчик CPU недоступен на VPS");
    setProgress("temp-progress", 0);
  } else {
    setText("temp-value", number(m.temperature_c, 1));
    setText("temp-unit", "°C");
    setText("temp-sub", "Датчик CPU");
    setProgress("temp-progress", m.temperature_c);
  }

  setText("network-in", speed(m.network.receive_bps));
  setText("network-out", speed(m.network.send_bps));
  const caddy = $("caddy-badge");
  caddy.className = `service-badge ${m.caddy.state}`;
  caddy.innerHTML = "<span></span>";
  caddy.append(document.createTextNode(m.caddy.state === "online" ? "Работает" : m.caddy.state === "offline" ? "Остановлен" : "Неизвестно"));
  setText("caddy-detail", m.caddy.detail);
  setText("fact-host", m.host);
  setText("fact-platform", m.platform);
  setText("fact-frequency", m.cpu.frequency_mhz ? `${number(m.cpu.frequency_mhz)} МГц` : "Недоступно");
  setText("fact-load", m.cpu.load.length ? m.cpu.load.join(" · ") : "Недоступно");
  setText("fact-disk-io", `${speed(m.disk.read_bps)} / ${speed(m.disk.write_bps)}`);
  setText("last-update", `Обновлено: ${new Date(m.timestamp).toLocaleTimeString("ru-RU")}`);
  renderCharts(history);
}

let latestTimestamp = 0;
async function refresh() {
  try {
    const response = await fetch("/api/metrics", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    latestTimestamp = data.current.timestamp;
    render(data);
  } catch (_error) {
    setConnection("offline", "Нет связи с сервером");
    if (latestTimestamp) setText("last-update", `Последние данные: ${new Date(latestTimestamp).toLocaleTimeString("ru-RU")}`);
  } finally {
    window.setTimeout(refresh, 3000);
  }
}

function updateClock() { setText("current-time", new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })); }
updateClock();
window.setInterval(updateClock, 30000);
refresh();
