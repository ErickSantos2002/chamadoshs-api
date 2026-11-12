"""
Notificação da Qualidade (API-15).

Fluxo próprio no n8n, separado do da TI. A API manda o que aconteceu e quem
deve ser avisado, por id; telefone, título e descrição nunca saem daqui. As
regras:

- chamado aberto sem responsável: `chamado_aberto` para os técnicos elegíveis
  da Qualidade, menos quem abriu;
- chamado aberto já com responsável (o corpo do cliente antigo):
  `responsavel_atribuido` só para ele;
- atribuição e redistribuição: `responsavel_atribuido` só para o novo
  responsável, e só se não foi ele quem fez — assumir não avisa ninguém;
- status, comentário, cancelamento e arquivamento não avisam;
- sem `WEBHOOK_QUALIDADE_URL` nada sai; com a URL e sem o token, também não;
- uma tentativa por evento, depois do commit: falha do n8n não desfaz nada e
  não é repetida;
- a TI não muda.

Nenhuma requisição real sai daqui: `requests.post` é substituído.
"""

import json
import logging
from types import SimpleNamespace

import pytest
import requests

import main
from app.api.endpoints import chamados as chamados_endpoint
from app.core.config import settings
from app.models import Chamado, Usuario
from app.services import webhook_service
from versao_do_cliente import com_versao_lida

API = "/api/v1/chamados"
DESCRICAO_OK = "O laudo do lote 42 chegou sem a assinatura do responsável"
URL = "https://exemplo.invalido/webhook/qualidade-segredo-da-url"
TOKEN = "token-de-teste-que-nao-pode-ir-para-o-log"
BRUNO = 41
BETO = 46


def _comum(autenticar, d):
    return autenticar(d["comum_id"], "usuario.teste", "Usuario")


def _bruno(autenticar, d):
    return autenticar(BRUNO, "bruno.qualidade", "Tecnico")


def _beto(autenticar, d):
    return autenticar(BETO, "beto.qualidade", "Tecnico")


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _corpo(d, **sobrescreve):
    base = {"setor_destino": "QUALIDADE", "descricao": DESCRICAO_OK, "solicitante_id": d["comum_id"]}
    base.update(sobrescreve)
    return base


@pytest.fixture
def ligado(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_URL", URL)
    monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_TOKEN", TOKEN)


@pytest.fixture
def posts(monkeypatch):
    """Registra os POSTs ao n8n em vez de enviá-los. `posts.resposta` troca a resposta."""

    class Posts(list):
        resposta = SimpleNamespace(status_code=200)

    chamadas = Posts()

    def falso_post(url, json=None, timeout=None, headers=None):
        chamadas.append({"url": url, "json": json, "timeout": timeout, "headers": headers})
        if isinstance(chamadas.resposta, Exception):
            raise chamadas.resposta
        return chamadas.resposta

    monkeypatch.setattr(webhook_service.requests, "post", falso_post)
    return chamadas


@pytest.fixture
def ti(monkeypatch):
    """Registra as chamadas ao webhook da TI em vez de enviá-las."""
    chamadas = []
    monkeypatch.setattr(chamados_endpoint, "enviar_webhook_tecnico", lambda **kwargs: chamadas.append(kwargs))
    return chamadas


@pytest.fixture
def equipe(qualidade, sessao):
    """A Qualidade com dois Técnicos elegíveis: o bruno e o beto."""
    sessao.add(Usuario(id=BETO, nome="beto.qualidade", role_id=2, setor_id=2, ativo=True))
    sessao.commit()
    return qualidade


def _abrir(cliente, d, headers, **sobrescreve):
    resposta = cliente.post(f"{API}/", json=_corpo(d, **sobrescreve), headers=headers)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


@pytest.fixture
def na_fila(equipe, cliente, autenticar, ligado, posts, ti):
    """Um chamado sem responsável, com o aviso da abertura já descartado."""
    criado = _abrir(cliente, equipe, _comum(autenticar, equipe))
    posts.clear()
    return {**equipe, "fila_id": criado["id"], "protocolo": criado["protocolo"]}


def _put(cliente, chamado_id, corpo, headers):
    corpo = com_versao_lida(cliente, chamado_id, corpo, headers)
    return cliente.put(f"{API}/{chamado_id}", json=corpo, headers=headers)


def _atribuir(cliente, chamado_id, tecnico_id, headers):
    resposta = _put(cliente, chamado_id, {"tecnico_responsavel_id": tecnico_id}, headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


class TestAbertura:
    def test_sem_responsavel_avisa_os_tecnicos_elegiveis(self, cliente, equipe, autenticar, ligado, posts, ti):
        criado = _abrir(cliente, equipe, _comum(autenticar, equipe))

        (post,) = posts
        assert post["url"] == URL
        assert post["headers"] == {"X-Webhook-Token": TOKEN}
        assert post["timeout"] == settings.WEBHOOK_TIMEOUT_SEGUNDOS
        assert post["json"] == {
            "evento": "chamado_aberto",
            "id_evento": f"{criado['id']}:{criado['versao']}:chamado_aberto",
            "setor": "QUALIDADE",
            "chamado": {"id": criado["id"], "protocolo": criado["protocolo"], "versao": criado["versao"]},
            "responsavel_id": None,
            "responsavel_anterior_id": None,
            "autor_id": equipe["comum_id"],
            "destinatarios_ids": [BRUNO, BETO],
        }
        assert ti == []

    def test_payload_nao_leva_titulo_descricao_nome_nem_telefone(self, cliente, equipe, autenticar, ligado, posts):
        criado = _abrir(cliente, equipe, _comum(autenticar, equipe))

        texto = json.dumps(posts[0]["json"], ensure_ascii=False)
        assert DESCRICAO_OK not in texto
        assert criado["titulo"] not in texto
        for proibido in ("titulo", "descricao", "telefone", "nome", "solicitante", "bruno", "beto", "usuario.teste"):
            assert proibido not in texto

    def test_so_tecnico_elegivel_da_qualidade_e_destinatario(self, cliente, equipe, autenticar, ligado, posts):
        # Fora: técnico e admin da TI, comum lotada na Qualidade, inativa,
        # conta de serviço e administrador lotado na Qualidade.
        _abrir(cliente, equipe, _comum(autenticar, equipe))

        destinatarios = posts[0]["json"]["destinatarios_ids"]
        assert destinatarios == [BRUNO, BETO]
        for chave in ("tecnico_id", "admin_id", "atendente_id", "inativo_id", "admin_da_qualidade_id", "comum_id"):
            assert equipe[chave] not in destinatarios

    def test_tecnico_da_qualidade_que_abre_nao_e_avisado(self, cliente, equipe, autenticar, ligado, posts):
        _abrir(cliente, equipe, _bruno(autenticar, equipe))

        (post,) = posts
        assert post["json"]["autor_id"] == BRUNO
        assert post["json"]["destinatarios_ids"] == [BETO]

    def test_unico_tecnico_abrindo_nao_dispara_nada(self, cliente, qualidade, autenticar, ligado, posts):
        _abrir(cliente, qualidade, _bruno(autenticar, qualidade))

        assert posts == []

    def test_autor_e_quem_abriu_e_nao_o_solicitante_informado(self, cliente, equipe, autenticar, ligado, posts):
        # O administrador abre em nome de outro: o autor da ação é ele.
        _abrir(cliente, equipe, _admin(autenticar, equipe), solicitante_id=BRUNO)

        assert posts[0]["json"]["autor_id"] == equipe["admin_id"]
        assert posts[0]["json"]["destinatarios_ids"] == [BRUNO, BETO]

    def test_com_responsavel_avisa_so_ele_como_atribuicao(self, cliente, equipe, autenticar, ligado, posts):
        criado = _abrir(cliente, equipe, _comum(autenticar, equipe), tecnico_responsavel_id=BRUNO)

        (post,) = posts
        assert post["json"]["evento"] == "responsavel_atribuido"
        assert post["json"]["id_evento"] == f"{criado['id']}:{criado['versao']}:responsavel_atribuido"
        assert post["json"]["responsavel_id"] == BRUNO
        assert post["json"]["responsavel_anterior_id"] is None
        assert post["json"]["destinatarios_ids"] == [BRUNO]

    def test_com_responsavel_igual_ao_autor_nao_dispara(self, cliente, equipe, autenticar, ligado, posts):
        _abrir(cliente, equipe, _bruno(autenticar, equipe), tecnico_responsavel_id=BRUNO)

        assert posts == []

    def test_sem_tecnico_elegivel_e_409_e_nada_sai(self, cliente, qualidade, sessao, autenticar, ligado, posts):
        sessao.get(Usuario, BRUNO).ativo = False
        sessao.commit()

        resposta = cliente.post(f"{API}/", json=_corpo(qualidade), headers=_comum(autenticar, qualidade))

        assert resposta.status_code == 409
        assert posts == []

    def test_abertura_recusada_nao_dispara(self, cliente, equipe, autenticar, ligado, posts):
        resposta = cliente.post(
            f"{API}/", json=_corpo(equipe, descricao="curta"), headers=_comum(autenticar, equipe)
        )

        assert resposta.status_code == 422
        assert posts == []


class TestConfiguracao:
    def test_url_vazia_nao_envia_nem_consulta_a_equipe(self, cliente, equipe, autenticar, posts, monkeypatch):
        monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_URL", "")
        monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_TOKEN", TOKEN)
        montagens = []
        monkeypatch.setattr(
            chamados_endpoint, "montar_evento_qualidade", lambda **kwargs: montagens.append(kwargs)
        )

        criado = _abrir(cliente, equipe, _comum(autenticar, equipe))
        _atribuir(cliente, criado["id"], BETO, _bruno(autenticar, equipe))

        assert posts == []
        assert montagens == []

    def test_padrao_e_desligado(self):
        from app.core.config import Settings

        campos = Settings.model_fields
        assert campos["WEBHOOK_QUALIDADE_URL"].default == ""
        assert campos["WEBHOOK_QUALIDADE_TOKEN"].default == ""

    def test_url_sem_token_nao_envia_e_registra_o_motivo(self, cliente, equipe, autenticar, posts, monkeypatch, caplog):
        monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_URL", URL)
        monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_TOKEN", "")

        with caplog.at_level(logging.DEBUG):
            _abrir(cliente, equipe, _comum(autenticar, equipe))

        assert posts == []
        assert "sem WEBHOOK_QUALIDADE_TOKEN" in caplog.text
        assert URL not in caplog.text

    def test_header_configuravel(self, cliente, equipe, autenticar, ligado, posts, monkeypatch):
        monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_HEADER", "X-Outro")

        _abrir(cliente, equipe, _comum(autenticar, equipe))

        assert posts[0]["headers"] == {"X-Outro": TOKEN}

    def test_nao_usa_a_configuracao_da_ti(self, cliente, equipe, autenticar, ligado, posts, monkeypatch):
        monkeypatch.setattr(settings, "WEBHOOK_TECNICO_URL", "https://exemplo.invalido/webhook/ti")
        monkeypatch.setattr(settings, "WEBHOOK_TECNICO_TOKEN", "token-da-ti")

        _abrir(cliente, equipe, _comum(autenticar, equipe))

        assert [p["url"] for p in posts] == [URL]
        assert "token-da-ti" not in json.dumps(posts[0]["headers"])


class TestAtribuicao:
    def test_assumir_nao_avisa_ninguem(self, cliente, na_fila, sessao, autenticar, posts):
        d = na_fila
        _atribuir(cliente, d["fila_id"], BRUNO, _bruno(autenticar, d))

        sessao.expire_all()
        assert sessao.get(Chamado, d["fila_id"]).tecnico_responsavel_id == BRUNO
        assert posts == []

    @pytest.mark.parametrize("quem,autor", [(_admin, 10), (_bruno, BRUNO)], ids=["administrador", "colega"])
    def test_atribuicao_por_outra_pessoa_avisa_o_novo_responsavel(
        self, cliente, na_fila, autenticar, posts, ti, quem, autor
    ):
        d = na_fila
        atualizado = _atribuir(cliente, d["fila_id"], BETO, quem(autenticar, d))

        (post,) = posts
        assert post["json"] == {
            "evento": "responsavel_atribuido",
            "id_evento": f"{d['fila_id']}:{atualizado['versao']}:responsavel_atribuido",
            "setor": "QUALIDADE",
            "chamado": {"id": d["fila_id"], "protocolo": d["protocolo"], "versao": atualizado["versao"]},
            "responsavel_id": BETO,
            "responsavel_anterior_id": None,
            "autor_id": autor,
            "destinatarios_ids": [BETO],
        }
        assert ti == []

    def test_redistribuicao_avisa_so_o_novo_responsavel(self, cliente, na_fila, autenticar, posts):
        d = na_fila
        _atribuir(cliente, d["fila_id"], BRUNO, _bruno(autenticar, d))
        _atribuir(cliente, d["fila_id"], BETO, _admin(autenticar, d))

        (post,) = posts
        assert post["json"]["responsavel_id"] == BETO
        assert post["json"]["responsavel_anterior_id"] == BRUNO
        assert post["json"]["destinatarios_ids"] == [BETO]

    def test_redistribuicao_para_si_mesmo_nao_avisa(self, cliente, na_fila, autenticar, posts):
        d = na_fila
        _atribuir(cliente, d["fila_id"], BRUNO, _bruno(autenticar, d))
        _atribuir(cliente, d["fila_id"], BETO, _beto(autenticar, d))

        assert posts == []

    def test_responsavel_que_passa_o_chamado_avisa_o_colega(self, cliente, na_fila, autenticar, posts):
        d = na_fila
        _atribuir(cliente, d["fila_id"], BRUNO, _bruno(autenticar, d))
        _atribuir(cliente, d["fila_id"], BETO, _bruno(autenticar, d))

        (post,) = posts
        assert post["json"]["autor_id"] == BRUNO
        assert post["json"]["destinatarios_ids"] == [BETO]

    def test_atribuir_e_iniciar_no_mesmo_put_e_um_aviso_so(self, cliente, na_fila, autenticar, posts):
        d = na_fila
        resposta = _put(
            cliente,
            d["fila_id"],
            {"tecnico_responsavel_id": BETO, "status": "Em Andamento"},
            _bruno(autenticar, d),
        )

        assert resposta.status_code == 200, resposta.text
        assert [p["json"]["evento"] for p in posts] == ["responsavel_atribuido"]

    def test_reenviar_o_mesmo_responsavel_nao_avisa(self, cliente, na_fila, autenticar, posts):
        d = na_fila
        _atribuir(cliente, d["fila_id"], BETO, _admin(autenticar, d))
        posts.clear()

        resposta = _put(
            cliente, d["fila_id"], {"tecnico_responsavel_id": BETO, "prioridade": "Alta"}, _admin(autenticar, d)
        )

        assert resposta.status_code == 200
        assert posts == []

    def test_atribuicao_recusada_nao_avisa(self, cliente, na_fila, autenticar, posts):
        d = na_fila
        h = _admin(autenticar, d)
        inelegivel = _put(cliente, d["fila_id"], {"tecnico_responsavel_id": d["tecnico_id"]}, h)
        versao_velha = cliente.put(
            f"{API}/{d['fila_id']}", json={"tecnico_responsavel_id": BETO, "versao_esperada": 999}, headers=h
        )
        sem_versao = cliente.put(f"{API}/{d['fila_id']}", json={"tecnico_responsavel_id": BETO}, headers=h)

        assert (inelegivel.status_code, versao_velha.status_code, sem_versao.status_code) == (400, 409, 428)
        assert posts == []


class TestOutrosEventosNaoAvisam:
    def test_status_comentario_cancelamento_e_arquivamento(self, cliente, na_fila, autenticar, posts):
        d = na_fila
        h = _bruno(autenticar, d)
        _atribuir(cliente, d["fila_id"], BRUNO, h)
        url = f"{API}/{d['fila_id']}"

        def versao():
            return cliente.get(url, headers=h).json()["versao"]

        respostas = [
            cliente.patch(f"{url}/atendimento", json={"status": "Em Andamento", "versao_esperada": versao()}, headers=h),
            _put(cliente, d["fila_id"], {"status": "Aguardando"}, h),
            _put(cliente, d["fila_id"], {"prioridade": "Crítica"}, h),
            cliente.post(
                "/api/v1/comentarios/",
                json={"chamado_id": d["fila_id"], "comentario": "Comentário de teste do fluxo"},
                headers=h,
            ),
            cliente.patch(f"{url}/arquivar", json={"versao_esperada": versao()}, headers=h),
        ]
        respostas.append(cliente.patch(f"{url}/desarquivar", json={"versao_esperada": versao()}, headers=h))
        respostas.append(cliente.patch(f"{url}/cancelar", json={"versao_esperada": versao()}, headers=h))

        assert [r.status_code for r in respostas] == [200, 200, 200, 201, 200, 200, 200], [r.text for r in respostas]
        assert posts == []


class TestFalhaDoN8n:
    @pytest.mark.parametrize(
        "resposta",
        [
            requests.exceptions.Timeout("demorou"),
            requests.exceptions.ConnectionError("fora do ar"),
            RuntimeError("qualquer coisa"),
            SimpleNamespace(status_code=500, text="<html>erro</html>"),
            SimpleNamespace(status_code=401),
            SimpleNamespace(status_code=404),
            SimpleNamespace(status_code=200, text="isto não é json"),
        ],
        ids=["timeout", "sem-conexao", "excecao", "500-com-html", "401", "404", "200-corpo-invalido"],
    )
    def test_nao_desfaz_a_abertura_nem_a_atribuicao_e_nao_repete(
        self, cliente, equipe, sessao, autenticar, ligado, posts, resposta
    ):
        posts.resposta = resposta

        criado = _abrir(cliente, equipe, _comum(autenticar, equipe))
        atribuido = _atribuir(cliente, criado["id"], BETO, _bruno(autenticar, equipe))

        sessao.expire_all()
        assert sessao.get(Chamado, criado["id"]).tecnico_responsavel_id == BETO
        assert atribuido["tecnico_responsavel_id"] == BETO
        # Uma tentativa por evento: repetir poderia duplicar a mensagem.
        assert [p["json"]["evento"] for p in posts] == ["chamado_aberto", "responsavel_atribuido"]

    def test_falha_ao_montar_o_evento_nao_quebra_a_resposta(self, cliente, equipe, autenticar, ligado, posts, monkeypatch):
        def quebra(**kwargs):
            raise RuntimeError("defeito na montagem")

        monkeypatch.setattr(chamados_endpoint, "montar_evento_qualidade", quebra)

        criado = _abrir(cliente, equipe, _comum(autenticar, equipe))
        _atribuir(cliente, criado["id"], BETO, _bruno(autenticar, equipe))

        assert posts == []

    def test_log_nao_registra_url_nem_token(self, cliente, equipe, autenticar, ligado, posts, caplog):
        posts.resposta = SimpleNamespace(status_code=401)

        with caplog.at_level(logging.DEBUG):
            criado = _abrir(cliente, equipe, _comum(autenticar, equipe))
            posts.resposta = requests.exceptions.ConnectionError(f"falha em {URL} com {TOKEN}")
            _atribuir(cliente, criado["id"], BETO, _bruno(autenticar, equipe))

        assert "WEBHOOK_QUALIDADE_TOKEN" in caplog.text
        assert URL not in caplog.text
        assert TOKEN not in caplog.text


class TestSemDuplicidadeNaApi:
    def test_um_envio_por_escrita_e_ids_distintos(self, cliente, equipe, autenticar, ligado, posts):
        criado = _abrir(cliente, equipe, _comum(autenticar, equipe))
        _atribuir(cliente, criado["id"], BETO, _bruno(autenticar, equipe))
        _atribuir(cliente, criado["id"], BRUNO, _beto(autenticar, equipe))

        eventos = [p["json"]["evento"] for p in posts]
        assert eventos == ["chamado_aberto", "responsavel_atribuido", "responsavel_atribuido"]
        # Leituras não reenviam nada.
        cliente.get(f"{API}/{criado['id']}", headers=_bruno(autenticar, equipe))
        cliente.get(f"{API}/", headers=_bruno(autenticar, equipe))
        assert len(posts) == 3

    def test_destinatario_nao_se_repete_no_mesmo_evento(self):
        evento = webhook_service.montar_evento_qualidade(
            evento="chamado_aberto",
            chamado_id=7,
            protocolo="CH-7",
            versao=1,
            autor_id=1,
            destinatarios_ids=[5, 20, 5, None, 1, 20],
        )

        assert evento["destinatarios_ids"] == [5, 20]

    def test_id_do_evento_e_estavel_e_muda_com_a_versao(self):
        def monta(versao):
            return webhook_service.montar_evento_qualidade(
                evento="responsavel_atribuido",
                chamado_id=7,
                protocolo="CH-7",
                versao=versao,
                autor_id=1,
                destinatarios_ids=[5],
                responsavel_id=5,
            )["id_evento"]

        assert monta(2) == monta(2) == "7:2:responsavel_atribuido"
        assert monta(3) != monta(2)

    def test_sem_destinatario_nao_ha_evento(self):
        assert (
            webhook_service.montar_evento_qualidade(
                evento="responsavel_atribuido",
                chamado_id=7,
                protocolo="CH-7",
                versao=2,
                autor_id=5,
                destinatarios_ids=[5],
                responsavel_id=5,
            )
            is None
        )


class TestTINaoMuda:
    def test_abertura_da_ti_dispara_so_o_webhook_da_ti(self, cliente, equipe, autenticar, ligado, posts, ti):
        resposta = cliente.post(
            f"{API}/",
            json={
                "setor_destino": "TI",
                "solicitante_id": equipe["comum_id"],
                "titulo": "Impressora da recepção não imprime",
                "descricao": "A impressora da recepção parou de imprimir hoje cedo",
                "categoria_id": 1,
                "prioridade": "Média",
            },
            headers=_comum(autenticar, equipe),
        )

        assert resposta.status_code == 201, resposta.text
        assert len(ti) == 1
        chamada = dict(ti[0])
        chamada.pop("db")
        assert chamada == {
            "protocolo": resposta.json()["protocolo"],
            "titulo": "Impressora da recepção não imprime",
            "tecnico_id": None,
            "acao": "criado",
        }
        assert posts == []

    def test_atribuicao_da_ti_dispara_so_o_webhook_da_ti(self, cliente, equipe, autenticar, ligado, posts, ti, monkeypatch):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", "1")

        resposta = cliente.put(
            f"{API}/{equipe['chamado_id']}",
            json={"tecnico_responsavel_id": equipe["tecnico_id"]},
            headers=_admin(autenticar, equipe),
        )

        assert resposta.status_code == 200, resposta.text
        assert [(c["tecnico_id"], c["acao"], c["protocolo"]) for c in ti] == [
            (equipe["tecnico_id"], "atribuido", "CH-TESTE-100")
        ]
        assert posts == []

    def test_envio_da_ti_segue_com_o_token_opcional(self, posts, monkeypatch):
        # O token obrigatório é só do fluxo novo: o da TI segue enviando sem ele.
        monkeypatch.setattr(settings, "WEBHOOK_TECNICO_URL", "https://exemplo.invalido/webhook/ti")
        monkeypatch.setattr(settings, "WEBHOOK_TECNICO_TOKEN", "")

        webhook_service.enviar_webhook_tecnico(None, "CH-1", "Título")

        (post,) = posts
        assert post["headers"] == {}
        assert post["json"] == {"protocolo": "CH-1", "titulo": "Título", "tecnico": "Sem atribuição", "acao": "criado"}


class TestEntregaHttpLocal:
    """Sem substituir `requests`: um servidor em 127.0.0.1 recebe o POST de verdade."""

    def test_o_post_chega_com_o_token_e_o_corpo(self, cliente, equipe, autenticar, monkeypatch):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        recebidos = []

        class Captura(BaseHTTPRequestHandler):
            def do_POST(self):
                corpo = self.rfile.read(int(self.headers["Content-Length"]))
                recebidos.append(
                    {
                        "caminho": self.path,
                        "token": self.headers.get("X-Webhook-Token"),
                        "tipo": self.headers.get("Content-Type"),
                        "json": json.loads(corpo),
                    }
                )
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        servidor = HTTPServer(("127.0.0.1", 0), Captura)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            monkeypatch.setattr(
                settings, "WEBHOOK_QUALIDADE_URL", f"http://127.0.0.1:{servidor.server_port}/webhook/local"
            )
            monkeypatch.setattr(settings, "WEBHOOK_QUALIDADE_TOKEN", TOKEN)

            criado = _abrir(cliente, equipe, _comum(autenticar, equipe))
        finally:
            servidor.shutdown()
            servidor.server_close()

        (recebido,) = recebidos
        assert recebido["caminho"] == "/webhook/local"
        assert recebido["token"] == TOKEN
        assert recebido["tipo"] == "application/json"
        assert recebido["json"]["id_evento"] == f"{criado['id']}:{criado['versao']}:chamado_aberto"
        assert recebido["json"]["destinatarios_ids"] == [BRUNO, BETO]
