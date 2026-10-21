/*
 * Hover dos gráficos e ordenação de tabela.
 *
 * O SVG já vem montado do servidor com um `<title>` por barra — isto é
 * melhoria, não a única forma de ler o valor: sem JS a dica nativa do
 * navegador continua funcionando, e todo número também está na tabela
 * logo abaixo. Dica que é o ÚNICO caminho para um valor é dica que
 * esconde o dado.
 *
 * O alvo do ponteiro é a FAIXA da coluna, não a coluna: acertar uma
 * barra de 8px no celular é impossível.
 */
(function () {
  "use strict";

  function montarDica(banda) {
    var titulo = banda.getAttribute("data-titulo") || "";
    var valor = banda.getAttribute("data-valor") || "";
    var detalhe = banda.getAttribute("data-detalhe") || "";
    var html = "<strong></strong><span></span>";
    var molde = document.createElement("div");
    molde.innerHTML = html;
    molde.firstChild.textContent = titulo;
    molde.lastChild.textContent = detalhe ? valor + " · " + detalhe : valor;
    return molde.innerHTML;
  }

  function ligarGrafico(grafico) {
    var dica = grafico.querySelector("[data-dica]");
    var mira = grafico.querySelector("[data-mira]");
    var svg = grafico.querySelector("svg");
    var bandas = grafico.querySelectorAll(".grafico-banda");
    var colunas = grafico.querySelectorAll(".grafico-coluna");
    if (!dica || !svg || !bandas.length) return;

    function apagar() {
      grafico.classList.remove("is-apontando");
      dica.setAttribute("data-visivel", "0");
      if (mira) mira.classList.remove("is-ativa");
      Array.prototype.forEach.call(colunas, function (c) {
        c.classList.remove("is-ativa");
      });
    }

    function acender(banda, evento) {
      var indice = banda.getAttribute("data-indice");
      grafico.classList.add("is-apontando");
      Array.prototype.forEach.call(colunas, function (c) {
        c.classList.toggle("is-ativa", c.getAttribute("data-coluna") === indice);
      });

      if (mira) {
        var centro = banda.getAttribute("data-centro");
        mira.setAttribute("x1", centro);
        mira.setAttribute("x2", centro);
        mira.classList.add("is-ativa");
      }

      dica.innerHTML = montarDica(banda);
      dica.setAttribute("data-visivel", "1");

      // Posiciona em pixels da CAIXA, não em unidades do viewBox: o SVG
      // é escalado por largura e os dois sistemas não coincidem.
      var caixa = grafico.getBoundingClientRect();
      var alvo = banda.getBoundingClientRect();
      var x = (evento ? evento.clientX : alvo.left + alvo.width / 2) - caixa.left;
      var largura = dica.offsetWidth || 150;
      var limite = caixa.width - largura - 4;
      dica.style.left = Math.max(4, Math.min(x - largura / 2, limite)) + "px";
      dica.style.top = Math.max(0, alvo.top - caixa.top) + "px";
    }

    Array.prototype.forEach.call(bandas, function (banda) {
      banda.addEventListener("mousemove", function (evento) {
        acender(banda, evento);
      });
      // Teclado vê o mesmo que o ponteiro.
      banda.setAttribute("tabindex", "0");
      banda.addEventListener("focus", function () {
        acender(banda, null);
      });
      banda.addEventListener("blur", apagar);
    });

    svg.addEventListener("mouseleave", apagar);
  }

  // ---------- tabelas ordenáveis ----------

  function valorDaCelula(celula, tipo) {
    var bruto = celula.getAttribute("data-ordem");
    if (bruto === null) bruto = celula.textContent;
    bruto = (bruto || "").trim();
    if (tipo !== "numero") return bruto.toLowerCase();
    // Aceita o que a tela mostra: vírgula decimal, %, sinal.
    var limpo = bruto.replace(/\s/g, "").replace("%", "").replace(",", ".");
    var numero = parseFloat(limpo);
    return isNaN(numero) ? -Infinity : numero;
  }

  function ligarTabela(tabela) {
    var cabecalhos = tabela.querySelectorAll("th[data-ordenar]");
    Array.prototype.forEach.call(cabecalhos, function (th, coluna) {
      th.setAttribute("tabindex", "0");
      th.setAttribute("role", "button");

      function ordenar() {
        var tipo = th.getAttribute("data-ordenar");
        var crescente = th.getAttribute("aria-sort") !== "ascending";
        var corpo = tabela.tBodies[0];
        var linhas = Array.prototype.slice.call(corpo.rows);

        linhas.sort(function (a, b) {
          var x = valorDaCelula(a.cells[coluna], tipo);
          var y = valorDaCelula(b.cells[coluna], tipo);
          if (x < y) return crescente ? -1 : 1;
          if (x > y) return crescente ? 1 : -1;
          return 0;
        });

        Array.prototype.forEach.call(cabecalhos, function (outro) {
          outro.removeAttribute("aria-sort");
        });
        th.setAttribute("aria-sort", crescente ? "ascending" : "descending");
        linhas.forEach(function (linha) {
          corpo.appendChild(linha);
        });
      }

      th.addEventListener("click", ordenar);
      th.addEventListener("keydown", function (evento) {
        if (evento.key === "Enter" || evento.key === " ") {
          evento.preventDefault();
          ordenar();
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-grafico]"), ligarGrafico);
    Array.prototype.forEach.call(document.querySelectorAll("[data-ordenavel]"), ligarTabela);
  });
})();
