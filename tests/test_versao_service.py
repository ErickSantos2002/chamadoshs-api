"""
Contrato da pré-condição de versão (API-4b), sem HTTP de rota.

- `conferir_versao`: 428 sem versão quando obrigatória, 409 com a versão atual
  quando diverge, e nada além disso — não grava, não toca em `versao`;
- o handler de `main.py` põe `codigo` e `versao_atual` no nível de cima, só
  no 409 de versão;
- `versao_esperada` nos schemas: inteiro positivo estrito, `null` explícito
  recusado, e ausência distinta de `null` (ausente vira None, e quem decide
  se é 428 é o endpoint).
"""

import asyncio
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import main
from app.models import Chamado
from app.schemas.chamado import ChamadoAtendimento, ChamadoMarca, ChamadoUpdate
from app.services.versao_service import (
    VERSAO_AUSENTE,
    VERSAO_DESATUALIZADA,
    VersaoAusente,
    VersaoDesatualizada,
    conferir_versao,
)


class TestConferirVersao:
    def _chamado(self, versao=3):
        return Chamado(versao=versao)

    def test_ausente_e_obrigatoria_e_428(self):
        with pytest.raises(VersaoAusente) as erro:
            conferir_versao(self._chamado(), None, obrigatoria=True)
        assert erro.value.status_code == 428
        assert erro.value.detail == VERSAO_AUSENTE

    def test_ausente_e_opcional_passa(self):
        conferir_versao(self._chamado(), None, obrigatoria=False)

    @pytest.mark.parametrize("obrigatoria", [True, False])
    def test_igual_passa(self, obrigatoria):
        conferir_versao(self._chamado(3), 3, obrigatoria=obrigatoria)

    @pytest.mark.parametrize("obrigatoria", [True, False])
    @pytest.mark.parametrize("esperada", [1, 2, 4, 2**40])
    def test_diferente_e_409_com_a_versao_atual(self, obrigatoria, esperada):
        with pytest.raises(VersaoDesatualizada) as erro:
            conferir_versao(self._chamado(3), esperada, obrigatoria=obrigatoria)
        assert erro.value.status_code == 409
        assert erro.value.corpo() == {
            "detail": VERSAO_DESATUALIZADA,
            "codigo": "versao_desatualizada",
            "versao_atual": 3,
        }

    def test_nao_mexe_na_versao_do_chamado(self):
        chamado = self._chamado(3)
        with pytest.raises(VersaoDesatualizada):
            conferir_versao(chamado, 9, obrigatoria=True)
        conferir_versao(chamado, 3, obrigatoria=True)
        assert chamado.versao == 3

    def test_as_recusas_sao_http_exception(self):
        """Sem handler nenhum, ainda saem como 428/409 — nunca como 500."""
        assert issubclass(VersaoAusente, HTTPException)
        assert issubclass(VersaoDesatualizada, HTTPException)


class TestHandlerDoConflito:
    def test_so_o_409_de_versao_tem_handler_proprio(self):
        assert VersaoDesatualizada in main.app.exception_handlers
        assert VersaoAusente not in main.app.exception_handlers

    def test_corpo_no_nivel_de_cima(self):
        handler = main.app.exception_handlers[VersaoDesatualizada]
        resposta = asyncio.run(handler(None, VersaoDesatualizada(8)))
        assert resposta.status_code == 409
        assert json.loads(resposta.body) == {
            "detail": "Este chamado foi alterado por outra pessoa. Atualize e tente de novo.",
            "codigo": "versao_desatualizada",
            "versao_atual": 8,
        }


SCHEMAS = pytest.mark.parametrize(
    "schema,base",
    [
        (ChamadoUpdate, {}),
        (ChamadoAtendimento, {"status": "Em Andamento"}),
        (ChamadoMarca, {}),
    ],
    ids=["update", "atendimento", "marca"],
)


class TestVersaoEsperadaNosSchemas:
    @SCHEMAS
    def test_ausente_vira_none_fora_dos_campos_enviados(self, schema, base):
        corpo = schema.model_validate(base)
        assert corpo.versao_esperada is None
        assert "versao_esperada" not in corpo.model_fields_set

    @SCHEMAS
    @pytest.mark.parametrize("valor", [1, 7, 2**40])
    def test_inteiro_positivo_passa(self, schema, base, valor):
        assert schema.model_validate({**base, "versao_esperada": valor}).versao_esperada == valor

    @SCHEMAS
    @pytest.mark.parametrize(
        "valor",
        [0, -1, True, False, "1", "abc", 1.0, None, [1], {"v": 1}],
        ids=["zero", "negativa", "true", "false", "string-numerica", "string", "float", "null", "lista", "objeto"],
    )
    def test_invalido_e_recusado(self, schema, base, valor):
        with pytest.raises(ValidationError) as erro:
            schema.model_validate({**base, "versao_esperada": valor})
        assert erro.value.errors()[0]["loc"] == ("versao_esperada",)

    def test_versao_esperada_nao_vai_para_o_que_o_put_grava(self):
        corpo = ChamadoUpdate.model_validate({"prioridade": "Alta", "versao_esperada": 4})
        assert corpo.model_dump(exclude_unset=True, exclude={"versao_esperada"}) == {"prioridade": "Alta"}

    def test_atendimento_segue_recusando_campo_a_mais(self):
        with pytest.raises(ValidationError):
            ChamadoAtendimento.model_validate({"status": "Em Andamento", "versao_esperada": 1, "versao": 1})

    def test_marca_ignora_campo_desconhecido(self):
        assert ChamadoMarca.model_validate({"motivo": "x"}).versao_esperada is None
