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
  });

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
