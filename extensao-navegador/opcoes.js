const token = document.getElementById('token');
const porta = document.getElementById('porta');
const status = document.getElementById('status');

chrome.storage.local.get({ porta: 8766, token: '' }).then((c) => {
  token.value = c.token;
  porta.value = c.porta;
});

document.getElementById('salvar').onclick = async () => {
  await chrome.storage.local.set({ token: token.value.trim(), porta: Number(porta.value) || 8766 });
  status.textContent = 'Salvo. Conectando…';
  setTimeout(() => (status.textContent = 'Salvo.'), 2500);
};
