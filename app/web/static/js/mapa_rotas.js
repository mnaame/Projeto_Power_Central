/* Mapa das rotas de visita (Leaflet vendorizado em static/vendor).
 *
 * Os dados vêm de um data-attribute no próprio elemento do mapa, e não de
 * uma chamada à API: a tela já recebeu as rotas renderizadas, e buscar de
 * novo seria refazer uma consulta que levou minutos.
 *
 * A biblioteca é servida localmente de propósito — o site roda na rede
 * interna e não pode depender de CDN para abrir. Só os tiles vêm da
 * internet; sem ela o mapa fica cinza, mas a página e as tabelas
 * continuam inteiras.
 */
(function () {
  "use strict";

  // Cores distinguíveis entre si e no claro/escuro; a lista cicla quando
  // há mais rotas que cores — nesse ponto a legenda já é o que orienta.
  var CORES = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#008080", "#9a6324", "#800000", "#808000", "#000075",
    "#f032e6", "#469990", "#ff8c00", "#2f4f4f", "#8b0000"
  ];

  function corDaRota(indice) {
    return CORES[(indice - 1) % CORES.length];
  }

  function marcador(ponto, cor) {
    return L.divIcon({
      className: "",
      html:
        '<div style="background:' + cor + ';color:#fff;border:2px solid #fff;' +
        "border-radius:50%;width:26px;height:26px;display:flex;align-items:center;" +
        'justify-content:center;font:bold 11px/1 sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.4)">' +
        ponto.ordem +
        "</div>",
      iconSize: [26, 26],
      iconAnchor: [13, 13]
    });
  }

  function escapar(texto) {
    var div = document.createElement("div");
    div.textContent = texto == null ? "" : String(texto);
    return div.innerHTML;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var elemento = document.getElementById("mapa-rotas");
    if (!elemento || typeof L === "undefined") {
      return;
    }

    var rotas;
    try {
      rotas = JSON.parse(elemento.getAttribute("data-rotas") || "[]");
    } catch (erro) {
      return;
    }
    if (!rotas.length) {
      return;
    }

    var mapa = L.map(elemento);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap"
    }).addTo(mapa);

    var limites = [];
    rotas.forEach(function (rota) {
      var cor = corDaRota(rota.indice);
      var caminho = [];

      rota.pontos.forEach(function (ponto) {
        var posicao = [ponto.lat, ponto.lon];
        caminho.push(posicao);
        limites.push(posicao);

        L.marker(posicao, { icon: marcador(ponto, cor) })
          .addTo(mapa)
          .bindPopup(
            "<strong>Rota " + rota.indice + " · parada " + ponto.ordem + "</strong><br>" +
            escapar(ponto.conta) + " — " + escapar(ponto.nome) +
            (ponto.cidade ? "<br>" + escapar(ponto.cidade) : "") +
            '<br><span style="opacity:.7">coordenada: ' + escapar(ponto.fonte) + "</span>"
          );
      });

      // A linha é a ordem de visita sugerida, não o trajeto de rua.
      if (caminho.length > 1) {
        L.polyline(caminho, { color: cor, weight: 3, opacity: 0.6 }).addTo(mapa);
      }
    });

    if (limites.length) {
      mapa.fitBounds(limites, { padding: [30, 30] });
    }

    var legenda = L.control({ position: "bottomright" });
    legenda.onAdd = function () {
      var caixa = L.DomUtil.create("div");
      caixa.style.cssText =
        "background:#fff;color:#222;padding:8px 10px;border-radius:6px;" +
        "box-shadow:0 1px 6px rgba(0,0,0,.3);font:12px/1.5 sans-serif;" +
        "max-height:200px;overflow:auto";
      caixa.innerHTML = rotas
        .map(function (rota) {
          return (
            '<div><span style="display:inline-block;width:10px;height:10px;' +
            "border-radius:50%;background:" + corDaRota(rota.indice) +
            ';margin-right:6px"></span>Rota ' + rota.indice +
            " (" + rota.pontos.length + ")</div>"
          );
        })
        .join("");
      return caixa;
    };
    legenda.addTo(mapa);
  });
})();
