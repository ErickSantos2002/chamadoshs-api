# Concorrência da TI (API-12)

Contrato da versão nas escritas de chamado da TI, o que a API-12 corrigiu e o
que continua dependendo do cliente. Branch `feat/setor-destino-api-12`, a
partir da API-11 (`5547893`). Sem migration, sem variável nova, sem mudança no
contrato HTTP.

## 1. O defeito (classe B)

Na API-11 o `PUT /chamados/{id}` da TI aceitava `versao_esperada` opcional e
a conferia — mas sem travar a linha. Duas requisições com a mesma versão liam
o chamado, conferiam a versão (as duas batiam) e só então gravavam: as duas
recebiam 200, e a segunda desfazia a primeira no mesmo campo.

**Reprodução anterior:** homologação local do FE-5 (PG15 descartável, API-11
inalterada, dados fictícios), dois PUTs largando juntos com a mesma versão:
12 de 20 rodadas com as duas gravando. Na API-12, a mesma cena com o código da
API-11 (mutação M1 abaixo) dá 200/200 já na segunda rodada.

**Causa:** `conferir_versao` comparava a versão de uma leitura sem
`FOR UPDATE`; entre a conferência e o `UPDATE` não havia nada que impedisse
outra transação de conferir a mesma versão. O próprio comentário da função
dizia que só vale com a linha travada; a TI não a travava. As marcas
(`cancelar`, `arquivar`, `desarquivar`) tinham o mesmo desenho.

## 2. A correção

Quando a escrita da TI manda `versao_esperada`, ela segue o caminho que a
Qualidade usa desde a API-4b/4c:

1. autorização sem trava (`buscar_chamado_alteravel`: 404, depois 403);
2. `db.refresh(chamado, with_for_update=True)` — `SELECT ... FOR UPDATE` da
   linha do chamado; quem chegar depois espera;
3. `conferir_versao` na linha travada (409 se não bate);
4. validação do responsável, campos, histórico na mesma transação
   (`adicionar_historico`), **um commit** — que solta a trava;
5. webhook de atribuição só depois do commit.

Vale para o `PUT` e para as três marcas. Nenhum mecanismo novo: a mesma
função, o mesmo `refresh`, o mesmo handler de 409. `UPDATE` condicional por
versão foi descartado: mudaria a forma de gravar o histórico e o 409 deixaria
de trazer a versão travada, sem ganho sobre o lock que já existe.

**Locks:** só a linha de `chamados` (o `INSERT` do histórico pede
`FOR KEY SHARE` na mesma linha, que a transação já tem). Uma linha, uma ordem:
não há ciclo possível entre duas escritas da API.

## 3. Semântica

| Situação | Resposta | Grava |
|---|---|---|
| TI com versão certa | 200, `versao` nova | chamado + histórico num commit; webhook depois |
| TI com versão velha | 409 `{detail, codigo: "versao_desatualizada", versao_atual}` | nada — nem campo, nem histórico, nem webhook |
| Duas TI com a mesma versão ao mesmo tempo | uma 200, a outra 409 | só a primeira |
| TI com versão, campos diferentes, ao mesmo tempo | a segunda recebe 409 | só a primeira — a versão é do chamado, não do campo; o FE-5 relê e oferece salvar de novo |
| TI sem versão | 200 | o fluxo de antes: sem trava, dois commits, vale a última |
| Versão inválida (`null`, booleana, texto, 0, negativa, fracionária) | 422 | nada |
| Quem não lê o chamado | 404 sem versão, sem esperar a trava | nada |
| Conta de serviço, perfil sem permissão | 403 sem versão, sem esperar a trava | nada |
| Qualidade | igual à API-11: 428 sem versão, 409, trava | — |

**Obrigatoriedade:** a versão continua **opcional** na TI. Exigi-la quebraria
as ações rápidas do FE-5 e qualquer cliente antigo; fica para uma decisão
própria (§7).

## 4. Compatibilidade

- **Clientes TI antigos (sem versão):** sem mudança de comportamento, nem de
  SQL — o teste estrutural `test_put_sem_versao_nao_pede_o_lock` e o T11 da
  API-4c seguem passando.
- **Qualidade:** sem mudança. T1–T14 inalterados e aprovados.
- **FE-5 `ad01793`:** compatível, sem mudança no front.

| Fluxo (FE-5) | FE-5 envia versão? | API-12 exige? | Resultado |
|---|---|---|---|
| Editar TI (página) | sim, a relida antes de salvar | não | **protegido**: 409 real também entre duas gravações simultâneas |
| Editar Qualidade | sim (obrigatória) | sim, como antes | igual |
| Ações rápidas da TI (status) | não | não | risco residual: vale a última |
| Resolver (TI) | não | não | risco residual: vale a última |
| Cancelar com motivo (TI) | não (cancelar + PUT do motivo) | não | risco residual; duas escritas, não atômicas |
| Arquivar / desarquivar (TI) | não | não | risco residual |
| Trocar responsável no modal (TI) | não | não | risco residual |

O comportamento percebido pelo FE-5 só muda num caso: duas edições da página
salvas ao mesmo tempo, que antes passavam as duas e agora dão 409 a uma — que
o FE-5 já trata ("Outra pessoa salvou este chamado enquanto você salvava").

## 5. Escritas de chamado (inventário)

| Rota | Entrada | Altera | Quem | Aceita versão | Exige | Sobe `versao` | Trava | Histórico | Webhook |
|---|---|---|---|---|---|---|---|---|---|
| `PUT /chamados/{id}` | `ChamadoUpdate` | qualquer campo enviado | equipe no alcance (humano) | sim | Qualidade | sim | Qualidade; TI com versão | troca de status; na Qualidade, também a de responsável (API-14) | TI, troca de responsável, depois do commit |
| `PATCH .../cancelar` | `ChamadoMarca` opcional | `cancelado` | solicitante; equipe no alcance | sim | Qualidade | sim | Qualidade; TI com versão | sim | não |
| `PATCH .../arquivar` | idem | `arquivado` | equipe no alcance | sim | Qualidade | sim | idem | sim | não |
| `PATCH .../desarquivar` | idem | `arquivado` | equipe no alcance | sim | Qualidade | sim | idem | sim | não |
| `PATCH .../atendimento` | `ChamadoAtendimento` | `status`, `solucao` | responsável da Qualidade | sim | sim (só Qualidade) | sim | sempre | sim | não |
| `PATCH .../avaliar` | `ChamadoAvaliacao` | `avaliacao` | solicitante | não | não | sim | não | sim (commit próprio) | não |
| `DELETE /chamados/{id}` | — | apaga | administrador humano | não | não | — | não | apaga junto | não |

"Ação rápida", "resolver" e "motivo do cancelamento" não são rotas próprias:
são `PUT` (status; status + solução; solução) e `PATCH .../cancelar`. Na TI,
sem versão, qualquer um deles pode sobrescrever o mesmo campo de outra
escrita e competir com um `PUT` com versão: espera a trava dele e grava por
cima (`test_acao_rapida_sem_versao_espera_a_trava_e_grava_por_cima`), e o
histórico dessa escrita traz o status anterior lido antes da espera.

**Mudança mínima para fechar (não feita, depende de autorização):** o FE
mandar `versao_esperada` nas escritas da TI que já a aceitam (ações rápidas,
resolver, cancelar, arquivar, desarquivar, responsável) — nenhuma mudança de
contrato na API, porque todas já aceitam o campo e, desde a API-12, travam
quando ele vem. O cancelar com motivo continua sendo duas escritas; juntar
pede rota ou campo novo. Testes necessários: os desta matriz para cada rota
com versão (já existem para PUT e marcas) e, no FE, o 409 em cada ação.

## 6. Testes

- **PostgreSQL** (`tests/test_concorrencia_ti_postgres.py`, 40): mesmo campo
  nas duas ordens para prioridade, status, categoria, responsável e solução
  (vencedora 200, perdedora 409 com a versão nova, versão +1, histórico e
  webhook só da vencedora); escrita recusada com vários campos sem gravar
  nenhum; 25 rodadas de largada conjunta por barreira (25/25 com exatamente
  uma 200); campos diferentes; marcas × PUT nas duas ordens; falha depois do
  flush (chamado e histórico desfeitos, trava solta, sem webhook); falha
  depois do commit (reenviar a mesma versão é 409, sem gravar duas vezes);
  mesmos valores (versão parada, sem histórico); 401/403/404 sem versão e sem
  esperar a trava; 422; permissão revogada durante a espera; Qualidade 428;
  e o que fica sem versão (sem trava, as duas gravam, ação rápida por cima).
- **SQLite** (`tests/test_concorrencia_ti.py`, 8): o SQLite ignora o
  `FOR UPDATE` e não tem o trigger de versão, então não se simula a disputa.
  Prova-se o contrato: com versão, um `refresh` com trava e **um** commit;
  sem versão, nenhum e dois; versão velha sem commit, histórico ou webhook;
  marcas idem.
- **T1–T14** (`tests/test_concorrencia_versao_postgres.py`) e a pré-condição
  da API-4b (`tests/test_precondicao_de_versao_postgres.py`): inalterados,
  aprovados.
- **Mutação:** M1 sem trava no PUT (a API-11), M2 conferir antes da trava, M3
  sem comparação, M4 escrever apesar do 409, M5 histórico em commit próprio,
  M6 webhook antes da conferência, M7 commit parcial, M8 Qualidade sem 428,
  M9 marcas sem trava — todas mortas pelos testes novos.

## 7. Riscos residuais

1. **TI sem versão:** vale a última escrita — ações rápidas, resolver,
   cancelar com motivo, arquivar, desarquivar e responsável no modal, como o
   FE-5 manda hoje. A classe B **não** está eliminada nesses fluxos.
2. **Autorização lida antes da trava:** quem perde a permissão enquanto
   espera a trava grava a escrita já autorizada, se a versão bater (o mesmo
   limite da Qualidade desde a API-4c; teste
   `test_permissao_revogada_enquanto_espera_a_trava_ainda_grava`).
3. **Histórico:** só troca de status entra; prioridade, categoria,
   responsável e solução não deixam trilha.
4. **Falha depois do commit:** o cliente que não recebeu a resposta e reenvia
   recebe 409 da própria escrita; o FE-5 mostra o conflito, não duplica.
5. **SQLite** não reproduz a disputa: a prova de concorrência é só PostgreSQL.

## 8. Rollback

Voltar a imagem da API-11 (`5547893`). Sem migration nem dado novo: nada a
desfazer no banco. O FE-5 continua funcionando contra a API-11 — a edição da
TI volta a ter a janela de corrida do §1, que é o estado de antes.
