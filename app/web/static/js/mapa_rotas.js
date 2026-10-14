// Mapa do catálogo de preventivas: um pino por cliente com coordenada.
//
// Os pontos chegam por `data-attribute`, não por uma chamada à API: a
// tela já recebeu o catálogo renderizado, e buscar de novo seria refazer
// uma consulta que já foi feita.
//
// O Leaflet é vendorizado (BSD-2) em `static/vendor/leaflet/`, não CDN:
// o site roda na rede interna e precisa abrir sem depender de CDN. Só os
// tiles vêm do OpenStreetMap — sem internet o mapa fica cinza, mas a
// página e as tabelas continuam inteiras.
(function () {
  var elemento = document.getElementById('mapa-rotas');
  if (!elemento || typeof L === 'undefined') { return; }

  var pontos = [];
  try {
    pontos = JSON.parse(elemento.dataset.pontos || '[]');
  } catch (e) {
    return;
  }
  if (!pontos.length) { return; }

  // Enquadramento de BH como fallback: se tudo falhar o mapa abre numa
  // região plausível em vez de no meio do Atlântico.
  var mapa = L.map(elemento).setView([-19.92, -43.94], 12);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap',
  }).addTo(mapa);

  // Uma cor por bairro, para a região saltar aos olhos; visitado fica
  // esmaecido e com o traço diferente, para "o que falta" ser o que
  // chama atenção.
  var cores = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e',
               '#17becf', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22'];
  var corDaRegiao = {};
  var proxima = 0;

  function cor(regiao) {
    if (!(regiao in corDaRegiao)) {
      corDaRegiao[regiao] = cores[proxima % cores.length];
      proxima += 1;
    }
    return corDaRegiao[regiao];
  }

  function escapar(texto) {
    var div = document.createElement('div');
    div.textContent = texto == null ? '' : texto;
    return div.innerHTML;
  }

  var marcadores = {};
  var limites = [];

  pontos.forEach(function (ponto) {
    var marcador = L.circleMarker([ponto.lat, ponto.lon], {
      radius: 7,
      color: ponto.visitado ? '#9aa0a6' : cor(ponto.regiao),
      fillColor: ponto.visitado ? '#9aa0a6' : cor(ponto.regiao),
      fillOpacity: ponto.visitado ? 0.35 : 0.85,
      weight: ponto.visitado ? 1 : 2,
    }).addTo(mapa);

    marcador.bindPopup(
      '<strong>' + escapar(ponto.nome) + '</strong><br>' +
      'Conta ' + escapar(ponto.conta) + '<br>' +
      escapar(ponto.regiao) + '<br>' +
      (ponto.visitado ? '<em>já visitado neste ciclo</em>' : 'ainda não visitado')
    );

    marcadores[ponto.conta] = marcador;
    limites.push([ponto.lat, ponto.lon]);
  });

  if (limites.length) {
    mapa.fitBounds(limites, { padding: [30, 30] });
  }

  // Marcar na lista tem que se refletir no mapa — senão o mapa vira uma
  // segunda versão da verdade, desatualizada desde o primeiro clique.
  document.addEventListener('rotas:visita', function (evento) {
    var marcador = marcadores[evento.detail.conta];
    if (!marcador) { return; }
    var visitado = evento.detail.visitado;
    var corOriginal = cor(evento.detail.regiao || '');
    marcador.setStyle({
      color: visitado ? '#9aa0a6' : corOriginal,
      fillColor: visitado ? '#9aa0a6' : corOriginal,
      fillOpacity: visitado ? 0.35 : 0.85,
      weight: visitado ? 1 : 2,
    });
  });

  // A busca da lista também filtra o mapa: ver dez pinos de "padaria"
  // num mapa de cem é metade da utilidade da busca.
  document.addEventListener('rotas:busca', function (evento) {
    var visiveis = evento.detail.contas;
    Object.keys(marcadores).forEach(function (conta) {
      var marcador = marcadores[conta];
      var mostrar = visiveis === null || visiveis.has(conta);
      if (mostrar && !mapa.hasLayer(marcador)) { marcador.addTo(mapa); }
      if (!mostrar && mapa.hasLayer(marcador)) { mapa.removeLayer(marcador); }
    });
  });
})();
