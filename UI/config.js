/*
 * config.js — ponto único de configuração da UI.
 *
 * Carregado antes de components.js em todas as páginas.
 *
 * API_BASE: origem do backend FastAPI. A UI é servida pelo próprio backend
 * (/ui/*), então a origem da página é a origem da API — vale para
 * uvicorn em dev, Docker e o .exe desktop (127.0.0.1:<porta livre>).
 * Para apontar a UI a outro backend, troque só este valor.
 */
(function () {
  'use strict';

  window.MC_CONFIG = Object.freeze({
    API_BASE: window.location.origin,
  });

  // Monta URL absoluta da API a partir de um caminho ('/auth/login').
  // URLs já absolutas (http://, https://) passam sem mudança.
  window.mcApiUrl = function (path) {
    if (typeof path !== 'string' || /^https?:\/\//i.test(path)) return path;
    return window.MC_CONFIG.API_BASE + (path.charAt(0) === '/' ? path : '/' + path);
  };
})();
