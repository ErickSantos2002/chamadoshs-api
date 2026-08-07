"""
Configuração da suíte de testes.

Fica na raiz de propósito: o pytest carrega este arquivo antes de importar
qualquer teste, e a aplicação não pode nem ser importada sem DATABASE_URL e
SECRET_KEY — `Settings` declara os dois sem valor padrão, então a ausência
levanta erro já no `import`.

Nenhum teste toca o banco. A DATABASE_URL aqui existe só para satisfazer a
validação de configuração; a engine do SQLAlchemy é preguiçosa e não abre
conexão enquanto ninguém consulta.
"""

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

os.environ.setdefault("DATABASE_URL", "postgresql://teste:teste@localhost:5432/teste")
os.environ.setdefault("SECRET_KEY", "chave-apenas-para-testes-nao-usar-em-producao")
os.environ.setdefault("ENVIRONMENT", "development")

# O container roda em UTC e o sistema opera em horário de Brasília. Fixar o TZ
# do processo impede que um teste passe na máquina de quem escreveu e falhe no
# CI só porque o fuso do sistema é outro. As funções de horário já normalizam
# para Brasília internamente — isto é cinto e suspensório.
os.environ.setdefault("TZ", "UTC")
