# Módulo: Contas em Teste (Super Nosso)

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md). Coloca as lojas da lista
semanal do Super Nosso em **teste** por uma semana, para o serviço
noturno não gerar falha de arme.

## 1. ⚠️ É a única escrita do sistema, e ela suprime alarme

Conta em teste faz a central **parar de tratar a falha de arme** dela.
Para a loja que não vai armar naquela semana, é exatamente o efeito
desejado. Para qualquer outra, é um buraco de segurança que o sistema não
tem como perceber — o erro aparece quando alguém tenta entrar.

Até 13/10/2026 este sistema tinha **zero** caminhos de escrita, e isso
era uma propriedade que se podia afirmar sem ressalva. Hoje existe
exatamente um, e por isso ele é cercado assim:

| Trava | Por quê |
|---|---|
| Admin-only | Suprimir alarme não é operação de rotina |
| Pré-visualização obrigatória | A lista vem de uma mensagem escrita por gente |
| Confirmação digitada (`COLOCAR EM TESTE`) | Clique errado não basta para gravar |
| **Janela que expira sozinha** | É o que impede "para sempre" |
| Auditoria do lote | Contagens, nunca nome de cliente |
| Recorte ao grupo Super Nosso/Apoio | Erro de digitação não alcança a base |
| **Tesouraria barrada, duas vezes** | Ela fica armada durante o serviço noturno |

### A tesouraria nunca entra

A tesouraria é **conta separada** da loja no cadastro — `SUPER NOSSO
CASTELO LOJA` (0330) e `SUPER NOSSO CASTELO TESOURARIA` (0327). Ela não
participa do serviço noturno: fica armada, e tem que continuar sendo
tratada.

Hoje, na base real, **nenhuma tesouraria tem número de filial no nome**,
então o casamento por número nunca a alcançaria. Mas isso é uma
propriedade do cadastro de hoje, não uma garantia: basta alguém renomear
a conta para "CASTELO TESOURARIA FILIAL 688" e a sorte acaba. A regra
fica no código (`PADROES_NUNCA_EM_TESTE`), onde não depende de ninguém
lembrar.

São **duas barreiras**, de propósito:

1. No universo elegível, quando a pré-visualização é montada — e a conta
   barrada aparece numa lista própria na tela, porque exclusão
   silenciosa é indistinguível de esquecimento.
2. Na beira da escrita, relendo o cadastro. A primeira depende de o lote
   ter vindo de uma pré-visualização íntegra; esta não depende de nada.
   Barreira duplicada num caminho que suprime alarme é barata.

### A janela é a segurança, não o cuidado de quem opera

`est_nduracion = 5` e `est_dfechahasta = início + 5 dias` fazem o estado
expirar sozinho. **Cinco dias = segunda a sexta**: o serviço noturno é de
dia útil, e no fim de semana a loja arma normal. Cobrir sábado e domingo
seria suprimir alarme em dois dias nos quais ninguém pediu isso. **Não existe passo de remover** — e essa ausência é
deliberada: um passo de remover é um passo que se pode esquecer, e
esquecer deixaria a loja silenciada indefinidamente. Quando a lista da
semana seguinte chega, a anterior já venceu.

Daí também a recusa de duração menor que 1 dia, no domínio **e** no
client: uma janela vazia é uma conta em teste sem previsão de voltar.

## 2. O endpoint (HAR 19/10)

A plataforma **grava por GET**. O verbo mente; o efeito é escrita, e o
resto do sistema trata assim.

```
GET /Rest/search/EstadoUpd
  Id              = <cue_iid>
  Name            = " "          (um espaço, como no HAR)
  est_iidcuenta   = <cue_iid>
  est_nestado     = 1
  est_ntipo       = 3            (tipo "em teste")
  est_dfechadesde = YYYY-MM-DDTHH:MM:SS   (hora local, sem timezone)
  est_nduracion   = 7            (DIAS)
  est_dfechahasta = YYYY-MM-DDTHH:MM:SS   (início + nduracion)
  est_mnota       = <nota>
  est_cData       = ""
  token           = <cookie OAuth_Token>
```

Dois detalhes que têm teste próprio porque errá-los não dá erro, dá
resultado errado:

- **`success: false` vem com HTTP 200.** Olhar só o status deixaria
  passar uma conta que NÃO entrou em teste como se tivesse entrado.
- **O `token` é lido dentro da tentativa.** Ele viaja na query, não só no
  cookie; repetir com o valor antigo depois de relogar falharia pelo
  mesmo motivo que a primeira vez.

## 3. Da mensagem à conta (`app/domain/contas_teste.py`, puro)

O Super Nosso manda, por semana, uma mensagem escrita por gente:

```
420 SN. FLEMING
688 SN. CASTELO
530 AP. VENDA NOVA
```

O nome abreviado não bate com o cadastro (`SN. FLEMING` ×
`SUPER NOSSO FLEMING FILIAL 420`). **Quem casa é o número da filial**,
que aparece nos dois lados — e só ele.

- Números de 2 a 4 dígitos. Mais que isso é CNPJ, telefone ou CEP que
  vieram junto no texto colado.
- No nome da conta, `FILIAL <n>` tem precedência sobre um número solto:
  `SUPER NOSSO CASTELO FILIAL 688` ganha de `SUPER NOSSO LOJA 688
  BARREIRO FILIAL 700`.
- **Três desfechos, e os três aparecem na tela**: casada, não encontrada
  e **ambígua**. Em caso de dúvida o módulo não casa — escolher "a
  primeira" entre duas candidatas colocaria em teste uma loja que talvez
  vá armar hoje à noite.

O universo de busca é só o grupo **Super Nosso/Apoio**
(`disparos_geral.grupo_do_cliente`, reaproveitado inteiro). Aqui o
recorte não é cosmético, é contenção.

## 4. Fluxo

1. **Preparar** (só leitura) — lê a mensagem, carrega as contas, casa, e
   mostra as três listas. Não grava nada.
2. **Conferir** — é o passo que separa "a lista da semana" de "silenciar
   a loja errada".
3. **Aplicar** — marque as contas, digite a confirmação. Uma chamada por
   conta, com pausa curta; **falha numa não derruba as outras**, e o
   motivo de cada falha aparece na tela.
4. Não há passo 4.

A pré-visualização fica na `session` entre preparar e aplicar, e **o
aplicar só aceita contas que estão nela**: a sessão é a autorização, o
formulário é o recorte dela. Sem isso, um POST montado à mão colocaria em
teste qualquer conta da base — inclusive uma que ninguém conferiu.

Depois de aplicar, a pré-visualização é descartada: senão dava para
aplicar o mesmo lote de novo sem conferir.

## 5. Configuração

| Chave | Padrão | Para quê |
|---|---|---|
| `teste_duracao_dias` | `5` | Segunda a sexta. Mais que 7 faz duas listas se sobreporem |
| `teste_nota_padrao` | `Serviço noturno durante a semana.` | Vai no `est_mnota` |
| `teste_tipo` | `3` | `est_ntipo` do estado "em teste" |

## 6. O que os testes travam

Conferido **por mutação** — desligando cada guarda, o teste correspondente
falha:

- aceitar conta fora da pré-visualização → o POST montado à mão passa;
- filial ambígua escolhendo a primeira → a loja errada entra em teste;
- universo sem o recorte Super Nosso/Apoio → o número solto alcança a
  base inteira.

E as duas barreiras da tesouraria, cada uma com o seu teste: tirando
qualquer uma delas, a conta protegida entra no lote.

Mais os parâmetros exatos do `EstadoUpd`, a janela (`dfechahasta` =
início + duração), a recusa de duração zero antes de qualquer chamada, e
`success: false` com HTTP 200 sendo tratado como falha.


## 7. O que o cadastro real mostrou (19/10)

Rodando a lista de exemplo contra as 23 contas do grupo:

| Filial | Resultado |
|---|---|
| 420 | `SUPER NOSSO FLEMING FILIAL 420 - LOJA` |
| 530 | `APOIO VENDA NOVA FILIAL 530` |
| **688** | **não encontrada** |

**Castelo não tem número de filial no nome.** As contas são
`SUPER NOSSO CASTELO LOJA` e `SUPER NOSSO CASTELO TESOURARIA`, e o
casamento é por número — então 688 não acha nada. O conserto é no
cadastro da PowerCentral (renomear para incluir `FILIAL 688` na conta da
**loja**, nunca na da tesouraria), e não no código: inventar um
casamento por nome aqui é o tipo de palpite que coloca a loja errada em
teste.

Também existe filial **duplicada**: `MOMENTO CEARA FILIAL 64` e
`MOMENTO CEARA ESTACIONAMENTO FILIAL 64`. O módulo marca como **ambígua**
e não escolhe — são dois pontos diferentes do mesmo endereço, e qual
deles entra em teste é decisão de quem conhece a operação.
