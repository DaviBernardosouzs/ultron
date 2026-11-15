// Ultron in Chrome — service worker: conexão com a ponte do Ultron (core/navegador.py),
// execução dos comandos nas abas e meio de campo com o painel lateral.
import { lerPagina, localizar, focarCampo, rolar } from './pagina.js';

let ws = null;
let conectado = false;
const paineis = new Set();            // portas abertas do painel lateral
const anexados = new Set();           // abas com o depurador ligado
const consoles = new Map();           // aba -> [linhas]
const redes = new Map();              // aba -> Map(requestId -> requisição)

// ------------------------------------------------------------------ conexão com a ponte
async function config() {
  const c = await chrome.storage.local.get({ porta: 8766, token: '' });
  return c;
}

function avisarPaineis(msg) {
  for (const p of paineis) { try { p.postMessage(msg); } catch (e) { /* painel fechou */ } }
}

function mudarEstado(ok, motivo = '') {
  conectado = ok;
  chrome.action.setBadgeText({ text: ok ? '' : '!' });
  chrome.action.setBadgeBackgroundColor({ color: '#C8102E' });
  avisarPaineis({ tipo: 'estado', conectado: ok, motivo });
}

async function conectar() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const { porta, token } = await config();
  if (!token) { mudarEstado(false, 'sem token: abra as opções da extensão'); return; }
  try {
    ws = new WebSocket(`ws://127.0.0.1:${porta}/extensao?token=${encodeURIComponent(token)}`);
  } catch (e) { mudarEstado(false, String(e)); return; }
  ws.onopen = () => mudarEstado(true);
  ws.onclose = (ev) => {
    ws = null;
    mudarEstado(false, ev.code === 4401 ? 'token recusado pela ponte' : 'ponte do Ultron fora do ar');
    if (ev.code !== 4000) setTimeout(conectar, 4000);
  };
  ws.onerror = () => {};
  ws.onmessage = (ev) => tratar(JSON.parse(ev.data));
}

function enviar(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

// mantém o service worker vivo enquanto conectado (Chrome 116+) e reconecta se cair
setInterval(() => enviar({ tipo: 'ping' }), 20000);
chrome.alarms.create('ultron-vigia', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => conectar());
chrome.runtime.onStartup.addListener(conectar);
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  conectar();
});
chrome.storage.onChanged.addListener(() => { if (ws) ws.close(4000); ws = null; conectar(); });

async function tratar(msg) {
  if (msg.tipo === 'comando') {
    try {
      const resultado = await (COMANDOS[msg.acao] || (() => { throw new Error(`ação desconhecida: ${msg.acao}`); }))(msg.args || {});
      enviar({ tipo: 'resposta', id: msg.id, ok: true, resultado });
    } catch (e) {
      enviar({ tipo: 'resposta', id: msg.id, ok: false, erro: String(e?.message || e) });
    }
  } else if (msg.tipo === 'confirmar') {
    if (!paineis.size) { enviar({ tipo: 'confirmacao', id: msg.id, resposta: 'nao' }); return; }
    avisarPaineis(msg);
  } else if (msg.tipo === 'chat_resposta' || msg.tipo === 'progresso') {
    avisarPaineis(msg);
  }
}

// ------------------------------------------------------------------ painel lateral
chrome.runtime.onConnect.addListener((porta) => {
  if (porta.name !== 'painel') return;
  paineis.add(porta);
  porta.postMessage({ tipo: 'estado', conectado });
  conectar();
  porta.onDisconnect.addListener(() => paineis.delete(porta));
  porta.onMessage.addListener(async (m) => {
    if (m.tipo === 'chat') {
      const a = await abaAtiva().catch(() => null);
      enviar({ tipo: 'chat', id: m.id, texto: m.texto, aba: a ? { titulo: a.title, url: a.url } : null });
    } else if (m.tipo === 'confirmacao') {
      enviar({ tipo: 'confirmacao', id: m.id, resposta: m.resposta });
    } else if (m.tipo === 'reconectar') {
      conectar();
    }
  });
});

// ------------------------------------------------------------------ abas
async function abaAtiva() {
  const [a] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!a) throw new Error('nenhuma aba ativa');
  return a;
}

async function aba(id) {
  return id ? chrome.tabs.get(Number(id)) : abaAtiva();
}

function scriptavel(a) {
  if (!/^(https?|file):/.test(a.url || '')) {
    throw new Error(`não dá para agir nesta página (${a.url || 'sem endereço'}): páginas internas do navegador são protegidas`);
  }
}

function esperarCarregar(id, limite = 30000) {
  return new Promise((ok) => {
    const fim = setTimeout(() => { chrome.tabs.onUpdated.removeListener(ouvir); ok(); }, limite);
    function ouvir(tid, info) {
      if (tid === id && info.status === 'complete') {
        clearTimeout(fim); chrome.tabs.onUpdated.removeListener(ouvir); setTimeout(ok, 400);
      }
    }
    chrome.tabs.onUpdated.addListener(ouvir);
    chrome.tabs.get(id).then((t) => { if (t.status === 'complete') { clearTimeout(fim); chrome.tabs.onUpdated.removeListener(ouvir); ok(); } });
  });
}

async function naPagina(a, func, ...args) {
  scriptavel(a);
  const [r] = await chrome.scripting.executeScript({ target: { tabId: a.id }, func, args });
  if (r?.result?.erro) throw new Error(r.result.erro);
  return r?.result;
}

// ------------------------------------------------------------------ depurador (CDP)
async function anexar(id) {
  if (!anexados.has(id)) {
    await chrome.debugger.attach({ tabId: id }, '1.3');
    anexados.add(id);
  }
}

const cdp = (id, metodo, params = {}) => chrome.debugger.sendCommand({ tabId: id }, metodo, params);

chrome.debugger.onDetach.addListener(({ tabId }) => anexados.delete(tabId));
chrome.tabs.onRemoved.addListener((id) => { anexados.delete(id); consoles.delete(id); redes.delete(id); });

function guardarConsole(id, linha) {
  const l = consoles.get(id) || [];
  l.push(linha.slice(0, 1500));
  if (l.length > 500) l.shift();
  consoles.set(id, l);
}

const valor = (a) => a.value !== undefined ? (typeof a.value === 'object' ? JSON.stringify(a.value) : String(a.value))
  : (a.description || a.unserializableValue || a.type);

chrome.debugger.onEvent.addListener(({ tabId: id }, metodo, p) => {
  const hora = new Date().toLocaleTimeString('pt-BR');
  if (metodo === 'Runtime.consoleAPICalled') {
    const onde = p.stackTrace?.callFrames?.[0];
    guardarConsole(id, `${hora} [${p.type}] ${p.args.map(valor).join(' ')}` + (onde ? `  (${onde.url}:${onde.lineNumber + 1})` : ''));
  } else if (metodo === 'Runtime.exceptionThrown') {
    const d = p.exceptionDetails;
    guardarConsole(id, `${hora} [exceção] ${d.exception?.description || d.text}  (${d.url || ''}:${(d.lineNumber ?? 0) + 1})`);
  } else if (metodo === 'Log.entryAdded') {
    const e = p.entry;
    guardarConsole(id, `${hora} [${e.level}/${e.source}] ${e.text}` + (e.url ? `  (${e.url})` : ''));
  } else if (metodo.startsWith('Network.')) {
    const m = redes.get(id) || new Map();
    redes.set(id, m);
    if (metodo === 'Network.requestWillBeSent') {
      if (p.request.url.startsWith('data:')) return;
      m.set(p.requestId, { metodo: p.request.method, url: p.request.url, tipo: p.type, inicio: p.timestamp });
      if (m.size > 600) m.delete(m.keys().next().value);
    } else {
      const r = m.get(p.requestId);
      if (!r) return;
      if (metodo === 'Network.responseReceived') { r.status = p.response.status; r.mime = p.response.mimeType; }
      else if (metodo === 'Network.loadingFinished') { r.ms = Math.round((p.timestamp - r.inicio) * 1000); r.bytes = p.encodedDataLength; }
      else if (metodo === 'Network.loadingFailed') { r.falha = p.canceled ? 'cancelada' : p.errorText; r.ms = Math.round((p.timestamp - r.inicio) * 1000); }
    }
  }
});

async function depurar(a, dominios, recarregar) {
  scriptavel(a);
  await anexar(a.id);
  for (const d of dominios) await cdp(a.id, `${d}.enable`);
  if (recarregar) {
    consoles.delete(a.id); redes.delete(a.id);
    await chrome.tabs.reload(a.id);
    await esperarCarregar(a.id);
    await new Promise((r) => setTimeout(r, 1500));
  }
}

const TECLAS = {
  enter: ['Enter', 13, '\r'], escape: ['Escape', 27], esc: ['Escape', 27], tab: ['Tab', 9], backspace: ['Backspace', 8],
  delete: ['Delete', 46], arrowleft: ['ArrowLeft', 37], arrowup: ['ArrowUp', 38], arrowright: ['ArrowRight', 39],
  arrowdown: ['ArrowDown', 40], pageup: ['PageUp', 33], pagedown: ['PageDown', 34], home: ['Home', 36], end: ['End', 35],
  space: [' ', 32, ' '], espaco: [' ', 32, ' '],
};
const MODIF = { alt: 1, ctrl: 2, control: 2, meta: 4, cmd: 4, shift: 8 };
const EDICAO = { a: 'selectAll', c: 'copy', v: 'paste', x: 'cut', z: 'undo', y: 'redo' };

async function tecla(id, combinacao) {
  const partes = combinacao.split('+').map((p) => p.trim());
  let mods = 0;
  for (const p of partes.slice(0, -1)) mods |= MODIF[p.toLowerCase()] || 0;
  const nome = partes.at(-1);
  let [key, codigo, texto] = TECLAS[nome.toLowerCase()] || [nome, nome.length === 1 ? nome.toUpperCase().charCodeAt(0) : 0, nome.length === 1 ? nome : undefined];
  const base = { modifiers: mods, key, windowsVirtualKeyCode: codigo, nativeVirtualKeyCode: codigo };
  if (mods & 2 && EDICAO[key.toLowerCase()]) base.commands = [EDICAO[key.toLowerCase()]];
  const comTexto = texto && !(mods & 2) && !(mods & 4) ? { text: texto, unmodifiedText: texto } : {};
  await cdp(id, 'Input.dispatchKeyEvent', { type: comTexto.text ? 'keyDown' : 'rawKeyDown', ...base, ...comTexto });
  await cdp(id, 'Input.dispatchKeyEvent', { type: 'keyUp', ...base });
}

// ------------------------------------------------------------------ comandos vindos do Ultron
const infoAba = (a) => ({ id: a.id, titulo: a.title, url: a.url });

const COMANDOS = {
  async abas() {
    const ativa = await abaAtiva().catch(() => null);
    return (await chrome.tabs.query({})).map((a) => ({ ...infoAba(a), ativa: a.id === ativa?.id }));
  },

  async abrir({ url, nova_aba = true, aba: id }) {
    let a;
    if (url === 'voltar' || url === 'avancar') {
      a = await aba(id);
      await (url === 'voltar' ? chrome.tabs.goBack(a.id) : chrome.tabs.goForward(a.id));
    } else {
      if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) url = 'https://' + url;
      if (/^(javascript|chrome|brave|about|file):/i.test(url) && !/^about:blank$/i.test(url)) {
        throw new Error('esse tipo de endereço não é aberto pelo Ultron');
      }
      a = nova_aba && !id ? await chrome.tabs.create({ url, active: true })
        : await chrome.tabs.update((await aba(id)).id, { url, active: true });
    }
    await esperarCarregar(a.id);
    return infoAba(await chrome.tabs.get(a.id));
  },

  async focar({ aba: id }) {
    const a = await chrome.tabs.update(Number(id), { active: true });
    await chrome.windows.update(a.windowId, { focused: true });
    return infoAba(a);
  },

  async fechar({ aba: id }) {
    await chrome.tabs.remove(Number(id));
    return { ok: true };
  },

  async ler({ aba: id, modo = 'tudo' }) {
    const a = await aba(id);
    return { id: a.id, ...(await naPagina(a, lerPagina, modo)) };
  },

  async clicar({ ref, aba: id }) {
    const a = await aba(id);
    const p = await naPagina(a, localizar, ref);
    await anexar(a.id);
    const base = { x: p.x, y: p.y, button: 'left', clickCount: 1 };
    await cdp(a.id, 'Input.dispatchMouseEvent', { type: 'mouseMoved', x: p.x, y: p.y });
    await cdp(a.id, 'Input.dispatchMouseEvent', { type: 'mousePressed', ...base });
    await cdp(a.id, 'Input.dispatchMouseEvent', { type: 'mouseReleased', ...base });
    await new Promise((r) => setTimeout(r, 700));
    const depois = await chrome.tabs.get(a.id);
    if (depois.status === 'loading') await esperarCarregar(a.id, 15000);
    return { rotulo: p.rotulo, ...infoAba(await chrome.tabs.get(a.id)) };
  },

  async digitar({ ref, texto, limpar = true, aba: id }) {
    const a = await aba(id);
    if ((await naPagina(a, focarCampo, ref, limpar, texto))?.feito) return { ok: true };
    await anexar(a.id);
    await cdp(a.id, 'Input.insertText', { text: texto });
    return { ok: true };
  },

  async tecla({ tecla: t, aba: id }) {
    const a = await aba(id);
    scriptavel(a);
    await anexar(a.id);
    await tecla(a.id, t);
    await new Promise((r) => setTimeout(r, 400));
    return { ok: true };
  },

  async rolar({ direcao = 'baixo', ref, aba: id }) {
    return naPagina(await aba(id), rolar, direcao, ref || null);
  },

  async captura() {
    const a = await abaAtiva();
    const imagem = await chrome.tabs.captureVisibleTab(a.windowId, { format: 'png' });
    return { imagem, titulo: a.title };
  },

  async console({ aba: id, recarregar = false, so_erros = false }) {
    const a = await aba(id);
    await depurar(a, ['Runtime', 'Log'], recarregar);
    let linhas = consoles.get(a.id) || [];
    if (so_erros) linhas = linhas.filter((l) => /\[(error|exceção|warning|assert)/.test(l));
    return { id: a.id, url: a.url, linhas };
  },

  async rede({ aba: id, recarregar = false, so_erros = false }) {
    const a = await aba(id);
    await depurar(a, ['Network'], recarregar);
    let reqs = [...(redes.get(a.id) || new Map()).values()];
    if (so_erros) reqs = reqs.filter((r) => r.falha || r.status >= 400);
    const linhas = reqs.map((r) => `${r.falha || r.status >= 400 ? '✗' : ' '} ${r.metodo} ${r.falha ? 'FALHOU(' + r.falha + ')' : r.status ?? '…'} ` +
      `${(r.tipo || '').toLowerCase()} ${r.ms != null ? r.ms + 'ms' : ''} ${r.url.slice(0, 220)}`);
    return { id: a.id, url: a.url, linhas };
  },

  async js({ codigo, aba: id }) {
    const a = await aba(id);
    scriptavel(a);
    await anexar(a.id);
    const r = await cdp(a.id, 'Runtime.evaluate', { expression: codigo, returnByValue: true, awaitPromise: true, userGesture: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value !== undefined ? r.result.value : (r.result.description ?? r.result.type);
  },
};

conectar();
