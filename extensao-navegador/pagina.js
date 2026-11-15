// Funções injetadas nas páginas com chrome.scripting.executeScript (rodam no contexto da página,
// por isso não podem usar nada de fora delas).

// Marca os elementos interativos visíveis com data-ultron-ref e devolve a lista + o texto.
export function lerPagina(modo) {
  const SEL = 'a[href], button, input:not([type=hidden]), textarea, select, summary, [role=button], [role=link], ' +
    '[role=tab], [role=menuitem], [role=checkbox], [role=radio], [role=switch], [role=option], [role=combobox], ' +
    '[role=textbox], [contenteditable=""], [contenteditable=true], [onclick], [tabindex]:not([tabindex="-1"])';
  const visivel = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05;
  };
  const limpo = (t, n = 80) => (t || '').replace(/\s+/g, ' ').trim().slice(0, n);
  const rotulo = (el) => {
    const id = el.getAttribute('aria-labelledby');
    const rotuloPorId = id && document.getElementById(id)?.innerText;
    const label = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText;
    return limpo(el.getAttribute('aria-label') || rotuloPorId || label || el.innerText || el.value ||
      el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('alt') ||
      el.querySelector('img[alt]')?.alt || el.getAttribute('name') || '');
  };
  let saida = { titulo: document.title, url: location.href };
  if (modo !== 'pagina') {
    let n = Number(document.documentElement.dataset.ultronN || 0);
    const linhas = [];
    for (const el of document.querySelectorAll(SEL)) {
      if (!visivel(el) || el.closest('[aria-hidden=true]')) continue;
      if (!el.dataset.ultronRef) el.dataset.ultronRef = 'r' + (++n);
      const tag = el.tagName.toLowerCase();
      const papel = el.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'input' ? `campo ${el.type}` :
        tag === 'textarea' ? 'campo texto' : el.isContentEditable ? 'campo editável' : tag);
      let extra = '';
      if (tag === 'a') extra = ' → ' + limpo(el.getAttribute('href'), 100);
      if ('value' in el && tag !== 'button' && el.value && el.type !== 'password') extra += ` = "${limpo(el.value, 60)}"`;
      if (el.checked) extra += ' [marcado]';
      if (el.disabled) extra += ' [desativado]';
      linhas.push(`[${el.dataset.ultronRef}] ${papel} "${rotulo(el)}"${extra}`);
      if (linhas.length >= 400) break;
    }
    document.documentElement.dataset.ultronN = n;
    saida.interativos = linhas.join('\n');
  }
  if (modo !== 'interativos') {
    saida.texto = (document.body?.innerText || '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim().slice(0, 30000);
  }
  return saida;
}

// Centro do elemento na tela (para o clique pelo protocolo de depuração), já rolado para a vista.
export function localizar(ref) {
  const el = document.querySelector(`[data-ultron-ref="${ref}"]`);
  if (!el) return { erro: `elemento ${ref} não existe mais (leia a página de novo)` };
  el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
  const r = el.getBoundingClientRect();
  const rotulo = (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('placeholder') || '')
    .replace(/\s+/g, ' ').trim().slice(0, 60);
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, rotulo };
}

export function focarCampo(ref, limpar, texto) {
  const el = document.querySelector(`[data-ultron-ref="${ref}"]`);
  if (!el) return { erro: `elemento ${ref} não existe mais (leia a página de novo)` };
  el.scrollIntoView({ block: 'center', behavior: 'instant' });
  if (el.tagName === 'SELECT') {      // lista: escolhe a opção pelo texto
    const alvo = texto.trim().toLowerCase();
    const op = [...el.options].find((o) => o.text.trim().toLowerCase() === alvo || o.value.toLowerCase() === alvo)
      || [...el.options].find((o) => o.text.toLowerCase().includes(alvo));
    if (!op) return { erro: `opção "${texto}" não existe nessa lista` };
    el.value = op.value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { feito: true };
  }
  el.focus();
  if (limpar) {
    if ('value' in el && el.tagName !== 'BUTTON') {
      el.select?.();
    } else if (el.isContentEditable) {
      const s = getSelection(); const r = document.createRange();
      r.selectNodeContents(el); s.removeAllRanges(); s.addRange(r);
    }
  } else if (el.isContentEditable) {
    const s = getSelection(); const r = document.createRange();
    r.selectNodeContents(el); r.collapse(false); s.removeAllRanges(); s.addRange(r);
  }
  return { ok: true };
}

export function rolar(direcao, ref) {
  if (ref) {
    const el = document.querySelector(`[data-ultron-ref="${ref}"]`);
    if (!el) return { erro: `elemento ${ref} não existe mais` };
    el.scrollIntoView({ block: 'center' });
    return { ok: true };
  }
  const h = innerHeight * 0.85;
  if (direcao === 'cima') scrollBy(0, -h);
  else if (direcao === 'topo') scrollTo(0, 0);
  else if (direcao === 'fim') scrollTo(0, document.documentElement.scrollHeight);
  else scrollBy(0, h);
  return { ok: true };
}
