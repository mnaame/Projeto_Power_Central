// Mapa do catálogo de preventivas: um pino por cliente com coordenada,
// agrupados por proximidade como no app de campo.
//
// **Por que agrupar.** Cem pinos crus em cima de Belo Horizonte viram uma
// mancha: não dá para ver quantos clientes há em cada lugar nem clicar
// num deles. O agrupamento mostra a contagem por região e vai abrindo
// conforme se aproxima — é o que torna o mapa legível de verdade, e é
// como a Auvo faz.
//
// Os pontos chegam por `data-attribute`, não por uma chamada à API: a
// tela já recebeu o catálogo renderizado, e buscar de novo seria refazer
// uma consulta que já foi feita.
//
// Leaflet e Leaflet.markercluster são vendorizados (BSD-2 e MIT) em
// `static/vendor/leaflet/`, não CDN: o site roda na rede interna e
// precisa abrir sem depender de CDN. Só os tiles vêm do OpenStreetMap —
// sem internet o mapa fica cinza, mas a página e as tabelas continuam
// inteiras.
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

  // Enquadramento de BH como ponto de partida: se o `fitBounds` falhar,
  // o mapa abre numa região plausível em vez de no meio do Atlântico.
  var mapa = L.map(elemento).setView([-19.92, -43.94], 12);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap',
  }).addTo(mapa);

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

  function estilo(ponto) {
    var base = cor(ponto.regiao);
    return {
      radius: 8,
      color: '#fff',
      weight: 2,
      fillColor: ponto.visitado ? '#9aa0a6' : base,
      fillOpacity: ponto.visitado ? 0.45 : 0.95,
    };
  }

  // A bolha do grupo mostra quantos faltam, não quantos são: "o que
  // ainda tenho para fazer aqui" é a pergunta de quem monta a agenda.
  var grupo = L.markerClusterGroup({
    maxClusterRadius: 50,
    showCoverageOnHover: false,
    iconCreateFunction: function (cluster) {
      var filhos = cluster.getAllChildMarkers();
      var pendentes = filhos.filter(function (m) { return !m.options.visitado; }).length;
      var tudoFeito = pendentes === 0;
      var tamanho = filhos.length < 10 ? 36 : (filhos.length < 50 ? 44 : 52);
      return L.divIcon({
        className: 'cluster-rotas',
        iconSize: [tamanho, tamanho],
        html:
          '<div class="cluster-rotas-bolha' + (tudoFeito ? ' is-ok' : '') + '">' +
          '<span>' + (tudoFeito ? filhos.length : pendentes) + '</span>' +
          '</div>',
      });
    },
  });

  var marcadores = {};
  var limites = [];

  pontos.forEach(function (ponto) {
    var marcador = L.circleMarker([ponto.lat, ponto.lon], estilo(ponto));
    marcador.options.visitado = ponto.visitado;
    marcador.options.regiao = ponto.regiao;
    marcador.options.conta = ponto.conta;

    marcador.bindPopup(
      '<strong>' + escapar(ponto.nome) + '</strong><br>' +
      'Conta ' + escapar(ponto.conta) + '<br>' +
      escapar(ponto.regiao) + '<br>' +
      (ponto.visitado ? '<em>já visitado neste ciclo</em>' : 'ainda não visitado')
    );

    marcadores[ponto.conta] = marcador;
    grupo.addLayer(marcador);
    limites.push([ponto.lat, ponto.lon]);
  });

  mapa.addLayer(grupo);
  if (limites.length) {
    mapa.fitBounds(limites, { padding: [40, 40] });
  }

  // Marcar na lista tem que se refletir no mapa — senão o mapa vira uma
  // segunda versão da verdade, desatualizada desde o primeiro clique.
  document.addEventListener('rotas:visita', function (evento) {
    var marcador = marcadores[evento.detail.conta];
    if (!marcador) { return; }
    marcador.options.visitado = evento.detail.visitado;
    marcador.setStyle(estilo({
      regiao: marcador.options.regiao,
      visitado: evento.detail.visitado,
    }));
    grupo.refreshClusters(marcador);  // a contagem da bolha acompanha
  });

  // A busca da lista também filtra o mapa: ver dez pinos de "padaria"
  // num mapa de cem é metade da utilidade da busca.
  document.addEventListener('rotas:busca', function (evento) {
    var visiveis = evento.detail.contas;
    grupo.clearLayers();
    var mostrados = [];
    Object.keys(marcadores).forEach(function (conta) {
      if (visiveis === null || visiveis.has(conta)) {
        grupo.addLayer(marcadores[conta]);
        mostrados.push(marcadores[conta].getLatLng());
      }
    });
    if (mostrados.length) {
      mapa.fitBounds(mostrados, { padding: [40, 40], maxZoom: 16 });
    }
  });
})();
