(() => {
  const presets = {
    queue: ['assets/queue-panel.png', 'NAS音乐器完整播放队列，支持拖动排序、随机和循环', '下一首听什么，由你决定。拖动调整顺序，退出后还能接着听。'],
    effects: ['assets/effects-panel.png', 'NAS音乐器九种实时音效和原声选项', '低频、人声、空间感。九种音效，也保留回到原声的自由。'],
    search: ['assets/musicbox-overview.png', 'NAS音乐器综合搜索结果和同曲音源入口', '综合搜索，先找到的先出现。同版本聚在一起，选源也更方便。'],
  };
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function select(tab) {
    tabs.forEach(item => {
      item.setAttribute('aria-selected', String(item === tab));
      item.tabIndex = item === tab ? 0 : -1;
    });
    const [src, alt, caption] = presets[tab.dataset.image];
    const image = document.getElementById('app-preview');
    image.src = src; image.alt = alt;
    document.getElementById('preview-panel').setAttribute('aria-labelledby', tab.id);
    document.getElementById('preview-caption').textContent = caption;
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const target = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      select(target); target.focus();
    });
  });
  document.querySelectorAll('[aria-disabled="true"]').forEach(link => link.addEventListener('click', event => {
    if (link.getAttribute('aria-disabled') === 'true') event.preventDefault();
  }));
  fetch('release.json', {cache:'no-store'}).then(response => {
    if (!response.ok) throw new Error('Version unavailable');
    return response.json();
  }).then(release => {
    document.querySelectorAll('[data-version]').forEach(item => { item.textContent = release.version; });
    const mode = new URLSearchParams(location.search).get('downloads') || release.downloadMode || 'auto';
    const localHost = ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname);
    // A query string must never expose paths that exist only on the owner's PC.
    const local = localHost && mode !== 'public';
    const available = local ? release.localDownloadsReady : release.published;
    document.getElementById('release-status').textContent = available ? (local ? '新版安装包 · 本地预览' : '可下载') : '新版准备中 · 暂未公开发布';
    for (const kind of ['installer', 'portable']) {
      const asset = release[kind];
      const link = document.getElementById(`${kind}-download`);
      const candidate = local ? asset.path : asset.publicUrl;
      let valid = false;
      if (candidate) {
        const url = new URL(candidate, location.href);
        valid = local ? url.origin === location.origin && url.pathname.startsWith('/downloads/') : url.protocol === 'https:';
        if (available && valid) { link.href = url.href; link.setAttribute('aria-disabled', 'false'); }
      }
      if (kind === 'installer') link.querySelector('span').textContent = available && valid ? '下载安装版 EXE' : '安装版即将发布';
      if (asset.sizeBytes) {
        const size = `${(asset.sizeBytes / 1024 / 1024).toFixed(1)} MB`;
        document.getElementById(kind === 'installer' ? 'installer-info' : 'portable-size').textContent = kind === 'installer' ? `${size} · 适合日常使用，安装后双击打开` : size;
      }
      if (/^[0-9a-f]{64}$/i.test(asset.sha256 || '')) {
        document.getElementById(`${kind}-hash`).textContent = asset.sha256;
        const copy = document.querySelector(`[data-copy="${kind}"]`);
        copy.disabled = false;
        copy.addEventListener('click', async () => {
          try { await navigator.clipboard.writeText(asset.sha256); document.getElementById('copy-status').textContent = '校验值已复制'; }
          catch { document.getElementById('copy-status').textContent = '请选中上方校验值手动复制'; }
        });
      }
    }
  }).catch(() => { document.getElementById('release-status').textContent = '版本信息暂时不可用，请稍后重试'; });
})();
