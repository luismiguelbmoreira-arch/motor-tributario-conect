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

  // ─── Fase 4 Segurança/LGPD — Constantes ──────────────────────────
  // Intervalo entre checagens de expiração do JWT. 60s equilibra carga e
  // responsividade (browser pode throttle aba de fundo — tratamos em visibilitychange).
  const JWT_CHECK_INTERVAL_MS = 60 * 1000;
  // Janela de antecipação: se o token expira em menos disso, aciona refresh.
  const JWT_REFRESH_WINDOW_S = 5 * 60;
  // Referência do setInterval de refresh — guardada no escopo do módulo para
  // poder ser limpa no logout. Nunca vira global.
  let _jwtRefreshTimerId = null;

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
  // Blindado para LGPD Art. 46 (segurança) + Art. 6º V (minimização):
  //   1. sessionStorage.clear()  — remove token, username, role, analise_id.
  //   2. localStorage.clear()    — defesa em profundidade (hoje não usamos,
  //                                mas ninguém garante que uma lib futura use).
  //   3. window.__MC_SESSION__   — zera a PII que vive em memória.
  //   4. clearInterval do refresh — evita leak de timer após navegação.
  //   5. Redirect para login.
  function mcLogoutLimpar() {
    try { sessionStorage.clear(); } catch (_) { /* storage indisponível */ }
    try { localStorage.clear(); } catch (_) { /* idem */ }
    if (window.__MC_SESSION__) {
      try { delete window.__MC_SESSION__; } catch (_) {
        // Navegadores antigos podem não aceitar delete em window — sobrescreve.
        window.__MC_SESSION__ = null;
      }
    }
    if (_jwtRefreshTimerId !== null) {
      clearInterval(_jwtRefreshTimerId);
      _jwtRefreshTimerId = null;
    }
  }
  // Exposição pública para que outras páginas possam disparar logout blindado
  // sem duplicar lógica (ex.: timeout detectado no resultado.html).
  window.mcLogout = function () {
    mcLogoutLimpar();
    if (currentPage() !== 'login.html') {
      window.location.href = 'login.html';
    }
  };

  function setupLogout() {
    const btn = document.getElementById('mc-logout');
    if (!btn) return;
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      window.mcLogout();
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

  // ─── API helper único — JWT + 401 global + timeout + erro de rede ────
  //
  // Todo fetch da UI passa por aqui. Garante:
  //   1. Authorization: Bearer <JWT> injetado de sessionStorage.token.
  //   2. 401 → limpa sessão e redireciona para login.html (sem laço de refresh).
  //   3. Timeout default 30s via AbortController (override em options.timeout).
  //   4. Erro de rede (offline, DNS, CORS) → rejeita com mensagem amigável,
  //      sem derrubar a página com TypeError cru.
  //
  // Uso:
  //   const res = await mcFetch('/auth/me');
  //   if (!res.ok) { ... }
  //   const data = await res.json();
  //
  //   // override de timeout:
  //   await mcFetch('/analise/pdf', { method: 'POST', body: fd, timeout: 120000 });
  //
  //   // opt-out do redirect global (ex.: tela de login):
  //   await mcFetch('/auth/login', { method: 'POST', body: ..., skipAuthRedirect: true });
  window.mcFetch = async function (url, options) {
    options = options || {};
    options.headers = options.headers || {};

    const token = sessionStorage.getItem('token');
    if (token && !options.headers['Authorization']) {
      options.headers['Authorization'] = 'Bearer ' + token;
    }

    const timeoutMs = typeof options.timeout === 'number' ? options.timeout : 30000;
    const skipAuthRedirect = options.skipAuthRedirect === true;
    // Remove chaves custom antes de repassar ao fetch nativo
    delete options.timeout;
    delete options.skipAuthRedirect;

    const controller = new AbortController();
    const externalSignal = options.signal;
    options.signal = controller.signal;
    const timer = setTimeout(function () { controller.abort(); }, timeoutMs);
    // Se o chamador passou um signal próprio, encadeia abort
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort();
      else externalSignal.addEventListener('abort', function () { controller.abort(); });
    }

    let response;
    try {
      response = await fetch(url, options);
    } catch (err) {
      clearTimeout(timer);
      if (err && err.name === 'AbortError') {
        const timeoutErr = new Error('Tempo esgotado ao contatar o servidor (' + Math.round(timeoutMs / 1000) + 's).');
        timeoutErr.code = 'TIMEOUT';
        throw timeoutErr;
      }
      const netErr = new Error('Falha de rede ao contatar o servidor. Verifique sua conexão.');
      netErr.code = 'NETWORK';
      netErr.cause = err;
      throw netErr;
    }
    clearTimeout(timer);

    // 401 global → sessão morta. Limpa TUDO e manda pro login.
    // ERR-019 — LGPD Art. 46: removeItem campo a campo deixava analise_empresa,
    // analise_cnpj e diagnostico vivos → vazamento de PII entre contas no
    // mesmo browser. Fase 4: mcLogoutLimpar() inclui window.__MC_SESSION__
    // e clearInterval do refresh timer, não só sessionStorage.
    if (response.status === 401 && !skipAuthRedirect) {
      mcLogoutLimpar();
      if (currentPage() !== 'login.html') {
        window.location.href = 'login.html';
      }
    }
    return response;
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

  // ─── Fase 4 — Decode de JWT client-side (apenas payload, sem validar) ──
  //
  // O backend é a autoridade de assinatura — aqui só lemos o `exp` claim
  // para decidir o timing do refresh. Tentativa de forjar JWT no frontend
  // não engana o backend. Retorna null se token mal-formado.
  //
  // Formato JWT: header.payload.signature (3 partes, base64url).
  function mcDecodeJwtPayload(token) {
    if (!token || typeof token !== 'string') return null;
    const partes = token.split('.');
    if (partes.length !== 3) return null;
    try {
      // base64url → base64 padrão (-/+, _/=)
      let b64 = partes[1].replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) b64 += '=';
      const json = atob(b64);
      return JSON.parse(json);
    } catch (_) {
      return null;
    }
  }
  window.mcDecodeJwtPayload = mcDecodeJwtPayload;

  // ─── Fase 4 — Refresh automático de JWT ───────────────────────────────
  //
  // A cada JWT_CHECK_INTERVAL_MS, decodifica o token em sessionStorage e:
  //   - Se exp ausente/token malformado → força logout (fail-closed).
  //   - Se já expirou → força logout.
  //   - Se faltam menos de JWT_REFRESH_WINDOW_S → chama POST /auth/refresh.
  //     * 200 + renewed=true  → atualiza sessionStorage.token.
  //     * 200 + renewed=false → nada a fazer (backend achou que não precisa).
  //     * 401 → token já foi rejeitado, mcFetch mandou pro logout.
  //     * outro erro → silencioso. Tenta de novo no próximo tick.
  //
  // O setInterval para quando a aba morre (browser). No logout, limpamos
  // explicitamente via mcLogoutLimpar() para evitar leak.
  async function mcCheckAndRefreshToken() {
    const token = sessionStorage.getItem('token');
    if (!token) {
      // Sem token → deixa o authGuard cuidar. Aqui não força redirect pra
      // evitar loop em páginas públicas.
      return;
    }
    const payload = mcDecodeJwtPayload(token);
    if (!payload || typeof payload.exp !== 'number') {
      // Token mal-formado: fail-closed, manda pro login.
      window.mcLogout();
      return;
    }
    const agoraS = Math.floor(Date.now() / 1000);
    const restante = payload.exp - agoraS;
    if (restante <= 0) {
      // Já expirou — não tenta refresh (backend vai rejeitar de qualquer forma).
      window.mcLogout();
      return;
    }
    if (restante > JWT_REFRESH_WINDOW_S) {
      // Token ainda confortável. Nada a fazer.
      return;
    }
    // Janela de refresh — solicita novo token ao backend.
    try {
      const resp = await window.mcFetch('/auth/refresh', {
        method: 'POST',
        timeout: 15000,
      });
      if (!resp.ok) {
        // mcFetch já tratou 401 (limpou sessão + redirect). Outros erros:
        // silencioso — tenta de novo no próximo tick.
        return;
      }
      const body = await resp.json();
      if (body && body.renewed && typeof body.access_token === 'string') {
        sessionStorage.setItem('token', body.access_token);
      }
    } catch (_) {
      // Falha de rede ou timeout — sem toast (não dá pra pedir pro operador
      // "tentar de novo" por renovação silenciosa). Próximo tick tenta.
    }
  }
  window.mcCheckAndRefreshToken = mcCheckAndRefreshToken;

  function setupJwtRefreshLoop() {
    // Só inicia em páginas autenticadas. login.html não precisa.
    const page = currentPage();
    if (page === 'login.html') return;
    if (_jwtRefreshTimerId !== null) return;  // já rodando — idempotente

    // Primeira checagem imediata, depois periódica. Se o operador voltou
    // pra aba após 1h, não esperamos mais 60s pra detectar que expirou.
    mcCheckAndRefreshToken().catch(function () { /* silencia */ });
    _jwtRefreshTimerId = setInterval(function () {
      mcCheckAndRefreshToken().catch(function () { /* silencia */ });
    }, JWT_CHECK_INTERVAL_MS);

    // Tab inativa → browser pode throttle setInterval. Ao voltar ao foco,
    // força uma checagem imediata.
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') {
        mcCheckAndRefreshToken().catch(function () { /* silencia */ });
      }
    });
  }

  // ─── Fase 4 — Session store em memória (PII fora do storage) ──────────
  //
  // window.__MC_SESSION__ é o único local onde CNPJ, razão social e
  // diagnóstico completo podem viver no frontend. sessionStorage guarda
  // apenas:
  //   - token         (JWT — necessário sobreviver a F5)
  //   - username/role (não-PII, usado pelo header)
  //   - analise_id    (UUID opaco do buffer backend — não identifica)
  //
  // Helpers mcSessionSet/get/clear encapsulam o acesso e garantem que
  // nenhum caller grava direto em sessionStorage.
  window.__MC_SESSION__ = window.__MC_SESSION__ || {};
  window.mcSessionSet = function (key, value) {
    if (!window.__MC_SESSION__) window.__MC_SESSION__ = {};
    window.__MC_SESSION__[key] = value;
  };
  window.mcSessionGet = function (key) {
    return window.__MC_SESSION__ ? window.__MC_SESSION__[key] : undefined;
  };
  window.mcSessionClear = function () {
    window.__MC_SESSION__ = {};
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
    setupJwtRefreshLoop();
  }

})();
