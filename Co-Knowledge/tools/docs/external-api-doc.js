(() => {
  const sidebar = document.getElementById('sidebar');
  const menuToggle = document.getElementById('menuToggle');
  const printBtn = document.getElementById('printBtn');
  const search = document.getElementById('tocSearch');
  const toc = document.getElementById('toc');
  const progress = document.getElementById('progress');
  const toTop = document.getElementById('toTop');
  const scrim = document.getElementById('scrim');

  function setSidebar(open) {
    sidebar?.classList.toggle('open', open);
    scrim?.classList.toggle('show', open);
  }

  if (menuToggle) {
    menuToggle.addEventListener('click', () => setSidebar(!sidebar.classList.contains('open')));
    document.addEventListener('click', (event) => {
      if (window.innerWidth <= 980 && sidebar.classList.contains('open')
          && !sidebar.contains(event.target) && !menuToggle.contains(event.target)) {
        setSidebar(false);
      }
    });
  }
  scrim?.addEventListener('click', () => setSidebar(false));

  if (printBtn) printBtn.addEventListener('click', () => window.print());
  if (toTop) toTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

  // 目录搜索
  if (search && toc) {
    const empty = document.createElement('div');
    empty.className = 'toc-empty';
    empty.textContent = '没有匹配的章节';
    toc.parentNode.appendChild(empty);
    search.addEventListener('input', () => {
      const query = search.value.trim().toLowerCase();
      let matches = 0;
      toc.querySelectorAll('li.toc-h2').forEach((group) => {
        const groupText = (group.dataset.text || '').toLowerCase();
        const children = group.querySelectorAll('li.toc-h3');
        const childMatch = [...children].some((child) =>
          (child.dataset.text || '').toLowerCase().includes(query));
        const showGroup = !query || groupText.includes(query) || childMatch;
        group.style.display = showGroup ? '' : 'none';
        if (showGroup) matches += 1;
        children.forEach((child) => {
          const childText = (child.dataset.text || '').toLowerCase();
          child.style.display = !query || groupText.includes(query)
            || childText.includes(query) ? '' : 'none';
        });
      });
      empty.style.display = matches ? 'none' : 'block';
    });
  }

  // 目录点击（移动端关闭抽屉）
  if (toc) {
    toc.addEventListener('click', (event) => {
      if (event.target.closest('a') && window.innerWidth <= 980) {
        setSidebar(false);
      }
    });
  }

  // 滚动高亮 + 阅读进度
  const headings = [...document.querySelectorAll('.content h2, .content h3')];
  const linkById = new Map();
  if (toc) {
    toc.querySelectorAll('a[href^="#"]').forEach((link) => {
      linkById.set(link.getAttribute('href').slice(1), link);
    });
  }
  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      if (progress) {
        progress.style.width = `${max > 0 ? Math.min(100, (window.scrollY / max) * 100) : 0}%`;
      }
      if (toTop) toTop.classList.toggle('show', window.scrollY > 900);
      let active = null;
      for (const heading of headings) {
        if (heading.getBoundingClientRect().top <= 110) active = heading;
        else break;
      }
      toc?.querySelectorAll('.toc-item.active').forEach((item) => item.classList.remove('active'));
      if (active) {
        const link = linkById.get(active.id);
        link?.closest('li')?.classList.add('active');
        link?.closest('li.toc-h3')?.closest('li.toc-h2')?.classList.add('active');
      }
      ticking = false;
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // 代码复制
  document.querySelectorAll('pre').forEach((pre) => {
    const button = document.createElement('button');
    button.className = 'copy-btn';
    button.type = 'button';
    button.textContent = '复制';
    button.addEventListener('click', async () => {
      const code = pre.querySelector('code');
      const text = code ? code.innerText : pre.innerText;
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = '已复制';
      } catch {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        area.remove();
        button.textContent = '已复制';
      }
      setTimeout(() => { button.textContent = '复制'; }, 1500);
    });
    pre.appendChild(button);
  });

  // 外链新窗口
  document.querySelectorAll('.content a[href^="http"]').forEach((link) => {
    if (link.origin !== location.origin) {
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
    }
  });

  // 快捷键 / 聚焦目录搜索
  document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) {
      event.preventDefault();
      search?.focus();
      if (window.innerWidth <= 980) setSidebar(true);
    }
  });
})();
