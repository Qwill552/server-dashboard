import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { basicSetup, EditorView } from "codemirror";
import { Compartment } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { markdown } from "@codemirror/lang-markdown";
import { StreamLanguage } from "@codemirror/language";
import { shell } from "@codemirror/legacy-modes/mode/shell";

const $ = (id) => document.getElementById(id);
const encoder = new TextEncoder();
const isLight = () => document.documentElement.dataset.theme === "light";
const terminalThemes = {
  dark: { background: "#0b1018", foreground: "#eaf1f4", cursor: "#b5ec85", selectionBackground: "#477b5b88" },
  light: { background: "#f8fbf9", foreground: "#1d312b", cursor: "#287c4d", selectionBackground: "#9bcaaa88" },
};

async function request(url, options) {
  const response = await fetch(url, { cache: "no-store", credentials: "same-origin", ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
  return data;
}

function message(id, value) { $(id).textContent = value; }

// A real PTY receives raw keystrokes and returns output without polling.
const terminal = new Terminal({
  cursorBlink: true,
  convertEol: false,
  fontFamily: '"Cascadia Code", Consolas, monospace',
  fontSize: 13,
  scrollback: 5000,
  theme: terminalThemes[isLight() ? "light" : "dark"],
});
const fit = new FitAddon();
terminal.loadAddon(fit);
terminal.open($("terminal-screen"));
let socket = null;
let activePanel = "terminal";

function fitTerminal() {
  if (activePanel !== "terminal") return;
  fit.fit();
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }));
  }
}

function connectTerminal() {
  if (socket) socket.close();
  terminal.write("\r\nПодключение к серверу…\r\n");
  message("terminal-status", "Подключение…");
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const connection = new WebSocket(`${protocol}//${location.host}/ws/terminal`);
  let serverError = false;
  connection.binaryType = "arraybuffer";
  socket = connection;
  connection.onopen = () => {
    if (socket !== connection) return;
    message("terminal-status", "Терминал подключён");
    fitTerminal();
    terminal.focus();
  };
  connection.onmessage = (event) => {
    if (socket !== connection) return;
    if (event.data instanceof ArrayBuffer) {
      terminal.write(new Uint8Array(event.data));
    } else {
      try {
        const control = JSON.parse(event.data);
        if (control.type === "error") {
          serverError = true;
          message("terminal-status", control.message);
          terminal.writeln(`\r\n${control.message}`);
        }
      } catch (_) { /* Ignore unknown control messages. */ }
    }
  };
  connection.onclose = () => {
    if (socket !== connection) return;
    if (!serverError) {
      message("terminal-status", "Соединение закрыто");
      terminal.write("\r\n[Соединение закрыто. Нажмите «Переподключить».]\r\n");
    }
  };
  connection.onerror = () => { if (socket === connection) message("terminal-status", "Ошибка соединения"); };
}

terminal.onData((data) => {
  if (socket?.readyState === WebSocket.OPEN) socket.send(encoder.encode(data));
});
new ResizeObserver(fitTerminal).observe($("terminal-screen"));
$("terminal-reconnect").addEventListener("click", connectTerminal);

document.querySelectorAll(".management-tab").forEach((button) => {
  button.addEventListener("click", () => {
    activePanel = button.dataset.panel;
    document.querySelectorAll(".management-tab").forEach((item) => {
      const selected = item === button;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-selected", String(selected));
      $(`${item.dataset.panel}-panel`).hidden = !selected;
    });
    if (activePanel === "terminal") requestAnimationFrame(fitTerminal);
  });
});

// Files: tabs retain their editor state, including undo history.
const tabs = new Map();
let selectedFile = null;
let directory = "/etc";

function languageFor(path) {
  const extension = path.split(".").pop()?.toLowerCase();
  if (extension === "py") return python();
  if (["js", "mjs", "cjs", "ts", "tsx", "jsx"].includes(extension)) return javascript({ typescript: extension?.startsWith("t"), jsx: extension?.endsWith("x") });
  if (["json", "jsonc"].includes(extension)) return json();
  if (["css", "scss"].includes(extension)) return css();
  if (["html", "htm", "xml", "svg"].includes(extension)) return html();
  if (["md", "markdown"].includes(extension)) return markdown();
  if (["sh", "bash", "zsh", "service", "conf"].includes(extension)) return StreamLanguage.define(shell);
  return [];
}

function renderTabs() {
  const row = $("editor-tabs");
  row.replaceChildren();
  for (const [path, tab] of tabs) {
    const group = document.createElement("div");
    group.className = `editor-tab${path === selectedFile ? " active" : ""}`;
    const select = document.createElement("button");
    select.type = "button";
    select.textContent = `${path.split(/[\\/]/).pop()}${tab.dirty ? " ●" : ""}`;
    select.title = path;
    select.addEventListener("click", () => selectTab(path));
    const close = document.createElement("button");
    close.type = "button";
    close.className = "editor-tab-close";
    close.textContent = "×";
    close.setAttribute("aria-label", `Закрыть ${path}`);
    close.addEventListener("click", () => closeTab(path));
    group.append(select, close);
    row.append(group);
  }
}

function selectTab(path) {
  if (!tabs.has(path)) return;
  selectedFile = path;
  for (const [name, tab] of tabs) tab.container.hidden = name !== path;
  message("editor-path", path);
  $("file-save").disabled = false;
  $("file-reload").disabled = false;
  renderTabs();
  loadBackups(path);
  tabs.get(path).view.focus();
}

function closeTab(path, force = false) {
  const tab = tabs.get(path);
  if (!tab) return;
  if (tab.dirty && !force && !confirm(`Закрыть ${path} без сохранения?`)) return;
  tab.view.destroy();
  tab.container.remove();
  tabs.delete(path);
  if (selectedFile === path) {
    selectedFile = null;
    const next = tabs.keys().next().value;
    if (next) selectTab(next);
    else {
      message("editor-path", "Выберите файл слева");
      $("file-save").disabled = true;
      $("file-reload").disabled = true;
      $("backup-list").replaceChildren(new Option("Нет открытого файла"));
      $("backup-list").disabled = true;
      $("backup-open").disabled = true;
    }
  }
  renderTabs();
}

function addEditor(data) {
  const { path, content, revision } = data;
  if (tabs.has(path)) { selectTab(path); return; }
  const container = document.createElement("div");
  container.className = "editor-instance";
  container.hidden = true;
  $("editor-container").append(container);
  const themeSlot = new Compartment();
  const tab = { path, revision, original: content, dirty: false, container, themeSlot, view: null };
  tab.view = new EditorView({
    doc: content,
    parent: container,
    extensions: [
      basicSetup,
      languageFor(path),
      themeSlot.of(isLight() ? [] : oneDark),
      keymap.of([{ key: "Mod-s", run: () => { saveFile(path); return true; } }]),
      EditorView.updateListener.of((update) => {
        if (!update.docChanged) return;
        tab.dirty = update.state.doc.toString() !== tab.original;
        renderTabs();
      }),
    ],
  });
  tabs.set(path, tab);
  selectTab(path);
}

async function loadDirectory(path) {
  try {
    const data = await request(`/api/files?path=${encodeURIComponent(path)}`);
    directory = data.path;
    $("file-path").value = directory;
    const list = $("file-list");
    list.replaceChildren();
    for (const entry of data.entries) {
      const button = document.createElement("button");
      button.type = "button";
      button.title = entry.path;
      const icon = document.createElement("span");
      icon.textContent = entry.directory ? "▸" : "·";
      const name = document.createElement("div");
      name.textContent = entry.name;
      name.style.overflow = "hidden";
      name.style.textOverflow = "ellipsis";
      button.append(icon, name);
      button.addEventListener("click", () => entry.directory ? loadDirectory(entry.path) : openFile(entry.path));
      list.append(button);
    }
    message("file-status", `${data.entries.length} элементов${data.truncated ? " · показаны первые 1000" : ""}`);
  } catch (error) { message("file-status", error.message); }
}

async function openFile(path) {
  if (tabs.has(path)) { selectTab(path); return; }
  try {
    addEditor(await request(`/api/file?path=${encodeURIComponent(path)}`));
    message("file-status", `Открыт ${path}`);
  } catch (error) { message("file-status", error.message); }
}

async function saveFile(path = selectedFile) {
  const tab = tabs.get(path);
  if (!tab) return;
  try {
    const content = tab.view.state.doc.toString();
    const data = await request("/api/file", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content, revision: tab.revision }),
    });
    tab.revision = data.revision;
    tab.original = content;
    tab.dirty = false;
    renderTabs();
    loadBackups(path);
    message("file-status", `Сохранено: ${path}${data.backup ? " · предыдущая версия в копиях" : ""}`);
  } catch (error) { message("file-status", error.message); }
}

async function loadBackups(path) {
  const select = $("backup-list");
  select.replaceChildren(new Option("Загрузка…"));
  select.disabled = true;
  $("backup-open").disabled = true;
  try {
    const data = await request(`/api/backups?path=${encodeURIComponent(path)}`);
    if (selectedFile !== path) return;
    select.replaceChildren();
    if (!data.backups.length) select.add(new Option("Копий пока нет"));
    for (const item of data.backups) select.add(new Option(item.id.replace("T", " ").replace("Z-", " · "), item.id));
    select.disabled = !data.backups.length;
    $("backup-open").disabled = !data.backups.length;
  } catch (error) { message("file-status", error.message); }
}

$("file-path-form").addEventListener("submit", (event) => { event.preventDefault(); loadDirectory($("file-path").value); });
$("file-parent").addEventListener("click", () => loadDirectory(directory.replace(/[\\/]?[^\\/]+[\\/]?$/, "") || "/"));
$("file-new").addEventListener("click", () => {
  const name = prompt("Имя или абсолютный путь нового файла:");
  if (!name) return;
  const path = name.startsWith("/") ? name : `${directory.replace(/\/$/, "")}/${name}`;
  addEditor({ path, content: "", revision: null });
  message("file-status", "Новый файл будет создан при сохранении");
});
$("file-save").addEventListener("click", () => saveFile());
$("file-reload").addEventListener("click", async () => {
  if (!selectedFile) return;
  const path = selectedFile;
  if (tabs.get(path).dirty && !confirm("Загрузить файл заново и потерять несохранённые изменения?")) return;
  closeTab(path, true);
  await openFile(path);
});
$("backup-open").addEventListener("click", async () => {
  if (!selectedFile) return;
  try {
    const data = await request(`/api/backup?path=${encodeURIComponent(selectedFile)}&id=${encodeURIComponent($("backup-list").value)}`);
    const view = tabs.get(selectedFile).view;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: data.content } });
    message("file-status", "Копия загружена в редактор. Нажмите «Сохранить» для восстановления.");
  } catch (error) { message("file-status", error.message); }
});

// Slash commands are stored server-side and can run Bash, a file, then open a URL.
let macros = [];
let selectedMacro = null;

function macroByName(name) { return macros.find((item) => item.name === name); }

function renderMacroList() {
  const list = $("macro-list");
  list.replaceChildren();
  for (const macro of macros) {
    const button = document.createElement("button");
    button.type = "button";
    button.classList.toggle("selected", macro.name === selectedMacro);
    const title = document.createElement("strong");
    title.textContent = `/${macro.name}`;
    const subtitle = document.createElement("small");
    subtitle.textContent = macro.label || macro.command || macro.file;
    button.append(title, subtitle);
    button.addEventListener("click", () => selectMacro(macro.name));
    list.append(button);
  }
}

function selectMacro(name) {
  const macro = macroByName(name);
  if (!macro) return;
  selectedMacro = name;
  $("macro-name").value = name;
  $("macro-label").value = macro.label;
  $("macro-command").value = macro.command;
  $("macro-file").value = macro.file;
  $("macro-url").value = macro.open_url;
  renderMacroList();
  message("macro-status", `Выбран /${name}`);
}

async function loadMacros(preferred) {
  try {
    macros = (await request("/api/macros")).macros;
    renderMacroList();
    if (preferred && macroByName(preferred)) selectMacro(preferred);
    else if (!selectedMacro && macros.length) selectMacro(macros[0].name);
  } catch (error) { message("macro-status", error.message); }
}

function clearMacro() {
  selectedMacro = null;
  $("macro-form").reset();
  renderMacroList();
  message("macro-status", "Новый макрос");
  $("macro-name").focus();
}

async function runMacro(name, outputId = "macro-output") {
  const macro = macroByName(name);
  if (!macro) {
    const output = $(outputId);
    output.hidden = false;
    output.textContent = `Макрос /${name} не найден`;
    message("macro-status", output.textContent);
    return;
  }
  // The tab must be opened directly from the submit/click gesture to avoid popup blocking.
  const destination = macro.open_url ? window.open("about:blank", "_blank") : null;
  if (destination) destination.opener = null;
  message("macro-status", `Выполняется /${name}…`);
  const output = $(outputId);
  output.hidden = false;
  output.textContent = `/${name}\nВыполнение…`;
  try {
    const result = await request(`/api/macros/${encodeURIComponent(name)}/run`, { method: "POST" });
    output.textContent = result.output || `/${name}: выполнено`;
    message("macro-status", result.success ? `/${name}: выполнено` : `/${name}: код ${result.exit_code}`);
    if (destination) {
      if (result.success && result.open_url) destination.location.replace(result.open_url);
      else destination.close();
    }
  } catch (error) {
    if (destination) destination.close();
    output.textContent = error.message;
    message("macro-status", error.message);
  }
}

$("macro-new").addEventListener("click", clearMacro);
$("macro-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = $("macro-name").value.trim();
  try {
    await request(`/api/macros/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: $("macro-label").value,
        command: $("macro-command").value,
        file: $("macro-file").value,
        open_url: $("macro-url").value,
      }),
    });
    selectedMacro = name;
    await loadMacros(name);
    message("macro-status", `/${name} сохранён`);
  } catch (error) { message("macro-status", error.message); }
});
$("macro-run").addEventListener("click", () => selectedMacro && runMacro(selectedMacro));
$("macro-delete").addEventListener("click", async () => {
  if (!selectedMacro || !confirm(`Удалить /${selectedMacro}?`)) return;
  try {
    await request(`/api/macros/${encodeURIComponent(selectedMacro)}`, { method: "DELETE" });
    clearMacro();
    await loadMacros();
  } catch (error) { message("macro-status", error.message); }
});
$("command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("command-input");
  const command = input.value.trim();
  if (!command) return;
  input.value = "";
  if (/^\/[a-z][a-z0-9_-]*$/.test(command)) {
    runMacro(command.slice(1), "command-output");
  } else if (socket?.readyState === WebSocket.OPEN) {
    socket.send(encoder.encode(`${command}\n`));
    terminal.focus();
  } else {
    const output = $("command-output");
    output.hidden = false;
    output.textContent = "Терминал не подключён";
  }
});

new MutationObserver(() => {
  terminal.options.theme = terminalThemes[isLight() ? "light" : "dark"];
  for (const tab of tabs.values()) tab.view.dispatch({ effects: tab.themeSlot.reconfigure(isLight() ? [] : oneDark) });
}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

request("/api/console/status").then((status) => {
  message("console-status", status.privileged ? "Права администратора" : status.terminal_available ? "Требуется настройка прав на VPS" : "Терминал доступен на Linux VPS");
  if (status.privileged) connectTerminal();
  else message("terminal-status", status.terminal_available ? "Настройте права сервиса на VPS" : "Терминал доступен на Linux VPS");
}).catch((error) => message("console-status", error.message));
loadDirectory(directory);
loadMacros();
