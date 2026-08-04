(function () {
  "use strict";

  var THEME_KEY = "power-central-theme";

  function aplicarTema(tema) {
    document.documentElement.setAttribute("data-theme", tema);
  }

  function temaAtual() {
    return localStorage.getItem(THEME_KEY) || "auto";
  }

  function alternarTema() {
    var atual = document.documentElement.getAttribute("data-theme");
    var proximo = atual === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, proximo);
    aplicarTema(proximo);
  }

  var salvo = localStorage.getItem(THEME_KEY);
  if (salvo && salvo !== "auto") {
    aplicarTema(salvo);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var botao = document.querySelector("[data-theme-toggle]");
    if (botao) {
      botao.addEventListener("click", alternarTema);
    }

    var alvo = document.querySelector("[data-poll-target]");
    if (alvo) {
      var url = alvo.getAttribute("data-poll-target");
      var intervaloMs = parseInt(alvo.getAttribute("data-poll-interval") || "30000", 10);
      iniciarPolling(alvo, url, intervaloMs);
    }

    document.addEventListener("submit", function (evento) {
      var formulario = evento.target;
      if (!formulario.matches("[data-loading-submit]")) {
        return;
      }
      var botaoEnvio = formulario.querySelector("button[type=submit]");
      if (botaoEnvio && !botaoEnvio.disabled) {
        botaoEnvio.dataset.textoOriginal = botaoEnvio.textContent;
        botaoEnvio.textContent = "Atualizando...";
        botaoEnvio.disabled = true;
      }
    });

    document.addEventListener("click", function (evento) {
      var botao = evento.target.closest("[data-marcar-todas]");
      if (!botao) {
        return;
      }
      var marcar = botao.getAttribute("data-marcar-todas") === "1";
      document.querySelectorAll("[data-linha-checkbox]").forEach(function (caixa) {
        if (!caixa.disabled) {
          caixa.checked = marcar;
        }
      });
    });

    document.addEventListener("click", function (evento) {
      var botao = evento.target.closest("[data-cofre-gerar-senha]");
      if (!botao) {
        return;
      }
      var campo = document.querySelector("[data-cofre-senha-campo]");
      if (!campo) {
        return;
      }
      campo.value = botao.getAttribute("data-cofre-gerar-senha");
      campo.dispatchEvent(new Event("input"));
    });

    var campoSenha = document.querySelector("[data-cofre-senha-campo]");
    var indicadorForca = document.querySelector("[data-cofre-forca-senha]");
    if (campoSenha && indicadorForca) {
      campoSenha.addEventListener("input", function () {
        atualizarForcaSenha(campoSenha.value, indicadorForca);
      });
    }

    document.querySelectorAll("[data-cofre-revelado]").forEach(function (elemento) {
      agendarLimpezaSenhaRevelada(elemento);
    });

    if (!navigator.clipboard) {
      document.querySelectorAll("[data-cofre-copiar]").forEach(function (botao) {
        botao.style.display = "none";
      });
    }

    document.addEventListener("click", function (evento) {
      var botao = evento.target.closest("[data-cofre-copiar]");
      if (!botao) {
        return;
      }
      var linha = botao.closest("td") || botao.parentElement;
      var elementoSenha = linha ? linha.querySelector("[data-cofre-revelado]") : null;
      if (!elementoSenha) {
        return;
      }
      copiarParaAreaDeTransferencia(elementoSenha.textContent, botao);
    });
  });

  function atualizarForcaSenha(senha, indicador) {
    if (!senha) {
      indicador.textContent = "";
      return;
    }
    var categorias = 0;
    if (/[a-z]/.test(senha)) categorias++;
    if (/[A-Z]/.test(senha)) categorias++;
    if (/\d/.test(senha)) categorias++;
    if (/[^\w\s]/.test(senha)) categorias++;

    var forca;
    if (senha.length < 8) {
      forca = "fraca";
    } else {
      var pontos = categorias + (senha.length >= 12 ? 1 : 0) + (senha.length >= 16 ? 1 : 0);
      if (pontos <= 2) forca = "fraca";
      else if (pontos === 3) forca = "media";
      else if (pontos === 4) forca = "forte";
      else forca = "muito_forte";
    }

    var rotulos = {
      fraca: "Força: fraca",
      media: "Força: média",
      forte: "Força: forte",
      muito_forte: "Força: muito forte",
    };
    indicador.textContent = rotulos[forca];
  }

  var LIMPEZA_SEGUNDOS = 30;

  function agendarLimpezaSenhaRevelada(elemento) {
    setTimeout(function () {
      elemento.textContent = "••••••••";
    }, LIMPEZA_SEGUNDOS * 1000);
  }

  function copiarParaAreaDeTransferencia(texto, botao) {
    if (!navigator.clipboard) {
      return;
    }
    navigator.clipboard.writeText(texto).then(function () {
      var textoOriginal = botao.textContent;
      botao.textContent = "Copiado!";
      setTimeout(function () {
        botao.textContent = textoOriginal;
      }, 2000);
      setTimeout(function () {
        navigator.clipboard.writeText("").catch(function () {
          // Sem permissão para limpar — a senha some da tela de qualquer forma.
        });
      }, LIMPEZA_SEGUNDOS * 1000);
    });
  }

  function iniciarPolling(alvo, url, intervaloMs) {
    setInterval(function () {
      fetch(url, { headers: { "X-Requested-With": "fetch" } })
        .then(function (resposta) {
          if (!resposta.ok) {
            throw new Error("status " + resposta.status);
          }
          return resposta.text();
        })
        .then(function (html) {
          alvo.style.opacity = "0.4";
          alvo.innerHTML = html;
          requestAnimationFrame(function () {
            alvo.style.opacity = "1";
          });
        })
        .catch(function () {
          // Falha de rede/portal não deve travar a tela — o próximo tick tenta de novo.
        });
    }, intervaloMs);
  }
})();
