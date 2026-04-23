/**
 * validacao.js — Helpers de validação client-side (Motor Tributário Conect).
 *
 * FILOSOFIA ZERO-TRUST:
 *   Validação client-side é REDUNDANTE com Pydantic no backend, NÃO substitui.
 *   Backend rejeita com 422 qualquer payload que burle o client-side — a validação
 *   aqui é feedback rápido pro usuário, não defesa. Sempre assumir que o usuário
 *   pode burlar esta camada.
 *
 * FILOSOFIA GIGO:
 *   Entrada suja é rejeitada em 3 camadas: JS, FastAPI path, Pydantic.
 *
 * DECIMAL:
 *   NUNCA usar parseFloat para valor monetário. Strings numéricas cruas trafegam
 *   pelo payload e o backend serializa como Decimal via Pydantic field_validator.
 */

(function () {
  'use strict';

  // ───────────────────────────────────────────────────────────────────
  // CNPJ — Módulo 11 (validação local espelho de PY/validadores.py)
  // Receita Federal — IN RFB 2.019/2021 + Decreto 3.000/1999.
  // ───────────────────────────────────────────────────────────────────
  window.validaCNPJ = function (cnpj) {
    if (typeof cnpj !== 'string') return { ok: false, erro: 'CNPJ deve ser string.' };
    const d = cnpj.replace(/[^\d]/g, '');
    if (d.length !== 14) return { ok: false, erro: 'CNPJ deve ter 14 dígitos.' };
    if (/^(\d)\1{13}$/.test(d)) return { ok: false, erro: 'CNPJ com todos os dígitos iguais.' };

    const pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    const pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];

    function calcDV(slice, pesos) {
      let soma = 0;
      for (let i = 0; i < pesos.length; i++) soma += parseInt(slice[i], 10) * pesos[i];
      const resto = soma % 11;
      return resto < 2 ? 0 : 11 - resto;
    }

    const dv1 = calcDV(d.slice(0, 12), pesos1);
    if (dv1 !== parseInt(d[12], 10)) return { ok: false, erro: 'Primeiro dígito verificador incorreto.' };
    const dv2 = calcDV(d.slice(0, 13), pesos2);
    if (dv2 !== parseInt(d[13], 10)) return { ok: false, erro: 'Segundo dígito verificador incorreto.' };
    return { ok: true, limpo: d };
  };

  // ───────────────────────────────────────────────────────────────────
  // UF — 27 unidades federativas (sigla de 2 letras)
  // ───────────────────────────────────────────────────────────────────
  const UFS_VALIDAS = new Set([
    'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO',
    'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR',
    'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO',
  ]);
  window.validaUF = function (uf) {
    if (typeof uf !== 'string') return { ok: false, erro: 'UF deve ser string.' };
    const u = uf.trim().toUpperCase();
    if (!UFS_VALIDAS.has(u)) return { ok: false, erro: 'UF inválida: ' + uf };
    return { ok: true, limpo: u };
  };

  // ───────────────────────────────────────────────────────────────────
  // Data — período transicional LC 214/2025 Art. 348 (2026-2033)
  // ───────────────────────────────────────────────────────────────────
  window.validaData2026_2033 = function (iso) {
    if (typeof iso !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
      return { ok: false, erro: 'Data deve estar no formato YYYY-MM-DD.' };
    }
    const ano = parseInt(iso.slice(0, 4), 10);
    if (ano < 2026 || ano > 2033) {
      return { ok: false, erro: 'Data fora do período transicional (2026-2033) — LC 214/2025 Art. 348.' };
    }
    // valida calendário real (30 fev etc.)
    const [a, m, d] = iso.split('-').map(n => parseInt(n, 10));
    const dt = new Date(Date.UTC(a, m - 1, d));
    if (dt.getUTCFullYear() !== a || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) {
      return { ok: false, erro: 'Data inexistente no calendário.' };
    }
    return { ok: true, limpo: iso };
  };

  // ───────────────────────────────────────────────────────────────────
  // CNAE — 7 dígitos numéricos
  // ───────────────────────────────────────────────────────────────────
  window.validaCNAE = function (cnae) {
    if (typeof cnae !== 'string') return { ok: false, erro: 'CNAE deve ser string.' };
    const d = cnae.replace(/[^\d]/g, '');
    if (d.length !== 7) return { ok: false, erro: 'CNAE deve ter 7 dígitos.' };
    return { ok: true, limpo: d };
  };

  // ───────────────────────────────────────────────────────────────────
  // NCM — 8 dígitos (NBS aceita mesmo formato)
  // ───────────────────────────────────────────────────────────────────
  window.validaNCM = function (ncm) {
    if (typeof ncm !== 'string') return { ok: false, erro: 'NCM deve ser string.' };
    const d = ncm.replace(/[^\d]/g, '');
    if (d.length !== 8) return { ok: false, erro: 'NCM/NBS deve ter 8 dígitos.' };
    return { ok: true, limpo: d };
  };

  // ───────────────────────────────────────────────────────────────────
  // Máscara BRL — R$ 1.234,56 (entrada do usuário)
  // Retorna string mascarada; NUNCA usar o valor numérico desse campo
  // direto no payload — usar decimalSafe() para conversão.
  // ───────────────────────────────────────────────────────────────────
  window.mascaraBRL = function (valor) {
    const apenasDigitos = String(valor || '').replace(/[^\d]/g, '');
    if (!apenasDigitos) return '';
    const centavos = apenasDigitos.padStart(3, '0');
    const inteiro = centavos.slice(0, -2).replace(/^0+/, '') || '0';
    const decimal = centavos.slice(-2);
    const intComPontos = inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return 'R$ ' + intComPontos + ',' + decimal;
  };

  // Aplica máscara BRL a um <input> — use no oninput.
  window.aplicarMascaraBRL = function (inputEl) {
    if (!inputEl) return;
    inputEl.value = window.mascaraBRL(inputEl.value);
  };

  // ───────────────────────────────────────────────────────────────────
  // decimalSafe — converte string mascarada (BRL ou texto livre) para
  // string decimal "1234.56" pronta para enviar ao backend.
  //
  // NUNCA retorna Number — backend exige Decimal via Pydantic e qualquer
  // float no caminho viola MAX_FISCAL_01.
  //
  // Aceita: "R$ 1.234,56", "1.234,56", "1234.56", "1234,56", "1234"
  // Retorna: string "1234.56" ou "" se inválido.
  // ───────────────────────────────────────────────────────────────────
  window.decimalSafe = function (raw) {
    if (raw === null || raw === undefined) return '';
    let s = String(raw).trim();
    if (!s) return '';
    // remove prefixo R$ e espaços
    s = s.replace(/[R$\s]/g, '');
    // se tem vírgula E ponto, assume pt-BR: pontos = milhar, vírgula = decimal
    if (s.includes(',') && s.includes('.')) {
      s = s.replace(/\./g, '').replace(',', '.');
    } else if (s.includes(',')) {
      // só vírgula = decimal pt-BR
      s = s.replace(',', '.');
    }
    // valida número
    if (!/^-?\d+(\.\d+)?$/.test(s)) return '';
    // normaliza sem zeros à esquerda (mas preserva 0.xx)
    const [ints, decs] = s.split('.');
    const intsNorm = String(parseInt(ints, 10));
    return decs !== undefined ? `${intsNorm}.${decs}` : intsNorm;
  };

  // ───────────────────────────────────────────────────────────────────
  // Máscara CNPJ para exibição: 00.000.000/0000-00
  // ───────────────────────────────────────────────────────────────────
  window.mascaraCNPJ = function (valor) {
    const d = String(valor || '').replace(/[^\d]/g, '').slice(0, 14);
    if (d.length <= 2) return d;
    if (d.length <= 5) return d.slice(0, 2) + '.' + d.slice(2);
    if (d.length <= 8) return d.slice(0, 2) + '.' + d.slice(2, 5) + '.' + d.slice(5);
    if (d.length <= 12) return d.slice(0, 2) + '.' + d.slice(2, 5) + '.' + d.slice(5, 8) + '/' + d.slice(8);
    return d.slice(0, 2) + '.' + d.slice(2, 5) + '.' + d.slice(5, 8) + '/' + d.slice(8, 12) + '-' + d.slice(12);
  };

  window.aplicarMascaraCNPJ = function (inputEl) {
    if (!inputEl) return;
    inputEl.value = window.mascaraCNPJ(inputEl.value);
  };

})();
