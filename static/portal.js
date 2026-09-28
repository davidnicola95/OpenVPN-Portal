document.querySelectorAll('[data-reveal]').forEach(button => {
  button.addEventListener('click', () => { const input = document.getElementById(button.dataset.reveal); const show = input.type === 'password'; input.type = show ? 'text' : 'password'; button.textContent = show ? 'Hide' : 'Show'; button.setAttribute('aria-pressed', String(show)); button.setAttribute('aria-label', `${show ? 'Hide' : 'Show'} ${input.labels[0].textContent.toLowerCase()}`); });
});
let pendingForm = null;
const dialog = document.getElementById('confirm-dialog');
document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
  if (form.dataset.confirmed === 'yes') return;
  event.preventDefault(); pendingForm = form;
  document.getElementById('confirm-title').textContent = form.dataset.confirmLabel;
  document.getElementById('confirm-message').textContent = form.dataset.confirm;
  document.getElementById('confirm-submit').textContent = form.dataset.confirmLabel;
  dialog.showModal();
}));
dialog.addEventListener('close', () => { if (dialog.returnValue === 'confirm' && pendingForm) { pendingForm.dataset.confirmed = 'yes'; pendingForm.requestSubmit(); } pendingForm = null; });
document.querySelectorAll('form[data-busy]').forEach(form => form.addEventListener('submit', event => {
  if (event.defaultPrevented) return;
  const button = form.querySelector('button[type="submit"]');
  if (button) { button.disabled = true; button.textContent = form.dataset.busy; }
}));
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
document.querySelectorAll('[data-search]').forEach(input => input.addEventListener('input', () => {
  const table = document.getElementById(input.dataset.search); let count = 0;
  table.querySelectorAll('[data-search-row]').forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(input.value.trim().toLowerCase()); if (!row.hidden) count++; });
  table.closest('.panel').querySelector('.search-empty').hidden = count > 0 || !input.value;
}));