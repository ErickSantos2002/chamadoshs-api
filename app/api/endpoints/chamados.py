import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import Any, List, Optional
from datetime import datetime

from app.api.deps import (
    get_current_user,
    get_db,
    is_admin_humano,
    require_admin,
    require_equipe_ti,
    require_staff,
)
from app.models.chamado import Chamado
from app.models.usuario import Usuario
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.schemas.chamado import (
    AtendenteQualidade,
    ChamadoAtendimento,
    ChamadoAvaliacao,
    ChamadoCreate,
    ChamadoCreateQualidade,
    ChamadoMarca,
    ChamadoResponse,
    ChamadoUpdate,
    ResponsavelTI,
    SetorDestinoEnum,
    StatusEnum,
)
from app.services.chamado_service import (
    adicionar_historico,
    calcular_tempo_resolucao,
    derivar_titulo,
    gerar_protocolo,
    registrar_historico,
    transicao_permitida,
)
from app.services.leitura_service import (
    ChamadoNaoEncontrado,
    buscar_chamado_alteravel,
    buscar_chamado_legivel,
    escopo_de_leitura,
    pode_alterar_como_equipe,
    pode_ler_chamado,
)
from app.services.qualidade_service import (
    AtendenteInelegivel,
    AtendenteNaoEncontrado,
    ChamadoForaDaQualidade,
    NaoEhResponsavel,
    QualidadeIndisponivel,
    buscar_atendente,
    listar_atendentes,
    verificar_atendimento,
)
from app.services.responsavel_ti_service import CONTA_DE_SERVICO, listar_responsaveis, motivo_de_recusa
from app.services.sla_service import calcular_sla
from app.services.versao_service import conferir_versao
from app.services.webhook_service import enviar_webhook_tecnico
from app.utils.timezone import agora_brasilia

router = APIRouter()

logger = logging.getLogger(__name__)

# Parâmetro `usuario_id` depreciado.
#
# Estes endpoints recebiam o autor da ação como query parameter, ou seja, o
# histórico registrava quem o chamador dissesse ser. O autor agora vem do
# token. O parâmetro continua sendo aceito e ignorado apenas para o frontend
# atual não quebrar durante a janela entre os dois deploys (repositórios
# separados). Remover assim que o aviso abaixo parar de aparecer nos logs.
USUARIO_ID_DEPRECIADO = Query(
    None,
    deprecated=True,
    include_in_schema=False,
    description="DEPRECADO: ignorado. O autor da ação vem do token JWT.",
)


def _avisar_usuario_id_depreciado(endpoint: str, usuario_id: Optional[int], atual: Usuario) -> None:
    # A condição é apenas `is not None`, de propósito.
    #
    # Antes havia também `usuario_id != atual.id`, e isso tornava o aviso
    # inútil como sinal de desligamento: o caso normal — a pessoa logada
    # agindo em nome de si mesma, mandando o próprio id — passava silencioso.
    # O log podia estar zerado com o frontend enviando o parâmetro em 100% das
    # chamadas, e remover o suporte no backend quebraria produção.
    #
    # Agora conta o que interessa: quantas chamadas ainda mandam o parâmetro.
    # O volume é alto enquanto o frontend não for atualizado — é o baseline
    # esperado, não um defeito.
    if usuario_id is not None:
        logger.warning(
            "param usuario_id depreciado em %s: recebido %s, usando %s (do token)",
            endpoint,
            usuario_id,
            atual.id,
        )


def _validar_tecnico_responsavel(db: Session, chamado: Chamado, chamado_data: ChamadoUpdate) -> None:
    """
    Responsável de chamado da TI: uma pessoa, e da equipe da TI.

    O seletor do frontend já filtra contas de serviço, mas filtro de tela é
    convenção, não garantia: `tecnico_responsavel_id` é FK crua e a API aceita
    qualquer id que exista na tabela.

    Só valida quando o campo vem na requisição — `model_fields_set`, não o
    valor. Validar o técnico atual em todo PUT tornaria um chamado ineditável
    caso a pessoa atribuída virasse conta de serviço depois: mudar o status ou
    escrever a solução passaria a falhar por causa de um campo que a
    requisição nem toca.

    `None` explícito é desatribuição, e continua permitido.

    Equipe da TI (API-6, D9): só na MUDANÇA de responsável, pelo mesmo motivo
    de `_validar_responsavel_da_qualidade` — a edição completa do frontend
    reenvia o responsável atual, e o chamado antigo com responsável de fora
    da equipe continua editável. Ele não é trocado sozinho: fica com quem
    está até alguém da equipe o reatribuir. A regra é da conta atribuída,
    independente de quem atribui, e mora em `responsavel_ti_service`.
    """
    if "tecnico_responsavel_id" not in chamado_data.model_fields_set:
        return

    tecnico_id = chamado_data.tecnico_responsavel_id
    if tecnico_id is None:
        return

    tecnico = db.query(Usuario).filter(Usuario.id == tecnico_id).first()
    if tecnico is None:
        # Sem esta checagem o id inexistente só estouraria como violação de
        # chave estrangeira no commit, virando 500 em vez de erro do cliente.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Técnico responsável não encontrado",
        )

    # Conta de serviço é recusada também quando é o responsável atual, como
    # sempre foi: só o resto da regra espera a mudança.
    if tecnico.conta_de_servico:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CONTA_DE_SERVICO)

    if tecnico_id != chamado.tecnico_responsavel_id:
        motivo = motivo_de_recusa(tecnico)
        if motivo is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=motivo)


def _validar_responsavel_da_qualidade(db: Session, chamado: Chamado, chamado_data: ChamadoUpdate) -> None:
    """
    Reatribuição de chamado da Qualidade: só entre atendentes elegíveis.

    Valida a MUDANÇA, não o campo. A edição completa do frontend reenvia o
    responsável atual em todo salvamento, e revalidá-lo deixaria ineditável o
    chamado cujo responsável saiu da Qualidade depois de atribuído — o mesmo
    motivo de `_validar_tecnico_responsavel` olhar só o que veio na requisição.

    Desatribuir é recusado: chamado da Qualidade nasce com responsável, e sem
    ele ninguém poderia atendê-lo pela rota de atendimento.
    """
    if "tecnico_responsavel_id" not in chamado_data.model_fields_set:
        return

    novo_id = chamado_data.tecnico_responsavel_id
    if novo_id == chamado.tecnico_responsavel_id:
        return

    if novo_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chamado da Qualidade precisa de responsável",
        )

    try:
        buscar_atendente(db, novo_id)
    except QualidadeIndisponivel:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=QUALIDADE_INDISPONIVEL)
    except AtendenteNaoEncontrado:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Atendente não encontrado")
    except AtendenteInelegivel:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Atendente não é elegível para a Qualidade",
        )


def _anexar_sla(chamados: List[Chamado], db: Session) -> List[Chamado]:
    """
    Calcula e anexa o bloco `sla` a cada chamado.

    Duas queries no total (configs + históricos de todos os chamados de uma vez),
    para não cair em N+1 na listagem.

    Resiliente à ausência da tabela `sla_configs` (ex.: migração ainda não
    rodou em produção): se a query falhar, trata como "sem configs" em vez de
    derrubar o endpoint inteiro — o chamado é devolvido normalmente, só sem
    bloco de SLA (ver `calcular_sla`: sem config, o chamado não tem SLA e o
    campo vai `None`, nunca um falso "No prazo").
    """
    if not chamados:
        return chamados

    try:
        configs = {c.prioridade: c for c in db.query(SLAConfig).all()}
    except SQLAlchemyError:
        db.rollback()  # sem isso, a próxima query nesta sessão estoura PendingRollbackError
        configs = {}

    ids = [c.id for c in chamados]
    historicos_por_chamado: dict[int, list] = {i: [] for i in ids}
    historicos = (
        db.query(HistoricoChamado)
        .filter(HistoricoChamado.chamado_id.in_(ids))
        .all()
    )
    for h in historicos:
        historicos_por_chamado[h.chamado_id].append(h)

    for chamado in chamados:
        cfg = configs.get(chamado.prioridade)
        chamado.sla = (
            calcular_sla(
                chamado=chamado,
                historicos=historicos_por_chamado.get(chamado.id, []),
                config=cfg,
            )
            if cfg
            else None
        )

    return chamados


@router.get("/", response_model=List[ChamadoResponse])
def listar_chamados(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: str = None,
    solicitante_id: int = None,
    tecnico_id: int = None,
    # Tipado pelo enum, e não `str` como `status`: valor fora da lista vira
    # 422, em vez de uma lista vazia que se leria como "não há chamados".
    setor_destino: Optional[SetorDestinoEnum] = None,
    incluir_cancelados: bool = False,
    incluir_arquivados: bool = False,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lista os chamados que o usuário pode ler, com filtros opcionais.
    Por padrão, exclui chamados cancelados e arquivados.

    O escopo de leitura entra primeiro (API-5): os filtros abaixo só estreitam
    o que já é permitido — `solicitante_id` de outra pessoa não traz os
    chamados dela —, e o offset e o limit cortam a página desse conjunto.
    """
    query = escopo_de_leitura(db.query(Chamado), current_user)

    # Filtros padrão para excluir cancelados e arquivados
    if not incluir_cancelados:
        query = query.filter(Chamado.cancelado == False)
    if not incluir_arquivados:
        query = query.filter(Chamado.arquivado == False)

    if status:
        query = query.filter(Chamado.status == status)
    if solicitante_id:
        query = query.filter(Chamado.solicitante_id == solicitante_id)
    if tecnico_id:
        query = query.filter(Chamado.tecnico_responsavel_id == tecnico_id)
    if setor_destino:
        query = query.filter(Chamado.setor_destino == setor_destino.value)

    # Ordem determinística: sem ela o Postgres não garante a mesma sequência
    # entre páginas, e o skip/limit repetiria ou puliria registros.
    chamados = query.order_by(Chamado.id.desc()).offset(skip).limit(limit).all()
    return _anexar_sla(chamados, db)


QUALIDADE_INDISPONIVEL = "Abertura de chamados para a Qualidade não está disponível neste ambiente"


# Antes de `/{chamado_id}`, como `/responsaveis-ti` abaixo: o FastAPI casa
# as rotas na ordem em que foram declaradas, e depois dela
# "atendentes-qualidade" seria lido como id.
@router.get("/atendentes-qualidade", response_model=List[AtendenteQualidade])
def listar_atendentes_qualidade(db: Session = Depends(get_db)):
    """
    Quem pode ser escolhido como responsável de um chamado da Qualidade.

    Aberto a qualquer perfil, como a abertura de chamado. Devolve só id e
    nome — o necessário para o seletor —, e a regra é a mesma que a criação
    aplica, então o que aparece aqui é aceito lá.
    """
    try:
        return listar_atendentes(db)
    except QualidadeIndisponivel:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=QUALIDADE_INDISPONIVEL)


@router.get("/responsaveis-ti", response_model=List[ResponsavelTI])
def listar_responsaveis_ti(
    current_user: Usuario = Depends(require_equipe_ti),
    db: Session = Depends(get_db),
):
    """
    Quem pode ser escolhido como novo responsável de um chamado da TI (API-9).

    Para o seletor de quem reatribui chamado da TI — o administrador e o
    técnico da TI, os únicos que o PUT deixa reatribuir —, por isso
    `require_equipe_ti`: o técnico da Qualidade, o de outro setor, o sem
    setor e o usuário comum recebem 403. Devolve só id e nome, e a regra é a
    mesma que o PUT aplica na mudança de responsável, então o que aparece
    aqui é aceito lá. Nenhum parâmetro do cliente entra na lista.

    O responsável atual de um chamado antigo pode não estar aqui (inativo,
    fora da equipe): continua no chamado, mas não é opção nova.
    """
    return listar_responsaveis(db)


@router.get("/{chamado_id}", response_model=ChamadoResponse)
def buscar_chamado(
    chamado_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Busca um chamado específico por ID, se o usuário puder lê-lo.

    Quem não pode recebe o mesmo 404 de um id que não existe (API-5, D6).
    """
    chamado = buscar_chamado_legivel(db, chamado_id, current_user)
    return _anexar_sla([chamado], db)[0]


def _validar_corpo_de_criacao(corpo: Any):
    """
    Valida o corpo com a classe do setor pedido.

    Feito à mão porque o FastAPI não escolhe a classe pelo valor de um campo.
    A escolha olha o `setor_destino` cru: só QUALIDADE exato vai para a
    classe da Qualidade; todo o resto — inclusive valor inválido ou corpo que
    nem é objeto — passa por `ChamadoCreate` e recebe dela exatamente o erro
    que recebia antes. O 422 é montado como o FastAPI monta (`loc` com "body"
    na frente), para o frontend não perceber diferença.
    """
    eh_qualidade = (
        isinstance(corpo, dict)
        and corpo.get("setor_destino") == SetorDestinoEnum.QUALIDADE.value
    )
    # Transição (API-13): o formulário novo sempre manda o setor escolhido, e
    # a ausência só vem de cliente antigo — o frontend de antes da 1.8.0, que
    # continua no ar entre o deploy da API e o do front, e volta num rollback
    # do front. Por isso ela ainda vale TI, como sempre valeu, e fica no log:
    # é a contagem que diz quando dá para tornar o campo obrigatório. Valor
    # presente e inválido segue recusado pela classe da TI (422).
    if isinstance(corpo, dict) and "setor_destino" not in corpo:
        logger.warning("criar_chamado sem setor_destino (cliente antigo): gravado como TI")
    modelo = ChamadoCreateQualidade if eh_qualidade else ChamadoCreate
    try:
        return modelo.model_validate(corpo, from_attributes=True)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**erro, "loc": ("body", *erro["loc"])} for erro in exc.errors()],
            body=corpo,
        )


def _schema_do_corpo(modelo) -> dict:
    # Os enums referenciados já estão em `components` pelo ChamadoResponse.
    schema = modelo.model_json_schema(ref_template="#/components/schemas/{model}")
    schema.pop("$defs", None)
    return schema


# O corpo é recebido como `Any`, então o OpenAPI não o descreveria sozinho.
CORPO_DE_CRIACAO_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "oneOf": [
                        _schema_do_corpo(ChamadoCreate),
                        _schema_do_corpo(ChamadoCreateQualidade),
                    ],
                },
            },
        },
    },
}


@router.post(
    "/",
    response_model=ChamadoResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=CORPO_DE_CRIACAO_OPENAPI,
)
def criar_chamado(
    corpo: Any = Body(...),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cria um novo chamado, para a TI ou para a Qualidade.

    O solicitante vem do token, não do corpo: aceitar do cliente permitia
    abrir chamado em nome de qualquer pessoa. Administrador continua podendo
    abrir em nome de outro, informando solicitante_id.

    TI: corpo `ChamadoCreate`, como sempre foi. Qualidade: corpo
    `ChamadoCreateQualidade` — título gerado da descrição, sem categoria,
    responsável obrigatório e elegível, e sem o webhook da TI.
    """
    chamado_data = _validar_corpo_de_criacao(corpo)
    eh_qualidade = isinstance(chamado_data, ChamadoCreateQualidade)

    # Antes de qualquer gravação: recusa aqui não deixa chamado pela metade.
    if eh_qualidade:
        try:
            atendente = buscar_atendente(db, chamado_data.tecnico_responsavel_id)
        except QualidadeIndisponivel:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=QUALIDADE_INDISPONIVEL)
        except AtendenteNaoEncontrado:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Atendente não encontrado")
        except AtendenteInelegivel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Atendente não é elegível para a Qualidade",
            )

    # Abrir em nome de outro é do administrador humano (API-11, S3): a conta
    # de serviço administradora abre como ela mesma, como qualquer outra conta.
    if is_admin_humano(current_user) and chamado_data.solicitante_id:
        solicitante_id = chamado_data.solicitante_id
    else:
        solicitante_id = current_user.id

    # Gerar protocolo único
    protocolo = gerar_protocolo(db)

    # Criar chamado
    if eh_qualidade:
        chamado = Chamado(
            protocolo=protocolo,
            solicitante_id=solicitante_id,
            categoria_id=None,
            titulo=derivar_titulo(chamado_data.descricao),
            descricao=chamado_data.descricao,
            prioridade=chamado_data.prioridade,
            setor_destino=SetorDestinoEnum.QUALIDADE.value,
            tecnico_responsavel_id=atendente.id,
            status="Aberto"
        )
        destino = f"Setor de destino: Qualidade | Responsável: {atendente.nome}"
    else:
        # Na TI o responsável é definido depois, pela equipe: um
        # `tecnico_responsavel_id` no corpo é ignorado, como sempre foi.
        chamado = Chamado(
            protocolo=protocolo,
            solicitante_id=solicitante_id,
            categoria_id=chamado_data.categoria_id,
            titulo=chamado_data.titulo,
            descricao=chamado_data.descricao,
            prioridade=chamado_data.prioridade,
            setor_destino=SetorDestinoEnum.TI.value,
            status="Aberto"
        )
        destino = "Setor de destino: TI"

    db.add(chamado)
    db.commit()
    db.refresh(chamado)

    # Registrar no histórico
    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=solicitante_id,
        acao="Abertura de chamado",
        descricao=f"Chamado aberto com protocolo {protocolo} | {destino}",
        status_novo="Aberto"
    )

    # Enviar webhook para notificação (sem técnico = "Sem atribuição").
    # Só TI: o fluxo do n8n avisa a equipe de TI, e um chamado da Qualidade
    # lá viraria notificação para quem não o atende.
    if not eh_qualidade:
        enviar_webhook_tecnico(
            db=db,
            protocolo=protocolo,
            titulo=chamado.titulo,
            tecnico_id=None,
            acao="criado"
        )

    return _anexar_sla([chamado], db)[0]


@router.put("/{chamado_id}", response_model=ChamadoResponse)
def atualizar_chamado(
    chamado_id: int,
    chamado_data: ChamadoUpdate,
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Atualiza um chamado existente. Restrito a administrador ou técnico.

    Chamado da Qualidade (API-4b): a linha é travada e relida antes de
    qualquer conferência, `versao_esperada` é obrigatória (428) e tem de bater
    com a versão travada (409), e chamado e histórico saem num commit só. Sem
    webhook, como sempre.

    TI: `versao_esperada` é opcional. Se vier (API-12), o caminho é o da
    Qualidade — trava, relê, confere e grava chamado e histórico num commit
    só —, e de duas escritas simultâneas com a mesma versão só uma passa; o
    webhook sai depois do commit. Sem ela, o fluxo de antes: sem trava, vale
    a última escrita, e o histórico tem commit próprio.

    Só o chamado do alcance da equipe de quem pede (API-6, D8): quem não o
    lê recebe o 404 de um id que não existe, antes da versão (D12); quem o
    lê só pelo vínculo, 403. Ordem: 401/403 do token e do perfil; 422 do
    corpo; 404; 403 da equipe; 428/409 de versão; 400 do responsável.
    """
    _avisar_usuario_id_depreciado("atualizar_chamado", usuario_id, current_user)

    chamado = buscar_chamado_alteravel(db, chamado_id, current_user)

    # O setor sai da leitura sem trava: o PUT não o altera, e nenhuma rota o
    # altera depois da criação. A trava é da Qualidade e, desde a API-12, da
    # TI que manda a versão: conferir sem o lock deixava duas escritas com a
    # mesma versão passarem as duas.
    eh_qualidade = chamado.setor_destino == SetorDestinoEnum.QUALIDADE.value
    travada = eh_qualidade or chamado_data.versao_esperada is not None
    if travada:
        # Relê a linha com `SELECT ... FOR UPDATE`: daqui até o commit, ninguém
        # mais escreve nela, e tudo abaixo — versão, responsável atual, status
        # anterior do histórico — é o estado travado, não o da primeira leitura.
        db.refresh(chamado, with_for_update=True)

    # Antes da validação dos campos: com a versão velha, o cliente decidiu
    # sobre um chamado que já não é este, e o que precisa saber é isso.
    conferir_versao(chamado, chamado_data.versao_esperada, obrigatoria=eh_qualidade)

    # Depois do 404: chamado inexistente é 404, não 400 por causa do técnico.
    # Antes de qualquer `setattr`: recusa aqui não grava nenhum campo.
    if eh_qualidade:
        _validar_responsavel_da_qualidade(db, chamado, chamado_data)
    else:
        _validar_tecnico_responsavel(db, chamado, chamado_data)

    # Armazenar status anterior e técnico anterior para histórico e webhook
    status_anterior = chamado.status
    tecnico_anterior = chamado.tecnico_responsavel_id

    # Atualizar campos. `versao_esperada` é pré-condição, não coluna.
    update_data = chamado_data.model_dump(exclude_unset=True, exclude={"versao_esperada"})
    for field, value in update_data.items():
        setattr(chamado, field, value)

    # Se mudou para "Resolvido" ou "Fechado", calcular tempo de resolução
    if chamado_data.status and chamado_data.status in ["Resolvido", "Fechado"]:
        if not chamado.data_resolucao:
            chamado.data_resolucao = agora_brasilia()
            chamado.tempo_resolucao_minutos = calcular_tempo_resolucao(
                chamado.data_abertura,
                chamado.data_resolucao
            )

    if travada:
        # Um commit para chamado e histórico, que também solta o lock. Qualquer
        # falha antes dele desfaz os dois: não fica chamado alterado sem o
        # histórico de que o SLA depende, nem histórico de mudança que não houve.
        try:
            if chamado_data.status and status_anterior != chamado_data.status:
                adicionar_historico(
                    db=db,
                    chamado_id=chamado.id,
                    usuario_id=current_user.id,
                    acao="Alteração de status",
                    descricao=f"Status alterado de {status_anterior} para {chamado_data.status.value}",
                    status_anterior=status_anterior,
                    status_novo=chamado_data.status.value
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(chamado)
        if eh_qualidade:
            return _anexar_sla([chamado], db)[0]
    else:
        db.commit()
        db.refresh(chamado)

        # Registrar no histórico se mudou o status
        if chamado_data.status and status_anterior != chamado_data.status:
            registrar_historico(
                db=db,
                chamado_id=chamado.id,
                usuario_id=current_user.id,
                acao="Alteração de status",
                descricao=f"Status alterado de {status_anterior} para {chamado_data.status.value}",
                status_anterior=status_anterior,
                status_novo=chamado_data.status.value
            )

    # Enviar webhook se o técnico foi atribuído ou alterado. Só TI, como na
    # abertura: o fluxo do n8n avisa a equipe de TI. Sempre depois do commit:
    # a escrita recusada (409) não chega aqui. (A Qualidade já saiu acima; o
    # `not eh_qualidade` fica como trava, caso o fluxo mude.)
    if (
        not eh_qualidade
        and chamado_data.tecnico_responsavel_id is not None
        and tecnico_anterior != chamado_data.tecnico_responsavel_id
    ):
        enviar_webhook_tecnico(
            db=db,
            protocolo=chamado.protocolo,
            titulo=chamado.titulo,
            tecnico_id=chamado_data.tecnico_responsavel_id,
            acao="atribuido"
        )

    return _anexar_sla([chamado], db)[0]


# Status em que o atendimento já terminou e faz sentido avaliar.
STATUS_AVALIAVEIS = (StatusEnum.RESOLVIDO.value, StatusEnum.FECHADO.value)


@router.patch("/{chamado_id}/avaliar", response_model=ChamadoResponse)
def avaliar_chamado(
    chamado_id: int,
    avaliacao_data: ChamadoAvaliacao,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Registra a avaliação do atendimento pelo solicitante.

    Existe como rota própria porque o PUT /{id} é `require_staff` e vai
    continuar sendo: por ele o solicitante conseguiria alterar status,
    prioridade e técnico responsável do próprio chamado. Aqui o único campo
    gravável é `avaliacao`.

    Só o solicitante avalia. Administrador e técnico não avaliam no lugar
    dele — a nota mede o atendimento que a equipe prestou, então deixar a
    própria equipe preenchê-la esvaziaria o indicador. Por isso a checagem é
    `solicitante_id != current_user.id` puro, sem escape por perfil.

    Quem não lê o chamado recebe o 404 de um id que não existe (API-6, D12),
    antes do 403: este diria a qualquer conta que o id existe.
    """
    chamado = buscar_chamado_legivel(db, chamado_id, current_user)

    if chamado.solicitante_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só o solicitante pode avaliar o próprio chamado",
        )

    if chamado.status not in STATUS_AVALIAVEIS:
        # 409 e não 400: o corpo está correto, o que impede é o estado atual
        # do chamado — resolver o chamado torna a mesma requisição válida.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O chamado só pode ser avaliado quando estiver resolvido ou fechado",
        )

    avaliacao_anterior = chamado.avaliacao
    chamado.avaliacao = avaliacao_data.avaliacao
    db.commit()
    db.refresh(chamado)

    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=current_user.id,
        acao="Avaliação do atendimento",
        descricao=(
            f"Avaliação alterada de {avaliacao_anterior} para {chamado.avaliacao}"
            if avaliacao_anterior is not None
            else f"Chamado avaliado com nota {chamado.avaliacao}"
        ),
    )

    return _anexar_sla([chamado], db)[0]


def _consulta_do_atendimento(db: Session, chamado_id: int):
    """
    O chamado a atender, com a linha travada (`SELECT ... FOR UPDATE`).

    O lock vale até o commit do atendimento. Uma reatribuição pelo PUT que
    grave antes faz esta leitura esperar e ver o responsável novo; uma que
    chegue depois espera o atendimento terminar. O SQLite dos testes ignora a
    cláusula — a disputa real só se prova em PostgreSQL.
    """
    return db.query(Chamado).filter(Chamado.id == chamado_id).with_for_update()


@router.patch("/{chamado_id}/atendimento", response_model=ChamadoResponse)
def atender_chamado(
    chamado_id: int,
    atendimento: ChamadoAtendimento,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atendimento de chamado da Qualidade pelo responsável atual.

    Existe porque quem atende a Qualidade costuma ter perfil comum, e o PUT é
    da equipe — por ele se mexe em responsável, prioridade e categoria. Aqui
    só o status, pelas transições das ações rápidas do frontend, e a solução
    ao resolver.

    Autorização pelo chamado e por quem pede, relidos do banco nesta
    requisição (`verificar_atendimento`); perfil não dá passe. Cancelado e
    arquivado estão fora do fluxo de atendimento (409). Sem webhook: o fluxo
    do n8n é da TI.

    Chamado e histórico vão no mesmo commit — o do `registrar_historico`,
    que é o único desta rota e também o que solta o lock. Qualquer falha
    antes dele desfaz os dois.

    `versao_esperada` é obrigatória (API-4b) e conferida na linha travada,
    depois da autorização. Ordem das recusas: 401/403 do token; 422 do corpo;
    404 (inexistente ou fora da leitura); 403/503 da autorização pelo
    chamado; 428 sem versão; 409 de versão; 409 de cancelado/arquivado; 409
    de transição.

    A leitura vem antes da autorização pelo chamado (API-6, D12): as recusas
    dela dizem o setor ("só chamados da Qualidade") e a quem o chamado está
    atribuído, e só quem já lê o chamado pode ouvi-las. A leitura é conferida
    na linha travada, com o responsável que vale para o atendimento.
    """
    chamado = _consulta_do_atendimento(db, chamado_id).first()
    if chamado is None or not pode_ler_chamado(current_user, chamado):
        raise ChamadoNaoEncontrado()

    try:
        verificar_atendimento(db, chamado, current_user)
    except ChamadoForaDaQualidade:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta rota atende só chamados da Qualidade",
        )
    except QualidadeIndisponivel:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=QUALIDADE_INDISPONIVEL)
    except AtendenteInelegivel:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não atende a Qualidade")
    except NaoEhResponsavel:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só o responsável atual pode atender este chamado",
        )

    # Depois da autorização: o 409 de versão diz a versão atual, e quem não
    # atende o chamado não tem por que sabê-la. Antes das recusas de estado:
    # com a versão velha, a pessoa decidiu sobre um estado que já mudou.
    conferir_versao(chamado, atendimento.versao_esperada, obrigatoria=True)

    # 409, como no /avaliar: o corpo está certo, o que impede é o estado.
    for marca in ("cancelado", "arquivado"):
        if getattr(chamado, marca):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Chamado {marca} não pode ser atendido",
            )

    status_anterior = chamado.status
    status_novo = atendimento.status.value
    if not transicao_permitida(status_anterior, status_novo):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transição de {status_anterior} para {status_novo} não permitida",
        )

    try:
        chamado.status = status_novo
        if atendimento.status is StatusEnum.RESOLVIDO:
            chamado.solucao = atendimento.solucao
            # Mesma regra do PUT: data e tempo são os da primeira resolução,
            # e reabrir não os apaga.
            if not chamado.data_resolucao:
                chamado.data_resolucao = agora_brasilia()
                chamado.tempo_resolucao_minutos = calcular_tempo_resolucao(
                    chamado.data_abertura,
                    chamado.data_resolucao
                )

        # Mesmo formato do PUT: é dele que o SLA lê pausas e resolução.
        registrar_historico(
            db=db,
            chamado_id=chamado.id,
            usuario_id=current_user.id,
            acao="Alteração de status",
            descricao=f"Status alterado de {status_anterior} para {status_novo}",
            status_anterior=status_anterior,
            status_novo=status_novo
        )
    except Exception:
        db.rollback()
        raise

    db.refresh(chamado)
    return _anexar_sla([chamado], db)[0]


# Corpo opcional das três marcas: sem ele, a requisição de antes continua
# valendo (a TI e o frontend atual não mandam corpo nenhum).
CORPO_DE_MARCA = Body(None)


def _travar_e_conferir_marca(db: Session, chamado: Chamado, corpo: Optional[ChamadoMarca]) -> bool:
    """
    Pré-condição das marcas (API-4b). Devolve se a linha foi travada.

    Qualidade: trava e relê a linha, e exige a versão (428/409). TI: versão
    opcional; se vier, trava e confere como a Qualidade (API-12, como no
    PUT); sem ela, sem trava, como antes. Chamar depois da autorização e
    antes das recusas de estado ("já está cancelado"), que passam a ler a
    linha travada.
    """
    eh_qualidade = chamado.setor_destino == SetorDestinoEnum.QUALIDADE.value
    esperada = corpo.versao_esperada if corpo is not None else None
    travada = eh_qualidade or esperada is not None
    if travada:
        db.refresh(chamado, with_for_update=True)
    conferir_versao(chamado, esperada, obrigatoria=eh_qualidade)
    return travada


def _gravar_marca(db: Session, chamado: Chamado, travada: bool, usuario_id: int, acao: str, descricao: str):
    """
    Grava a marca já posta no chamado, e o histórico dela.

    Linha travada (Qualidade, ou TI com versão): num commit só, que solta o
    lock; falha desfaz os dois. TI sem versão: o de antes — commit do
    chamado, depois o do histórico.
    """
    if travada:
        try:
            adicionar_historico(db=db, chamado_id=chamado.id, usuario_id=usuario_id, acao=acao, descricao=descricao)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(chamado)
        return

    db.commit()
    db.refresh(chamado)
    registrar_historico(db=db, chamado_id=chamado.id, usuario_id=usuario_id, acao=acao, descricao=descricao)


@router.patch("/{chamado_id}/cancelar", response_model=ChamadoResponse)
def cancelar_chamado(
    chamado_id: int,
    corpo: Optional[ChamadoMarca] = CORPO_DE_MARCA,
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cancela um chamado (soft delete - apenas marca como cancelado).

    O solicitante pode cancelar o próprio chamado; a equipe cancela os do
    alcance dela (API-6, D8): administrador, todos; técnico, os do setor que
    o perfil lê. Em chamado da Qualidade, exige `versao_esperada` (ver
    `_travar_e_conferir_marca`).

    Quem não lê o chamado recebe o 404 de um id que não existe (D12), antes
    do 403 e da versão. Ler pelo vínculo não dá o cancelamento: o responsável
    que não é o solicitante nem tem o chamado no alcance da equipe recebe 403.
    """
    _avisar_usuario_id_depreciado("cancelar_chamado", usuario_id, current_user)

    chamado = buscar_chamado_legivel(db, chamado_id, current_user)

    # Pela leitura sem trava: o solicitante não muda depois da abertura, nem
    # o setor de destino, que decide o alcance da equipe.
    if not pode_alterar_como_equipe(current_user, chamado) and chamado.solicitante_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só é possível cancelar chamados abertos por você",
        )

    travada = _travar_e_conferir_marca(db, chamado, corpo)

    if chamado.cancelado:
        raise HTTPException(status_code=400, detail="Chamado já está cancelado")

    chamado.cancelado = True
    _gravar_marca(
        db, chamado, travada, current_user.id,
        acao="Cancelamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi cancelado",
    )

    return _anexar_sla([chamado], db)[0]


@router.patch("/{chamado_id}/arquivar", response_model=ChamadoResponse)
def arquivar_chamado(
    chamado_id: int,
    corpo: Optional[ChamadoMarca] = CORPO_DE_MARCA,
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Arquiva um chamado (remove da visualização padrão mas mantém no banco).
    Restrito à equipe, nos chamados do alcance dela (ver o PUT: 404 para
    quem não lê, 403 para quem lê só pelo vínculo). Em chamado da Qualidade, exige
    `versao_esperada` (ver `_travar_e_conferir_marca`).
    """
    _avisar_usuario_id_depreciado("arquivar_chamado", usuario_id, current_user)

    chamado = buscar_chamado_alteravel(db, chamado_id, current_user)

    travada = _travar_e_conferir_marca(db, chamado, corpo)

    if chamado.arquivado:
        raise HTTPException(status_code=400, detail="Chamado já está arquivado")

    chamado.arquivado = True
    _gravar_marca(
        db, chamado, travada, current_user.id,
        acao="Arquivamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi arquivado",
    )

    return _anexar_sla([chamado], db)[0]


@router.patch("/{chamado_id}/desarquivar", response_model=ChamadoResponse)
def desarquivar_chamado(
    chamado_id: int,
    corpo: Optional[ChamadoMarca] = CORPO_DE_MARCA,
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Desarquiva um chamado (volta a exibir na visualização padrão).
    Restrito à equipe, nos chamados do alcance dela (ver o PUT: 404 para
    quem não lê, 403 para quem lê só pelo vínculo). Em chamado da Qualidade, exige
    `versao_esperada` (ver `_travar_e_conferir_marca`).
    """
    _avisar_usuario_id_depreciado("desarquivar_chamado", usuario_id, current_user)

    chamado = buscar_chamado_alteravel(db, chamado_id, current_user)

    travada = _travar_e_conferir_marca(db, chamado, corpo)

    if not chamado.arquivado:
        raise HTTPException(status_code=400, detail="Chamado não está arquivado")

    chamado.arquivado = False
    _gravar_marca(
        db, chamado, travada, current_user.id,
        acao="Desarquivamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi desarquivado",
    )

    return _anexar_sla([chamado], db)[0]


@router.delete("/{chamado_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_chamado(
    chamado_id: int,
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Deleta um chamado em definitivo. Restrito a administrador.

    É exclusão real (db.delete), não soft delete — o registro some junto
    com seu histórico. Para tirar da visualização use cancelar ou arquivar.
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    db.delete(chamado)
    db.commit()
    return None
