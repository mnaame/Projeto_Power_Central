# Módulo: Cofre de Senhas da Empresa

Extensão de [`ARQUITETURA.md`](ARQUITETURA.md) — mesmas camadas, mesma
disciplina. Especificação de origem: complemento "Cofre de Senhas da
Empresa". Cofre compartilhado de credenciais de sistemas (câmera/DVR,
roteador, plataformas, e-mail, acessos de cliente), cifradas em repouso,
com acesso por papel e auditoria de todo acesso à senha.

## 1. Decisões de segurança (o que rege o resto do módulo)

- **Hash × Cifra não se misturam.** Login do site continua com hash
  (`app/security.py`, argon2, mão única). Senha do cofre precisa voltar em
  claro para uso → cifra Fernet (mão dupla), nunca hash.
- **Chave dedicada.** `VAULT_ENCRYPTION_KEY` (nova, em `app/config.py`,
  mesmo padrão de `ENCRYPTION_KEY`) — separada da chave geral, para que um
  vazamento de uma não comprometa a outra. Fora do banco e do Git.
- **Nunca em claro fora do momento de revelar**: banco só guarda cifrado;
  auditoria nunca leva a senha em `details`; nunca em querystring/URL; nunca
  em log.
- **Reautenticação para revelar**: mesmo já logado, confirma a própria
  senha de novo antes de decifrar — camada extra barata contra sessão
  esquecida aberta na tela de alguém.
- **Auditoria de revelar é o diferencial do módulo** — registra mesmo
  quando a reautenticação falha (`result=failure`), sem a senha.

## 2. Camadas

### 2.1 `app/domain/cofre.py` (lógica pura)

- `gerar_senha(*, tamanho=20, excluir_ambiguos=True) -> str`: usa `secrets`
  (não `random`), garante ao menos 1 minúscula/maiúscula/dígito/símbolo,
  embaralha com `secrets.randbelow` (não `random.shuffle`).
- `forca_senha(senha) -> str`: heurística simples (variedade de categoria +
  tamanho) → `fraca`/`media`/`forte`/`muito_forte`. Não é um estimador
  científico (tipo zxcvbn) — é só o suficiente para sinalizar na tela de
  cadastro; não é usado como gate de segurança.

### 2.2 `app/models/cofre.py` (`Segredo`) + migration

Campos conforme o complemento (§2): `titulo`, `categoria`, `login`,
`senha_cifrada`, `url`, `notas_cifradas`, `nivel`
(`CheckConstraint IN ('equipe', 'restrito')`), `criado_por_user_id`,
`atualizado_por_user_id`, `criado_em`/`atualizado_em` (TZDateTime),
`expira_em` (Date, opcional). `categoria` é uma lista sugerida na tela
(select), sem `CheckConstraint` no banco — o complemento só pede o
constraint explicitamente em `nivel`.

### 2.3 `app/services/cofre_service.py`

- `cifrar`/`decifrar` — Fernet com `config["VAULT_ENCRYPTION_KEY"]`;
  decifra que falha (chave errada/trocada) vira `CofreDecifraError` com
  mensagem amigável, nunca derruba a tela.
- `notas_em_claro(segredo, *, config)` — devolve as notas decifradas para
  o formulário de edição. **Diferente da senha, não exige
  reautenticação**: as notas são contexto do item (por onde entrar, com
  quem falar), e quem chegou na tela de edição já passou pelo controle de
  nível de `obter_ou_negar`.
  > Isso não é conforto, é correção de um bug real: `SegredoForm(obj=segredo)`
  > preenche por **nome do atributo** e a coluna é `notas_cifradas`, então
  > o campo chegava vazio à tela. O sintoma visível era "a nota some"; o
  > invisível era pior — salvar qualquer outro campo gravava vazio por
  > cima e **destruía a nota**, porque `atualizar` grava o que veio do
  > formulário. Na listagem aparece só o selo "com notas"
  > (`notas_cifradas is not None`); o conteúdo não é decifrado ali.
- `criar`/`atualizar`/`excluir` — campo senha vazio no formulário de edição
  = "não trocar" (mesma UX de qualquer formulário de credencial).
- `listar(*, usuario, busca, categoria)` — filtra `nivel='equipe'` para
  quem não é admin, direto na query (nunca filtra na tela depois de buscar
  tudo).
- `obter_ou_negar(id, *, usuario)` — usado por toda rota que recebe um id
  direto na URL (ver/editar/revelar/excluir): `CofreNaoEncontradoError` →
  404; `CofreAcessoNegadoError` → 403 auditado (mesma disciplina de
  `roles_required`, replicada aqui porque a checagem é por registro, não
  por rota inteira).
- `revelar(segredo, *, usuario, senha_reautenticacao, config)` — confere a
  reautenticação (`app.security.verify_password`), decifra, audita
  `cofre_senha_revelada` (success com id/título/categoria — nunca a senha;
  failure quando a reautenticação erra, também sem a senha).

## 3. Web — blueprint `cofre` (prefixo `/cofre`)

- **Lista** (`GET /cofre`): busca por texto + filtro por categoria; senha
  nunca vem embutida na tabela.
- **Revelar** (`POST /cofre/<id>/revelar`): cada linha tem um
  `<details>`/`<summary>` (mesmo padrão de `auvo/painel.html` para "ver"
  erro) que expande um mini-formulário pedindo a senha do usuário. Sucesso
  **re-renderiza a própria lista** (não redirect) com a senha revelada só
  naquela resposta — nunca fica em flash/sessão. JS mínimo em `app.js`
  apaga o texto da tela e limpa o clipboard depois de ~30s; se
  `navigator.clipboard` não existir (HTTP fora de localhost, comum em
  acesso pela rede local), o botão "Copiar" some e sobra a seleção manual.
- **Novo/Editar**: formulário com botão "gerar senha forte" (preenche via
  JS o campo com o valor já gerado no servidor — sem reinventar gerador em
  JS) e indicador de força. Marcar `nivel=restrito` exige admin (checado na
  rota, não só na tela).
- **Configuração** (admin): aviso da `VAULT_ENCRYPTION_KEY` — perder a
  chave torna as senhas irrecuperáveis; orienta backup **separado** do
  backup do banco.
- **Backup** (`/cofre/backup`, só admin) — ver §3.1.
- **Auditoria de revelar**: reaproveita a tela genérica já existente
  (`admin.auditoria`) — o filtro de ação já é populado dinamicamente a
  partir do que existe na tabela, então `cofre_senha_revelada` aparece lá
  sozinho assim que o primeiro evento for gravado. Não precisa de tela
  nova (extra do §6 do complemento já coberto de graça).

### 3.1 Backup — arquivo cifrado por senha

O backup do banco (§6 do `OPERACAO.md`) copia o cofre **cifrado**: sem a
`VAULT_ENCRYPTION_KEY` ele não serve para nada. E a chave mora na máquina
que se perdeu. Ou seja, a cópia do banco sozinha não protege contra o
cenário que mais assusta — perder o servidor inteiro.

Daí a decisão que define o módulo: **o backup do cofre NÃO usa a
`VAULT_ENCRYPTION_KEY`**. Ele é cifrado com uma senha que o admin digita na
hora, e carrega dentro de si o sal e os parâmetros de derivação
(PBKDF2-HMAC-SHA256, 600 mil iterações — patamar OWASP 2023). O arquivo é
autossuficiente: restaura numa instalação nova, com chave nova. Se ele
dependesse da chave antiga, seria inútil exatamente no dia em que é a
única cópia — há um teste de integração que encena esse desastre completo.

O que o formato faz de propósito:

- **JSON**, para poder ser inspecionado sem ferramenta especial;
- **metadados em claro** (data, contagem de itens) — dá para escolher entre
  dois arquivos sem precisar abrir nenhum;
- **nada além da contagem** sai do envelope cifrado: nem título, nem login,
  nem URL. Um teste garante que nenhum desses valores aparece no arquivo;
- **Fernet autenticado**: senha errada e arquivo adulterado dão o mesmo
  erro, e não há como distinguir — a mensagem cobre os dois casos.

Regras de operação:

- **Só admin.** O arquivo leva o cofre inteiro, itens `restrito` incluídos.
- **Exportar exige reautenticação**, pelo mesmo motivo que revelar uma
  senha exige: exportar é revelar todas de uma vez. Restaurar também exige,
  porque escreve no cofre.
- **O arquivo nunca toca o disco do servidor** — é montado em memória e
  enviado. Ao contrário dos outros exports, não fica cópia em
  `instance/reports/` esperando alguém achar.
- **Restaurar não sobrescreve por padrão.** Casa por título (sem
  diferenciar maiúsculas); item que já existe é ignorado a menos que
  "substituir" esteja marcado. Restaurar por engano em cima de um cofre
  vivo é pior do que restaurar de menos, porque o que foi sobrescrito não
  volta.
- **Item sem título ou sem senha é pulado**, contado em `invalidos`: um
  arquivo meio corrompido deve restaurar o que dá, não falhar inteiro.
- **"Conferir arquivo"** abre o backup e diz o que tem dentro sem gravar
  nada. Existe porque backup que nunca foi aberto é esperança, não backup.
- Auditoria: `cofre_backup_exportado` / `cofre_backup_restaurado`, só
  contadores — nunca a senha do backup, nunca uma senha do cofre.
- **Sem tamanho mínimo para a senha do backup.** Houve uma trava de 12
  caracteres aqui; saiu a pedido de quem opera o cofre, e a razão é boa:
  quem guarda o arquivo é quem decide o quanto quer protegê-lo, e uma
  recusa não ensina nada — só impede. O que ficou no lugar informa em vez
  de barrar: indicador de força ao digitar e o texto dizendo o que muda.
  `TAMANHO_RECOMENDADO` (12) só alimenta esse aviso. O único caso ainda
  barrado é senha **vazia** — cifrar com nada não é cifrar, e o arquivo
  sairia abrível por qualquer um que conheça o formato.

> **A senha do backup não tem recuperação.** Não é um "esqueci minha
> senha": é cifragem de verdade, e ninguém consegue abrir o arquivo sem
> ela. Ela precisa ser guardada **separada do arquivo** — cofre físico,
> gerenciador pessoal ou envelope lacrado. Guardar os dois juntos é o
> mesmo que não cifrar.

## 4. Fases

| Fase | Entrega | Prova |
|---|---|---|
| **COF1** ✅ | Domínio + modelo + migration + `VAULT_ENCRYPTION_KEY` + `cofre_service.py` | Unit (gerador/força) + integração (cifra ida-e-volta, filtro por papel, reautenticação, auditoria sem senha) |
| **COF2** ✅ | Aba web completa (lista, revelar, criar/editar, config) | Integração web (RBAC, nível restrito, chave ausente não derruba a tela) + screenshots claro/escuro |
| **COF3** ✅ | Docs (`OPERACAO.md`) + validação final | Suíte completa verde |

Módulo concluído. `admin.auditoria` (tela genérica já existente) cobre
`cofre_senha_revelada`/`cofre_criado`/`cofre_editado`/`cofre_excluido`/
`cofre_acesso_negado` sem precisar de tela própria — o filtro de ação é
populado dinamicamente a partir do que já foi gravado.

O que NUNCA entra no repositório: `VAULT_ENCRYPTION_KEY` de verdade, e
qualquer senha real de sistema da empresa.
