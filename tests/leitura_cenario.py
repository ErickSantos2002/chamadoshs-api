"""
Cenário comum dos testes de leitura por chamado (API-5).

Acrescenta ao `chamado_qualidade` do conftest as contas e os chamados que a
matriz D1–D5 precisa, cada um com um comentário público, um interno e uma
linha de histórico — para que toda rota de leitura tenha o que devolver ou
esconder. `LEITURA_ESPERADA` é a matriz aprovada escrita à mão, e não
derivada do código: é contra ela que o predicado, o escopo SQL e as rotas
são conferidos.

Ids fixos e altos, como no conftest, para não colidir com o que as rotas
gravarem pela sequência no PostgreSQL.
"""

import pytest

from app.models import Chamado, Setor, Usuario
from app.models.comentario import ComentarioChamado
from app.models.historico import HistoricoChamado

SETOR_COMERCIAL = 4

# Contas novas, além das do conftest (admin 10, técnico 20, comum 30,
# atendente 40, técnico da Qualidade 41, inativo 42, conta de serviço 43,
# sem setor 44, administrador da Qualidade 45).
INTRUSO = 50
OUTRO_SOLICITANTE = 51
COLEGA_DO_SOLICITANTE = 52  # mesmo setor (TI, 1) do solicitante 30
EX_RESPONSAVEL = 53  # da Qualidade, já não atende o 103
TECNICO_SEM_SETOR = 54

CHAMADOS = {
    "ti_do_solicitante": 100,  # conftest: TI, solicitante 30
    "q_atribuido": 101,  # conftest: Qualidade, solicitante 30, responsável 40
    "ti_arquivado": 102,
    "q_reatribuido": 103,
    "ti_cancelado": 104,
    "ti_com_tecnico_da_q": 105,
    "ti_sem_responsavel": 106,
}

TODOS = set(CHAMADOS)

# Quem lê o quê, pela matriz aprovada.
LEITURA_ESPERADA = {
    "admin": TODOS,
    "admin_da_qualidade": TODOS,  # D: administrador lê todos, de qualquer setor
    "tecnico_ti": TODOS,  # D1
    # D2: Qualidade inteira; da TI só o que ele atende.
    "tecnico_qualidade": {"q_atribuido", "q_reatribuido", "ti_com_tecnico_da_q"},
    "solicitante": {"ti_do_solicitante", "q_atribuido"},
    "atendente": {"q_atribuido", "q_reatribuido"},
    "ex_responsavel": set(),  # D4
    "outro_solicitante": {
        "ti_arquivado",
        "q_reatribuido",
        "ti_cancelado",
        "ti_com_tecnico_da_q",
        "ti_sem_responsavel",
    },
    "intruso": set(),
    "colega_do_solicitante": set(),  # D5
    "tecnico_sem_setor": set(),  # sem setor, sem leitura por perfil
    "usuario_sem_setor": set(),
    "conta_de_servico": set(),
}

# Quem vê comentário interno nos chamados que lê: a regra de sempre (perfil
# de equipe), que a API-5 não muda.
EQUIPE = {"admin", "admin_da_qualidade", "tecnico_ti", "tecnico_qualidade", "tecnico_sem_setor"}

ROLE_DE = {
    "admin": "Administrador",
    "admin_da_qualidade": "Administrador",
    "tecnico_ti": "Tecnico",
    "tecnico_qualidade": "Tecnico",
    "tecnico_sem_setor": "Tecnico",
}


def comentario_publico(chamado_id: int) -> int:
    return chamado_id * 10


def comentario_interno(chamado_id: int) -> int:
    return chamado_id * 10 + 1


def historico_de(chamado_id: int) -> int:
    return chamado_id * 10


@pytest.fixture
def cenario_de_leitura(chamado_qualidade, sessao):
    d = chamado_qualidade
    sessao.add(Setor(id=SETOR_COMERCIAL, nome="Comercial", ativo=True))
    sessao.flush()
    sessao.add_all([
        Usuario(id=INTRUSO, nome="intruso.comercial", role_id=3, setor_id=SETOR_COMERCIAL, ativo=True),
        Usuario(id=OUTRO_SOLICITANTE, nome="outro.solicitante", role_id=3, setor_id=SETOR_COMERCIAL, ativo=True),
        Usuario(id=COLEGA_DO_SOLICITANTE, nome="colega.ti", role_id=3, setor_id=1, ativo=True),
        Usuario(id=EX_RESPONSAVEL, nome="eva.qualidade", role_id=3, setor_id=d["setor_qualidade_id"], ativo=True),
        Usuario(id=TECNICO_SEM_SETOR, nome="tecnico.sem.setor", role_id=2, setor_id=None, ativo=True),
    ])
    sessao.flush()

    def _chamado(nome, setor, solicitante, responsavel=None, **extra):
        cid = CHAMADOS[nome]
        return Chamado(
            id=cid,
            protocolo=f"CH-TESTE-{cid}",
            solicitante_id=solicitante,
            categoria_id=1 if setor == "TI" else None,
            titulo=f"Chamado {nome}",
            descricao=f"Descrição do chamado {nome}",
            status="Aberto",
            prioridade="Média",
            setor_destino=setor,
            tecnico_responsavel_id=responsavel,
            **extra,
        )

    sessao.add_all([
        _chamado("ti_arquivado", "TI", OUTRO_SOLICITANTE, arquivado=True),
        _chamado("q_reatribuido", "QUALIDADE", OUTRO_SOLICITANTE, d["atendente_id"]),
        _chamado("ti_cancelado", "TI", OUTRO_SOLICITANTE, cancelado=True),
        _chamado("ti_com_tecnico_da_q", "TI", OUTRO_SOLICITANTE, d["tecnico_da_qualidade_id"]),
        _chamado("ti_sem_responsavel", "TI", OUTRO_SOLICITANTE),
    ])
    sessao.flush()

    for cid in CHAMADOS.values():
        sessao.add_all([
            ComentarioChamado(
                id=comentario_publico(cid), chamado_id=cid, usuario_id=d["admin_id"],
                comentario=f"Comentário público do {cid}", is_interno=False,
            ),
            ComentarioChamado(
                id=comentario_interno(cid), chamado_id=cid, usuario_id=d["tecnico_id"],
                comentario=f"Comentário interno do {cid}", is_interno=True,
            ),
            HistoricoChamado(
                id=historico_de(cid), chamado_id=cid, usuario_id=d["admin_id"],
                acao="Criação", descricao=f"Histórico do {cid}",
            ),
        ])
    sessao.commit()

    return {
        **d,
        "admin": d["admin_id"],
        "admin_da_qualidade": d["admin_da_qualidade_id"],
        "tecnico_ti": d["tecnico_id"],
        "tecnico_qualidade": d["tecnico_da_qualidade_id"],
        "solicitante": d["comum_id"],
        "atendente": d["atendente_id"],
        "ex_responsavel": EX_RESPONSAVEL,
        "outro_solicitante": OUTRO_SOLICITANTE,
        "intruso": INTRUSO,
        "colega_do_solicitante": COLEGA_DO_SOLICITANTE,
        "tecnico_sem_setor": TECNICO_SEM_SETOR,
        "usuario_sem_setor": d["sem_setor_id"],
        "conta_de_servico": d["conta_de_servico_id"],
    }
