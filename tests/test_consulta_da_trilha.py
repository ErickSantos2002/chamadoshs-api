"""
Testes da leitura da trilha: `GET /usuarios/{id}/eventos` e `GET /eventos`.

Gravar sem conseguir ler não é auditoria. O passo anterior encheu
`eventos_de_conta` sem nenhuma forma de consultar aquilo pela aplicação — a
resposta a um pedido de evidência ainda passava por SQL no banco.

Duas rotas porque são duas perguntas. "O que aconteceu com esta conta" é o
painel do modal de usuário, escopado por alvo. "O que aconteceu no período" e
"o que fulano andou fazendo" são a tela de auditoria, e atravessam os dois
cadastros — daí a listagem geral juntar conta e setor num formato só.

O que mais se erra aqui é o filtro de data: `ate` interpretado como meia-noite
faz o último dia do período sumir, e o dia que mais se filtra é o de hoje.
"""

from datetime import date, datetime, timedelta

from app.models import EventoDeConta, EventoDeSetor, Setor


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def _semear(sessao, dados):
    """
    Eventos plantados direto na tabela, com datas escolhidas.

    Direto e não pela API de propósito: o que se testa aqui é a consulta, e
    `created_at` precisa ser controlado para o filtro de período ter o que
    separar.
    """
    sessao.add(Setor(id=2, nome="Financeiro"))
    sessao.flush()

    ontem = datetime(2026, 8, 11, 15, 0)
    hoje_cedo = datetime(2026, 8, 12, 8, 30)
    hoje_tarde = datetime(2026, 8, 12, 17, 45)

    sessao.add_all([
        EventoDeConta(
            id=1, usuario_id=dados["comum_id"], ator_id=dados["admin_id"],
            acao="desativacao", valor_anterior="true", valor_novo="false",
            origem="DELETE /api/v1/usuarios/{id}", created_at=ontem,
        ),
        EventoDeConta(
            id=2, usuario_id=dados["comum_id"], ator_id=dados["tecnico_id"],
            acao="alteracao_de_nome", valor_anterior="a", valor_novo="b",
            origem="PUT /api/v1/usuarios/{id}", created_at=hoje_cedo,
        ),
        EventoDeConta(
            id=3, usuario_id=dados["tecnico_id"], ator_id=dados["admin_id"],
            acao="alteracao_de_perfil", valor_anterior="Usuario", valor_novo="Tecnico",
            origem="PUT /api/v1/usuarios/{id}", created_at=hoje_tarde,
        ),
        EventoDeSetor(
            id=1, setor_id=2, setor_nome="Financeiro", ator_id=dados["admin_id"],
            acao="desativacao", valor_anterior="true", valor_novo="false",
            origem="PATCH /api/v1/setores/{id}/desativar", created_at=hoje_cedo,
        ),
    ])
    sessao.commit()
    return {"ontem": ontem.date(), "hoje": hoje_cedo.date()}


class TestPainelDaConta:
    """`GET /usuarios/{id}/eventos` — o histórico dentro do modal de usuário."""

    def test_devolve_so_os_eventos_daquela_conta(self, cliente, dados, sessao, autenticar):
        _semear(sessao, dados)

        resposta = cliente.get(
            f"/api/v1/usuarios/{dados['comum_id']}/eventos",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert {e["id"] for e in resposta.json()} == {1, 2}

    def test_mais_recente_primeiro(self, cliente, dados, sessao, autenticar):
        """
        A leitura da trilha é do presente para trás: estado atual da conta, e os
        eventos desfazendo passo a passo.
        """
        _semear(sessao, dados)

        eventos = cliente.get(
            f"/api/v1/usuarios/{dados['comum_id']}/eventos",
            headers=_como_admin(autenticar, dados),
        ).json()

        assert [e["id"] for e in eventos] == [2, 1]

    def test_traz_o_nome_de_quem_fez(self, cliente, dados, sessao, autenticar):
        """
        Sem o nome do ator a tela mostraria um id, e a pergunta da auditoria é
        "quem" — não "qual número".
        """
        _semear(sessao, dados)

        eventos = cliente.get(
            f"/api/v1/usuarios/{dados['comum_id']}/eventos",
            headers=_como_admin(autenticar, dados),
        ).json()

        por_id = {e["id"]: e for e in eventos}
        assert por_id[1]["ator_nome"] == "admin.teste"
        assert por_id[2]["ator_nome"] == "tecnico.teste"
        assert por_id[1]["alvo_nome"] == "usuario.teste"

    def test_o_que_a_conta_fez_com_outras_nao_entra(self, cliente, dados, sessao, autenticar):
        """
        A rota é escopada pelo ALVO. O técnico praticou o evento 2 e sofreu o 3;
        só o 3 é história da conta dele. Misturar os dois lados responderia a
        pergunta errada — para "o que fulano andou fazendo" existe o filtro
        `ator_id` na listagem geral.
        """
        _semear(sessao, dados)

        eventos = cliente.get(
            f"/api/v1/usuarios/{dados['tecnico_id']}/eventos",
            headers=_como_admin(autenticar, dados),
        ).json()

        assert [e["id"] for e in eventos] == [3]

    def test_conta_inexistente_devolve_404(self, cliente, dados, autenticar):
        """
        Não lista vazia: um id errado que responde `[]` se lê como "esta conta
        nunca foi tocada", que é uma afirmação sobre auditoria — e falsa.
        """
        resposta = cliente.get(
            "/api/v1/usuarios/9999/eventos", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 404

    def test_e_restrito_a_administrador(self, cliente, dados, sessao, autenticar):
        """
        A trilha diz quem fez o quê com a conta de quem: é informação de
        administração, e não de perfil próprio.
        """
        _semear(sessao, dados)

        resposta = cliente.get(
            f"/api/v1/usuarios/{dados['comum_id']}/eventos",
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 403


class TestListagemGeral:
    """`GET /eventos` — a tela de auditoria, atravessando os dois cadastros."""

    def test_junta_conta_e_setor_ordenados_por_data(self, cliente, dados, sessao, autenticar):
        _semear(sessao, dados)

        eventos = cliente.get("/api/v1/eventos/", headers=_como_admin(autenticar, dados)).json()

        assert [e["chave"] for e in eventos] == [
            "usuario:3",   # hoje 17:45
            "usuario:2",   # hoje 08:30
            "setor:1",     # hoje 08:30 — empate resolvido pelo id, que entre
                           # tabelas diferentes é arbitrário: só precisa ser
                           # sempre o mesmo. Ver `_ordem` em trilha_service.
            "usuario:1",   # ontem
        ]

    def test_a_chave_distingue_ids_que_colidem(self, cliente, dados, sessao, autenticar):
        """
        Existe evento de conta 1 e evento de setor 1. Sem a chave composta, uma
        lista no frontend teria duas linhas com a mesma key.
        """
        _semear(sessao, dados)

        eventos = cliente.get("/api/v1/eventos/", headers=_como_admin(autenticar, dados)).json()

        ids = [e["id"] for e in eventos]
        chaves = [e["chave"] for e in eventos]
        assert len(set(ids)) < len(ids)
        assert len(set(chaves)) == len(chaves)

    def test_filtro_por_alvo(self, cliente, dados, sessao, autenticar):
        _semear(sessao, dados)
        headers = _como_admin(autenticar, dados)

        so_setor = cliente.get("/api/v1/eventos/?alvo=setor", headers=headers).json()
        so_usuario = cliente.get("/api/v1/eventos/?alvo=usuario", headers=headers).json()

        assert [e["chave"] for e in so_setor] == ["setor:1"]
        assert {e["alvo_tipo"] for e in so_usuario} == {"usuario"}

    def test_alvo_invalido_devolve_400(self, cliente, dados, sessao, autenticar):
        """Dado inválido do cliente, não defeito do servidor."""
        _semear(sessao, dados)

        resposta = cliente.get(
            "/api/v1/eventos/?alvo=chamado", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 400

    def test_filtro_por_ator_atravessa_os_dois_cadastros(
        self, cliente, dados, sessao, autenticar
    ):
        """
        "O que fulano andou fazendo" — a pergunta que o painel da conta não
        responde, e que não para na fronteira entre usuários e setores.
        """
        _semear(sessao, dados)

        eventos = cliente.get(
            f"/api/v1/eventos/?ator_id={dados['admin_id']}",
            headers=_como_admin(autenticar, dados),
        ).json()

        assert [e["chave"] for e in eventos] == ["usuario:3", "setor:1", "usuario:1"]

    def test_periodo_inclui_o_ultimo_dia_inteiro(self, cliente, dados, sessao, autenticar):
        """
        O erro clássico deste filtro: `ate` tratado como meia-noite faz sumir o
        dia inteiro que a pessoa pediu. O evento 3 é de 17:45 do dia `ate`, e
        precisa aparecer.
        """
        datas = _semear(sessao, dados)

        eventos = cliente.get(
            f"/api/v1/eventos/?de={datas['hoje']}&ate={datas['hoje']}",
            headers=_como_admin(autenticar, dados),
        ).json()

        assert [e["chave"] for e in eventos] == ["usuario:3", "usuario:2", "setor:1"]

    def test_periodo_recorta_o_comeco(self, cliente, dados, sessao, autenticar):
        datas = _semear(sessao, dados)

        eventos = cliente.get(
            f"/api/v1/eventos/?ate={datas['ontem']}",
            headers=_como_admin(autenticar, dados),
        ).json()

        assert [e["chave"] for e in eventos] == ["usuario:1"]

    def test_paginacao_nao_repete_nem_perde_linha(self, cliente, dados, sessao, autenticar):
        """
        A mescla das duas tabelas é feita em Python, então a paginação é o
        ponto onde ela erraria em silêncio. Duas páginas de dois precisam dar
        exatamente a lista inteira, sem repetição.
        """
        _semear(sessao, dados)
        headers = _como_admin(autenticar, dados)

        inteira = cliente.get("/api/v1/eventos/", headers=headers).json()
        pagina1 = cliente.get("/api/v1/eventos/?skip=0&limit=2", headers=headers).json()
        pagina2 = cliente.get("/api/v1/eventos/?skip=2&limit=2", headers=headers).json()

        assert [e["chave"] for e in pagina1 + pagina2] == [e["chave"] for e in inteira]

    def test_empate_de_data_tem_ordem_estavel(self, cliente, dados, sessao, autenticar):
        """
        Uma edição que muda dois campos grava dois eventos no mesmo instante.
        Sem desempate por id, duas chamadas iguais devolveriam ordens
        diferentes — e a paginação repetiria uma linha e engoliria a outra.
        """
        _semear(sessao, dados)
        headers = _como_admin(autenticar, dados)

        primeira = cliente.get("/api/v1/eventos/", headers=headers).json()
        segunda = cliente.get("/api/v1/eventos/", headers=headers).json()

        assert [e["chave"] for e in primeira] == [e["chave"] for e in segunda]

    def test_paginacao_recusa_valores_fora_da_faixa(self, cliente, dados, sessao, autenticar):
        """
        A mescla termina num `juntos[skip : skip + limit]`, e slice de Python
        aceita índice negativo contando do fim: `skip=-5` devolveria as linhas
        mais ANTIGAS numa consulta que promete as mais recentes, sem erro
        nenhum. 422 é a resposta certa para parâmetro fora da faixa.
        """
        _semear(sessao, dados)
        headers = _como_admin(autenticar, dados)

        assert cliente.get("/api/v1/eventos/?skip=-5", headers=headers).status_code == 422
        assert cliente.get("/api/v1/eventos/?limit=0", headers=headers).status_code == 422
        assert cliente.get("/api/v1/eventos/?limit=99999", headers=headers).status_code == 422

    def test_setor_apagado_continua_legivel_na_listagem(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O nome do setor vem congelado da própria linha, não de um join — é o
        que faz a trilha continuar dizendo o que era aquele setor depois do
        hard delete do passo 3.
        """
        _semear(sessao, dados)
        sessao.query(Setor).filter(Setor.id == 2).delete()
        sessao.commit()

        eventos = cliente.get(
            "/api/v1/eventos/?alvo=setor", headers=_como_admin(autenticar, dados)
        ).json()

        assert [e["alvo_nome"] for e in eventos] == ["Financeiro"]

    def test_e_restrito_a_administrador(self, cliente, dados, sessao, autenticar):
        _semear(sessao, dados)

        resposta = cliente.get(
            "/api/v1/eventos/", headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico")
        )

        assert resposta.status_code == 403

    def test_exige_autenticacao(self, cliente, dados, sessao):
        _semear(sessao, dados)

        assert cliente.get("/api/v1/eventos/").status_code == 401


class TestLeituraEnxergaOQueAsRotasGravam:
    """
    As duas pontas ligadas: sem isto, os testes de gravação e os de leitura
    poderiam passar concordando cada um com uma tabela diferente.
    """

    def test_desativar_pela_api_aparece_na_consulta(self, cliente, dados, autenticar):
        headers = _como_admin(autenticar, dados)
        cliente.patch(f"/api/v1/usuarios/{dados['comum_id']}/desativar", headers=headers)

        eventos = cliente.get(
            f"/api/v1/usuarios/{dados['comum_id']}/eventos", headers=headers
        ).json()

        assert len(eventos) == 1
        assert eventos[0]["acao"] == "desativacao"
        assert eventos[0]["ator_nome"] == "admin.teste"
        assert eventos[0]["alvo_nome"] == "usuario.teste"
        assert eventos[0]["origem"] == "PATCH /api/v1/usuarios/{id}/desativar"

    def test_evento_de_setor_pela_api_aparece_na_listagem(self, cliente, dados, sessao, autenticar):
        headers = _como_admin(autenticar, dados)
        sessao.add(Setor(id=2, nome="Financeiro"))
        sessao.commit()

        cliente.patch("/api/v1/setores/2/desativar", headers=headers)

        eventos = cliente.get("/api/v1/eventos/?alvo=setor", headers=headers).json()

        assert len(eventos) == 1
        assert eventos[0]["alvo_tipo"] == "setor"
        assert eventos[0]["alvo_nome"] == "Financeiro"
        assert eventos[0]["ator_nome"] == "admin.teste"

    def test_filtro_de_hoje_encontra_o_que_acabou_de_acontecer(
        self, cliente, dados, autenticar
    ):
        """
        O caso real do filtro de período, com a data vinda do relógio em vez de
        plantada: quem abre a tela de auditoria filtra o dia corrente.
        """
        headers = _como_admin(autenticar, dados)
        cliente.patch(f"/api/v1/usuarios/{dados['comum_id']}/desativar", headers=headers)

        hoje = date.today()
        eventos = cliente.get(
            f"/api/v1/eventos/?de={hoje}&ate={hoje}", headers=headers
        ).json()

        assert len(eventos) == 1

        amanha = hoje + timedelta(days=1)
        assert cliente.get(f"/api/v1/eventos/?de={amanha}", headers=headers).json() == []
