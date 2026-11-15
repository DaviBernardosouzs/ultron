// Painel lateral: conversa com o Ultron e responde às confirmações das ações.
const conversa = document.getElementById('conversa');
const form = document.getElementById('form');
const caixa = document.getElementById('texto');
const estado = document.getElementById('estado');
const aviso = document.getElementById('aviso');
let porta;
let esperando = null;      // balão "pensando" da pergunta em andamento

function ligar() {
  porta = chrome.runtime.connect({ name: 'painel' });
  porta.onMessage.addListener(receber);
  porta.onDisconnect.addListener(() => setTimeout(ligar, 500));   // service worker reiniciou
}

function balao(classe, texto) {
  conversa.querySelector('.vazio')?.remove();
  const d = document.createElement('div');
  d.className = 'msg ' + classe;
  d.textContent = texto;
  conversa.append(d);
  conversa.scrollTop = conversa.scrollHeight;
  return d;
}

function receber(m) {
  if (m.tipo === 'estado') {
    estado.classList.toggle('on', m.conectado);
    estado.title = m.conectado ? 'conectado ao Ultron' : (m.motivo || 'desconectado');
    aviso.hidden = m.conectado;
    if (!m.conectado) {
      aviso.innerHTML = '';
      aviso.append(`Sem conexão com o Ultron: ${m.motivo || 'ponte fora do ar'}. `);
      const a = document.createElement('a');
      a.href = '#'; a.textContent = 'Opções';
      a.onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };
      aviso.append(a);
    }
  } else if (m.tipo === 'progresso') {
    balao('progresso', '· ' + m.texto);
  } else if (m.tipo === 'chat_resposta') {
    if (esperando) { esperando.remove(); esperando = null; }
    balao('ultron', m.texto);
    caixa.disabled = false; caixa.focus();
  } else if (m.tipo === 'confirmar') {
    confirmar(m);
  }
}

function confirmar(m) {
  conversa.querySelector('.vazio')?.remove();
  const d = document.createElement('div');
  d.className = 'confirmar';
  d.innerHTML = '<div class="nivel"></div><p></p><div class="botoes"></div>';
  d.querySelector('.nivel').textContent = m.nivel === 'N3' ? 'AÇÃO CRÍTICA · N3' : 'CONFIRMAR · ' + m.nivel;
  d.querySelector('p').textContent = m.acao;
  const botoes = d.querySelector('.botoes');
  const responder = (resposta) => {
    porta.postMessage({ tipo: 'confirmacao', id: m.id, resposta });
    botoes.querySelectorAll('button, input').forEach((b) => (b.disabled = true));
    d.style.opacity = .6;
  };
  const botao = (rotulo, classe, resposta) => {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = rotulo; b.className = classe;
    b.onclick = () => responder(typeof resposta === 'function' ? resposta() : resposta);
    botoes.append(b);
  };
  if (m.pin) {
    const pin = document.createElement('input');
    pin.type = 'password'; pin.placeholder = 'PIN'; pin.size = 8; pin.inputMode = 'numeric';
    pin.onkeydown = (e) => { if (e.key === 'Enter') responder(pin.value); };
    botoes.append(pin);
    botao('Confirmar', 'sim', () => pin.value);
  } else {
    botao('Sim', 'sim', 'sim');
    if (m.nivel === 'N2') botao('Sempre', '', 'sempre');
  }
  botao('Não', 'nao', 'nao');
  conversa.append(d);
  conversa.scrollTop = conversa.scrollHeight;
  (botoes.querySelector('input') || botoes.querySelector('button')).focus();
}

form.onsubmit = (e) => {
  e.preventDefault();
  const texto = caixa.value.trim();
  if (!texto || caixa.disabled) return;
  balao('eu', texto);
  esperando = balao('ultron pensando', '');
  porta.postMessage({ tipo: 'chat', id: crypto.randomUUID(), texto });
  caixa.value = ''; caixa.style.height = '';
  caixa.disabled = true;
};

caixa.onkeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
};
caixa.oninput = () => { caixa.style.height = ''; caixa.style.height = caixa.scrollHeight + 'px'; };

ligar();
