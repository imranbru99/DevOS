/* Local workspace tools: commands use the existing allowlisted launcher. */
(() => {
  'use strict';
  const dialog = document.getElementById('command-dialog');
  const search = document.getElementById('command-search');
  const results = document.getElementById('command-results');
  const commands = [
    ...[['overview', 'Overview', 'System health and workspace'], ['security', 'Security', 'PIN and sign-in'],
      ['storage', 'Storage & disks', 'Volumes and disk tools'], ['subsystems', 'Subsystems', 'Compatibility tools'],
      ['firstboot', 'Setup wizard', 'Language and first steps']].map(([id, title, detail]) => ({title, detail, run: () => switchTab(id)})),
    ...[['browser', 'Browser'], ['files', 'Files'], ['code', 'Code editor'], ['terminal', 'Terminal'],
      ['settings', 'Settings'], ['notepad', 'Notepad'], ['pdf', 'PDF reader']].map(([id, title]) => ({title, detail: 'Open application', run: () => launchApp(id)})),
  ];
  let selected = 0;
  let matches = [];
  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    matches = commands.filter(c => `${c.title} ${c.detail}`.toLocaleLowerCase().includes(query));
    selected = 0;
    results.replaceChildren();
    matches.forEach((command, index) => {
      const button = document.createElement('button');
      button.className = 'command-result';
      const title = document.createElement('strong');
      title.textContent = command.title;
      const detail = document.createElement('span');
      detail.textContent = command.detail;
      button.append(title, detail);
      button.addEventListener('click', () => { dialog.close(); command.run(); });
      button.addEventListener('focus', () => { selected = index; highlight(); });
      results.append(button);
    });
    if (!matches.length) {
      const empty = document.createElement('p');
      empty.className = 'command-empty';
      empty.textContent = 'No commands found. Try “files” or “settings”.';
      results.append(empty);
    }
    highlight();
  }
  function highlight() {
    [...results.querySelectorAll('button')].forEach((button, i) => button.classList.toggle('selected', i === selected));
  }
  function open() { if (!dialog.open) dialog.showModal(); search.value = ''; render(); search.focus(); }
  document.getElementById('command-open').addEventListener('click', open);
  document.getElementById('command-close').addEventListener('click', () => dialog.close());
  search.addEventListener('input', render);
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault(); dialog.open ? dialog.close() : open();
    }
  });
  dialog.addEventListener('keydown', event => {
    if (['ArrowDown', 'ArrowUp'].includes(event.key) && matches.length) {
      event.preventDefault();
      selected = (selected + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length;
      highlight();
      results.children[selected].focus();
    } else if (event.key === 'Enter' && event.target === search && matches[selected]) {
      event.preventDefault(); dialog.close(); matches[selected].run();
    }
  });

  const duration = 25 * 60 * 1000;
  let remaining = duration;
  let deadline = null;
  const toggle = document.getElementById('focus-toggle');
  function draw() {
    if (deadline !== null) {
      remaining = Math.max(0, deadline - Date.now());
      if (!remaining) {
        deadline = null;
        document.getElementById('workspace-announcement').textContent = 'Focus session complete. Time for a break.';
      }
    }
    const seconds = Math.ceil(remaining / 1000);
    document.getElementById('focus-time').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    toggle.textContent = deadline !== null ? 'Pause focus' : remaining === duration ? 'Start focus' : remaining ? 'Resume focus' : 'Start again';
  }
  toggle.addEventListener('click', () => {
    if (deadline !== null) { remaining = Math.max(0, deadline - Date.now()); deadline = null; }
    else { if (!remaining) remaining = duration; deadline = Date.now() + remaining; }
    draw();
  });
  document.getElementById('focus-reset').addEventListener('click', () => { deadline = null; remaining = duration; draw(); });
  setInterval(draw, 1000);
  draw();
})();
