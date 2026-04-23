/**
 * components.js — Shell compartilhado do Motor Conect.
 *
 * Injeta sidebar, user footer e utilitários de auth via DOM.
 * Fonte ÚNICA de verdade para navegação — adicionar/remover item de menu
 * aqui propaga automaticamente para todas as páginas.
 *
 * Uso em qualquer HTML:
 *   <script src="components.js"></script>
 *   → Sidebar injetada no elemento com id="sidebar-root"
 *   → Se não existir, cria automaticamente dentro de .app-container
 */

(function () {
  'use strict';

  // ─── Configuração do Menu ─────────────────────────────────────────
  // Estrutura canônica: adicionar/remover links AQUI e todas as páginas refletem.
  const NAV_ITEMS = [
    { href: 'dashboard.html',         icon: 'layout-grid', label: 'Dashboard' },
    { href: 'analise_unificada.html',  icon: 'file-text',   label: 'Nova Auditoria' },
    { href: 'historico.html',          icon: 'history',     label: 'Histórico' },
    { href: 'integracoes.html',        icon: 'database',    label: 'Integrações' },
  ];

  const GESTAO_ITEMS = [
    { href: 'admin.html',             icon: 'users',       label: 'Usuários' },
    { href: 'configuracoes.html',      icon: 'settings',    label: 'Configurações' },
  ];

  // ─── Detectar página ativa ────────────────────────────────────────
  function currentPage() {
    const path = window.location.pathname;
    const file = path.substring(path.lastIndexOf('/') + 1) || 'dashboard.html';
    return file;
  }

  // ─── Gerar HTML da sidebar ────────────────────────────────────────
  function buildSidebar() {
    const active = currentPage();

    const navLinks = NAV_ITEMS.map(item => {
      const isActive = active === item.href ? ' active' : '';
      return `<a href="${item.href}" class="nav-link${isActive}">
        <i data-lucide="${item.icon}" style="width: 18px;"></i> ${item.label}
      </a>`;
    }).join('\n');

    const gestaoLinks = GESTAO_ITEMS.map(item => {
      const isActive = active === item.href ? ' active' : '';
      return `<a href="${item.href}" class="nav-link${isActive}">
        <i data-lucide="${item.icon}" style="width: 18px;"></i> ${item.label}
      </a>`;
    }).join('\n');

    // Dados do usuário logado (sessionStorage populado pelo login)
    const username = sessionStorage.getItem('username') || 'Administrador';
    const role = sessionStorage.getItem('role') || 'Manager';
    const initials = username.substring(0, 2).toUpperCase();

    return `
    <aside class="sidebar" id="mc-sidebar">
      <div class="p-6 mb-8 flex-row items-center gap-3">
        <div style="width: 32px; height: 32px; background: var(--action-primary); border-radius: 8px; display: flex; align-items: center; justify-content: center;">
          <i data-lucide="zap" style="color: white; width: 18px; height: 18px;"></i>
        </div>
        <div>
          <h1 style="font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em;">Motor Conect</h1>
          <p class="text-muted" style="font-size: 0.65rem; text-transform: uppercase;">Inteligência Contábil</p>
        </div>
      </div>

      <nav style="flex: 1;">
        ${navLinks}

        <div class="mt-8 px-8 mb-2">
          <p class="text-muted" style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em;">Gestão</p>
        </div>
        ${gestaoLinks}
      </nav>

      <div class="p-6 border-t" style="border-color: var(--border-subtle);">
        <div class="flex-row gap-3 items-center">
          <div class="mc-avatar" id="mc-userAvatar">${initials}</div>
          <div style="flex: 1; overflow: hidden;">
            <p id="mc-userName" style="font-size: 0.85rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${username}</p>
            <p id="mc-userRole" class="text-muted" style="font-size: 0.7rem;">${role}</p>
          </div>
          <a href="login.html" class="text-muted" title="Sair" id="mc-logout">
            <i data-lucide="log-out" style="width: 16px;"></i>
          </a>
        </div>
      </div>
    </aside>`;
  }

  // ─── Injetar na página ────────────────────────────────────────────
  function injectSidebar() {
    // Páginas sem sidebar (login, resultado)
    const page = currentPage();
    const noSidebar = ['login.html', 'resultado.html', 'cronograma.html'];
    if (noSidebar.includes(page)) return;

    // Remove sidebar inline (se existir) para evitar duplicação
    const existingSidebar = document.querySelector('.sidebar');
    if (existingSidebar) {
      existingSidebar.remove();
    }

    // Insere a sidebar centralizada
    const container = document.querySelector('.app-container');
    if (!container) return;

    container.insertAdjacentHTML('afterbegin', buildSidebar());

    // Re-renderiza ícones Lucide após injeção
    if (typeof lucide !== 'undefined' && lucide.createIcons) {
      lucide.createIcons();
    }
  }

  // ─── Logout handler ───────────────────────────────────────────────
  function setupLogout() {
    const btn = document.getElementById('mc-logout');
    if (!btn) return;
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      sessionStorage.removeItem('token');
      sessionStorage.removeItem('username');
      sessionStorage.removeItem('role');
      window.location.href = 'login.html';
    });
  }

  // ─── Auth guard (redireciona se não logado) ───────────────────────
  function authGuard() {
    const page = currentPage();
    const publicPages = ['login.html'];
    if (publicPages.includes(page)) return;

    const token = sessionStorage.getItem('token');
    if (!token) {
      // Sem token → redireciona para login
      window.location.href = 'login.html';
    }
  }

  // ─── Toast utility (disponível globalmente) ───────────────────────
  window.mcToast = function (msg, type) {
    type = type || 'success';
    let container = document.getElementById('mc-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'mc-toast-container';
      container.style.cssText = 'position:fixed;bottom:2rem;right:2rem;z-index:1000;display:flex;flex-direction:column;gap:0.5rem;';
      document.body.appendChild(container);
    }
    const colors = {
      success: 'rgba(0, 179, 126, 0.15)',
      error: 'rgba(226, 88, 88, 0.15)',
      info: 'rgba(10, 132, 255, 0.15)',
    };
    const toast = document.createElement('div');
    toast.style.cssText = `background:var(--color-gray-900);border:1px solid var(--border-subtle);color:white;padding:1rem 1.5rem;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,0.5);border-left:4px solid ${type === 'error' ? 'var(--color-red-500)' : type === 'info' ? 'var(--color-blue-500)' : 'var(--color-green-500)'};font-size:0.85rem;animation:fadeSlideUp 0.3s ease-out;`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(function () { toast.remove(); }, 4000);
  };

  // ─── API helper (token automático) ────────────────────────────────
  window.mcFetch = function (url, options) {
    options = options || {};
    options.headers = options.headers || {};
    const token = sessionStorage.getItem('token');
    if (token) {
      options.headers['Authorization'] = 'Bearer ' + token;
    }
    return fetch(url, options);
  };

  // ─── Submit lock (anti duplo-clique + spinner seguro) ─────────────
  //
  // Envolve operação async e garante:
  //   1. Botão desabilitado durante execução (flag reentrante em dataset.locked).
  //   2. Cliques adicionais ignorados até a promise resolver/rejeitar.
  //   3. Reabilitação SEMPRE via finally — nenhum erro deixa UI travada.
  //   4. onStart/onEnd opcionais para spinner, visibility, classes CSS.
  //
  // Uso:
  //   await mcWithSubmitLock('btn-processar', async () => {
  //     await mcFetch('/analise/pdf', { method: 'POST', body: fd });
  //   }, { onStart: showSpinner, onEnd: hideSpinner });
  window.mcWithSubmitLock = async function (btnId, fn, hooks) {
    hooks = hooks || {};
    const btn = (typeof btnId === 'string') ? document.getElementById(btnId) : btnId;
    if (!btn) {
      // Sem botão: ainda assim roda a função, mas sem lock.
      return await fn();
    }
    if (btn.dataset.mcLocked === '1') {
      // Já em execução — ignora re-entry. Retorna undefined.
      return undefined;
    }
    btn.dataset.mcLocked = '1';
    const originalDisabled = btn.disabled;
    btn.disabled = true;
    try {
      if (typeof hooks.onStart === 'function') hooks.onStart();
      return await fn();
    } finally {
      btn.dataset.mcLocked = '0';
      btn.disabled = originalDisabled;
      if (typeof hooks.onEnd === 'function') hooks.onEnd();
    }
  };

  // ─── Boot ─────────────────────────────────────────────────────────
  // Roda assim que o DOM estiver pronto
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  function boot() {
    authGuard();
    injectSidebar();
    setupLogout();
  }

})();
