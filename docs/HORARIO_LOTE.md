# Módulo: Ajuste de Horário em Lote

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md). Soma um delta (padrão
**+60 min**) ao horário de **fechamento** de todas as contas, sem abrir
conta por conta.

## 1. É o módulo mais perigoso do sistema

Todo o resto do Power Central **lê** a plataforma. Este escreve — e
escreve no cadastro de todas as contas. Um erro aqui não quebra uma tela:
desregula a supervisão da base inteira, e o estrago aparece dias depois,
quando um "não abriu" deixar de ser disparado em alguém.

É por isso que ele tem mais trava do que funcionalidade. Em ordem de
importância:

| Trava | O que impede |
|---|---|
| Lote preparado e **persistido** antes de qualquer escrita | Escrever sem ter guardado o estado anterior |
| **Simulação ligada por padrão** | O padrão nunca ser "escrever" |
| **Aplica o lote salvo**, nunca varre de novo | Confirmar uma lista e executar outra |
| **Releitura antes de gravar** | Somar em cima do que já foi somado, ou por cima do trabalho de outra pessoa |
| Confirmação datilografada para o lote inteiro | Clique acidental |
| Falha isolada por linha | Uma conta ruim derrubar as outras 144 |
| Admin-only + auditoria de cada PUT | Não saber depois o que foi alterado |

## 2. A regra da meia-noite

Somar o delta pode levar o fechamento a 00:00 ou além. Nesse caso o
sistema **não altera**: a linha vai para a lista "manual (vira 00h)".

O motivo não é preguiça — é que `hor_ndiacierre` (o dia do fechamento)
teria que mudar junto, e isso é uma decisão sobre a grade de horário
daquele cliente, não uma conta de somar. Quem decide é uma pessoa olhando
o caso. A lista manual é entregue em Excel justamente para ser a lista de
trabalho de quem vai fazer isso.

Mesma lógica para horário ilegível: valor que não se entende é o último
lugar onde se deve escrever por cima.

## 3. Idempotência — duas camadas independentes

Rodar de novo **nunca** pode somar 1h em cima de 1h. Duas proteções
diferentes, porque falham por motivos diferentes:

1. **Ledger** (`AjusteHorarioItem.status`): item já `aplicado` não entra
   de novo na execução. Cobre reexecutar o mesmo lote.
2. **Releitura do valor atual**, imediatamente antes de cada PUT:
   - atual == `antes` do lote → grava;
   - atual == `depois` esperado → **já aplicado**, pula;
   - atual é outra coisa → **divergente**, não toca (alguém mexeu).

A releitura é **uma por conta**, não por linha: a proteção continua sendo
por linha, mas sem multiplicar a operação por sete (uma conta tem uma
linha por dia da semana).

## 4. Camadas

- `app/domain/horario_lote.py` (puro): `novo_fechamento`,
  `preparar_linhas`, `corpo_do_put`. O corpo do PUT lista os campos
  **explicitamente** — mandar campo que o portal não espera é risco
  desnecessário numa chamada de escrita.
- `app/integrations/softguard_client.py`: `atualizar_horario` →
  `PUT /Rest/Horario/<Id>`. A única escrita do sistema.
- `app/services/horario_lote_service.py`: `preparar` (só leitura),
  `aplicar` (escreve), `resumo`, `itens`.
- `app/models/horario_lote.py`: `AjusteHorarioLote` + `AjusteHorarioItem`.
  O lote inteiro é persistido porque ele é, ao mesmo tempo, o backup, a
  lista revisada e o ledger.
- `app/web/horario_lote/`: tela admin.

## 5. O caminho seguro (é o que a tela mostra)

1. **Preparar** — varre e monta o de→para. Não grava nada.
2. **Baixar backup** — planilha com o estado ANTES. É o desfazer.
3. **Testar em 1 conta** — aplica só nela; confira na plataforma.
4. **Aplicar no lote** — só depois que o teste conferiu.

O teste em uma conta **não** exige a palavra de confirmação, de
propósito: o passo barato e seguro tem que ser fácil de dar, senão
ninguém dá e vai direto para o lote.

### O passo 3 tem escrita própria

Em modo simulação nada é gravado — inclusive no teste de uma conta, o que
tornava o passo 3 **impossível de dar**: para testar em uma conta era
preciso desligar a chave global, que arma o botão do lote inteiro junto.
O oposto do que a sequência existe para fazer.

Por isso existe a caixa **"alterar de verdade nesta conta"**: libera a
escrita real para aquela conta só, sem mexer na chave. Ela vale apenas
com a conta preenchida — no lote inteiro quem manda continua sendo
`horario_lote_simulacao`, e o botão muda de rótulo para "Alterar de
verdade" assim que a caixa é marcada, porque um botão escrito "Simular"
que grava na plataforma seria pior que nenhum aviso.

### A simulação é lida na execução, não no preparo

Ela não é propriedade do lote: o preparo só lê a plataforma, e quem
decide se o PUT sai é o momento da execução. Lendo do lote, desligar a
simulação em Configurações não surtia efeito nenhum sem repreparar tudo
de novo — uma varredura de minutos — e, pior, a tela mostrava "Aplicar"
(que lê a configuração atual) enquanto o código simulava calado. O lote
passa a guardar o modo com que foi **executado**, para o histórico não
mentir sobre o que aconteceu.

### "118" e "0118" são a mesma conta

A comparação do campo "testar em uma conta" era exata, e o exemplo do
próprio campo (`ex.: 118`) levava a digitar sem os zeros que o portal
usa. O filtro não casava com nada, nenhuma linha era tocada, e a tela
respondia "0 linha(s)" — indistinguível de "o módulo não funciona". Hoje
a normalização é a do resto do sistema (`contas.normalizar_numero`), e
uma conta que não está no lote dá **erro explícito** dizendo que ela pode
estar na lista "Manual (vira 00h)", em vez de um zero silencioso.

## 6. Configuração

| Chave | Padrão | Para quê |
|---|---|---|
| `horario_lote_simulacao` | `true` | Simulação. Só `"false"` exato desliga |
| `horario_lote_delta_min` | `60` | Minutos somados ao fechamento (aceita negativo) |
| `horario_lote_pausa_segundos` | `0` | Pausa entre chamadas, se o portal reclamar |

## 7. O que os testes travam

Os três guardas foram conferidos **por mutação** — desligando cada um, o
teste correspondente falha:

- simulação desligada por engano → grava (teste falha);
- checagem de "já no destino" removida → soma duas vezes (teste falha);
- checagem de divergência removida → escreve por cima (teste falha).

Mais: só o fechamento muda no PUT (abertura e dias intactos), linha que
vira 00h nunca é enviada, falha num PUT não derruba as outras, e a
releitura é uma por conta.
