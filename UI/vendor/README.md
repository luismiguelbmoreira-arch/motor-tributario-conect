# UI/vendor — bibliotecas locais

A UI não carrega nada da internet (necessário para o `.exe` desktop offline).
`PY/tests/test_ui_offline.py` quebra se alguma página voltar a usar CDN.

| Pasta | Versão | Origem | Licença | Usado em |
|---|---|---|---|---|
| `inter/` | @fontsource/inter 5.3.0 (pesos 300–700, latin + latin-ext) | npm `@fontsource/inter` | OFL-1.1 | `design_system.css`, `resultado.html` |
| `lucide/` | lucide 1.80.0 (UMD) | npm `lucide` | ISC | todas as páginas com ícones |
| `chartjs/chart-4.6.2.umd.min.js` | Chart.js 4.6.2 | npm `chart.js` | MIT | `dashboard.html`, `analise_unificada.html` |
| `chartjs/chart-4.4.0.umd.min.js` | Chart.js 4.4.0 (versão que `resultado.html` já fixava) | npm `chart.js` | MIT | `resultado.html` |
| `tailwind/` | Tailwind Play CDN 3.4.17 | `cdn.tailwindcss.com/3.4.17` | MIT | `cronograma.html`, `resultado.html` |

Antes, `lucide@latest` e `chart.js` sem versão mudavam sozinhos a cada release.
Agora a versão só muda trocando o arquivo aqui.
