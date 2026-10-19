# Módulo: Lojas sem Arme (Super Nosso)

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md). Desliga o aviso de "não
armou" das lojas da lista semanal do Super Nosso, para o serviço noturno
não gerar falha de arme.

## 1. Por que o mecanismo anterior foi descartado

A primeira versão deste módulo colocava a conta **em teste**
(`EstadoUpd`, `est_ntipo = 3`). Funcionava para o problema imediato, e
estava errada: o estado de teste **cala a conta inteira** — a falha de
arme, sim, mas também o **disparo**. Uma loja em teste com alguém dentro
não geraria nada.

O mecanismo atual mexe num campo só, `tol_nnyc` da tolerância, que
governa exclusivamente o aviso de "não fechou ainda". **O BUR continua
chegando normalmente.** É toda a razão da troca, e é o que a tela diz em
primeiro lugar.

## 2. ⚠️ E o que a troca cobra: nada expira sozinho

O teste tinha uma janela (`est_nduracion`) que expirava por conta
própria. Esquecer de desfazer **não era possível**.

Este campo fica desligado **até alguém religar**. A segurança deixa de
ser o relógio da plataforma e passa a ser:

1. **O ledger** (`aviso_arme_desligados`) — quem está desligado e, acima
   de tudo, **o valor que a conta tinha antes**.
2. **O ciclo semanal** — rodar a lista nova desliga as que entraram e
   **religa as que saíram**.
3. **O contador de dias na tela**, destacado acima de 8 dias. Sem
   expiração automática, "desligada há 23 dias" é o único sintoma de que
   a lista parou de ser rodada.
4. **O botão "religar todas"** — saída de emergência que não depende de o
   Super Nosso mandar a mensagem da semana.

Quem não rodar a semana seguinte deixa lojas sem supervisão de arme por
tempo indeterminado. Isso é uma propriedade do mecanismo, não um
descuido do código, e por isso está escrito na tela.

## 3. O endpoint (HAR 19/10)

**Read-modify-write.** Ler o registro inteiro, trocar um campo, mandar
tudo de volta:

```
GET /Rest/HorarioTolerancia/<cue_iid>     → o registro com tol_*
PUT /Rest/HorarioTolerancia/<cue_iid>     → o MESMO registro, com tol_nnyc trocado
```

- **Desligar o aviso**: `tol_nnyc = 2`.
- **Religar**: `tol_nnyc` = o valor original da conta, vindo do ledger
  (tipicamente 1).

### 1 = sim, 2 = não — e isso custou um lote

A especificação inicial dizia o contrário ("desligar = 1"). A prova de
que está invertido veio do próprio registro, comparado com a tela da
plataforma na mesma conta:

| Campo | Valor | Tela |
|---|---|---|
| `tol_nnyo` | 2 | "Gerar não desarmado ainda: **Não**" |
| `tol_nnyc` | 1 | "Gerar não armado ainda: **sim**" |

Dois campos irmãos, a mesma régua. Gravar 1 para "desligar" escrevia o
valor que já estava lá: nove contas foram reportadas como desligadas sem
que nada mudasse na plataforma, e o ledger guardou "religa com
`tol_nnyc = 1`" — que era a pista de que o valor lido já era o de
"ligado".

Quatro detalhes com teste próprio, porque errá-los não dá erro — dá
resultado errado:

- **O corpo do PUT é o registro lido, inteiro.** Reconstruí-lo seria
  inventar estado, inclusive as datas no formato `/Date(...)/`, que
  voltam exatamente como vieram.
- **O valor de religar nunca é constante.** "Tipicamente 2" não é
  "sempre 2": na base há conta com outro valor, e religar com o número
  errado deixaria a conta com uma supervisão que ela nunca teve. O
  client **recusa** religar sem receber o original.
- **`success: false` chega com HTTP 200.** Olhar só o status deixaria
  passar uma conta que não mudou como se tivesse mudado.
- **A escrita é conferida relendo.** A plataforma responde 200 e segue a
  vida mesmo quando o valor não muda — foi exatamente assim que o lote
  acima passou por aplicado. Se o campo não ficou com o valor pedido,
  isso é falha, não sucesso, e a conta não entra no ledger. Registro
  falso de que a loja está coberta é pior que erro.
- **O ledger é gravado ANTES do PUT.** Se o processo morrer no meio,
  sobra uma linha dizendo "esta conta deveria estar desligada" — que se
  confere — em vez de uma conta desligada que ninguém sabe que existe e
  cujo valor original se perdeu. Se o PUT falhar, a linha é removida: o
  inverso (ledger sem conta desligada) é inofensivo.

## 4. Conta já desligada não é tocada de novo

É o erro mais caro possível aqui. Desligar uma conta que já está
desligada leria `tol_nnyc = 1` e gravaria **isso** como "valor original"
— e aí o religar restauraria 1, ou seja, não religaria nada, para
sempre, sem erro nenhum aparecendo.

Por isso a conta que continua na lista entra numa terceira categoria
("já desligadas") e não é reenviada.

## 5. Da mensagem à conta

Igual à versão anterior, e pelos mesmos motivos: números de 2 a 4
dígitos, casamento pelo número da filial, universo limitado ao grupo
Super Nosso/Apoio, **tesouraria nunca entra** (barrada duas vezes — no
universo elegível e na beira da escrita), e em caso de dúvida o módulo
não casa: "não encontrada" ou "ambígua", nunca um palpite.

## 6. Fluxo

1. **Preparar** (só leitura) — três listas: desligar, religar, não
   encontradas. Mais "já desligadas", "ambíguas" e "nunca são
   desligadas". Não grava nada.
2. **Conferir.**
3. **Aplicar** — marque e digite `DESLIGAR AVISO`. Falha por conta
   isolada, com o motivo na tela.

A pré-visualização fica na `session` e o aplicar **só aceita contas que
estão nela**: a sessão é a autorização, o formulário é o recorte dela.

## 7. O que os testes travam

Conferido **por mutação** — desligando cada guarda, o teste
correspondente falha:

- regravar conta já desligada → o `nnyc_original` vira 1 e o religar
  deixa de funcionar;
- ledger gravado depois do PUT → conta desligada sem registro;
- religar com valor fixo em vez do ledger;
- PUT montando corpo novo em vez de preservar o registro lido.

Mais: `tol_nnyc = 2` ao desligar, escrita que não pegou tratada como
falha, recusa de religar sem o original,
`success: false` com HTTP 200 tratado como falha, tesouraria barrada nos
dois pontos, falha isolada por conta, e o ciclo semanal completo
(desliga as novas, religa as que saíram).


## 8. Se o ledger dessincronizar da plataforma

Acontece quando uma escrita é reportada como aplicada sem ter sido — era
possível antes da conferência pós-escrita existir. O sintoma na tela é a
coluna **"Religa com"** mostrando um valor que não é 1: significa que a
conta já estava desligada quando entrou no ledger, e o valor de origem se
perdeu.

O conserto é **"Religar todas"**: restaura o que cada linha guarda, limpa
a lista, e aí a lista da semana pode ser rodada de novo do zero.
