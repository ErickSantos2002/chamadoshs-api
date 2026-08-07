---
name: hsapi-pr-description
description: Gera descrição de Pull Request da API ChamadosHS a partir do diff ou dos commits do branch, destacando migrations, variáveis de ambiente e ordem de subida com o front. Nunca abre o PR.
---

# Skill: PR Description — chamadoshs-api

## Objetivo

Gerar descrição clara e padronizada de PR, com contexto suficiente para revisar
com confiança e **subir na ordem certa**.

## Contexto que muda a descrição

- Dois repositórios independentes (`chamadoshs-api` e `chamadoshs-sistema`).
  Uma feature pode exigir PR em cada um
- Migrations são `.sql` **aplicados à mão**, sem Alembic — nunca são detalhe de
  rodapé
- Deploy **manual pelo usuário via Easypanel**, sem CI/CD
- Variáveis são lidas em runtime: mudança exige restart, não rebuild
- Não há testes automatizados — o "como testar" é o que garante a validação
- O `main.py` tem trava que impede a app de subir com rota desprotegida: se o PR
  mexe em router, dizer que a app sobe limpa

## O que pedir se não for fornecido

- `git log main..HEAD --oneline` ou o diff
- Contexto: bug, feature, refactor, segurança?
- Há migration?
- Muda contrato? Precisa de PR no repositório irmão?

## Estrutura gerada

```markdown
## O que foi feito
[O que muda, do ponto de vista de quem usa o sistema]

## Por que foi feito
[Motivação: bug, requisito, decisão técnica, achado de segurança]

## Como testar
- [ ] `uvicorn main:app` sobe sem erro (trava de rotas passa)
- [ ] Passo 2
- [ ] Comportamento esperado: ...

## Impacto
- [ ] Breaking change no contrato da API
- [ ] Requer migration SQL — arquivo: `migrations/xxx.sql`
- [ ] Requer variável de ambiente nova
- [ ] Altera comportamento de autenticação (ver ordem de subida)
- [ ] Precisa de PR no repositório irmão — link:

## Ordem de subida
1. [ex.: backup do banco]
2. [ex.: aplicar migrations/xxx.sql]
3. [ex.: subir chamadoshs-api]
4. [ex.: subir chamadoshs-sistema]

## Checklist
- [ ] Aplicação sobe localmente
- [ ] Sem `print()` de debug
- [ ] Variáveis novas documentadas no `.env.example`
- [ ] Model e migration sincronizados
- [ ] Testado manualmente (descrever o quê)
```

## Regras

- Título no padrão de commit do projeto: `tipo(escopo): descrição em português`
- Não listar arquivos como descrição — explicar o impacto
- **Migration sempre em destaque**, com nome do arquivo e o lembrete de backup
- Mudança de autenticação exige seção "Ordem de subida" explicando por que o
  front vem antes (sessão do usuário)
- Adaptar o detalhe ao tamanho do PR

## Observações

- **Nunca abrir o PR automaticamente**
- Diff acima de ~500 linhas: sugerir dividir
- Aproveitar o contexto da sessão para decisões já discutidas
