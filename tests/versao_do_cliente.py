"""
O que o cliente da API-4b faz antes de escrever num chamado da Qualidade:
lê o chamado e manda, em `versao_esperada`, a versão que leu.

Para os testes de antes da API-4b, que exercitam outra regra (transição,
responsável, histórico) e escreviam sem versão. Eles continuam provando a
mesma coisa, agora como um cliente atualizado escreveria.

Não mexe no corpo quando:
- o chamado não é da Qualidade (a TI segue sem versão — é o que se quer
  provar dela);
- o corpo já traz `versao_esperada` (é o teste que decide o valor, ou a
  ausência dele: esses usam `cliente` direto);
- a leitura falha (sem token, inativo, inexistente): a escrita vai como veio
  e recebe a recusa que receberia, que vem antes da versão.
"""


def com_versao_lida(cliente, chamado_id, corpo, headers):
    if not isinstance(corpo, dict) or "versao_esperada" in corpo:
        return corpo
    leitura = cliente.get(f"/api/v1/chamados/{chamado_id}", headers=headers)
    if leitura.status_code != 200 or leitura.json()["setor_destino"] != "QUALIDADE":
        return corpo
    return {**corpo, "versao_esperada": leitura.json()["versao"]}
