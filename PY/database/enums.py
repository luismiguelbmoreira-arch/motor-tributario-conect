from enum import Enum

class RegimeTributario(str, Enum):
    """
    Regimes tributários suportados pelo motor.
    LC 123/2006 (Simples/MEI) | RIR/2018 (Presumido/Real).
    """
    SIMPLES = "SIMPLES"
    PRESUMIDO = "PRESUMIDO"
    REAL = "REAL"
    MEI = "MEI"


class NivelAlerta(str, Enum):
    """Níveis de severidade para alertas do motor."""
    INFO = "INFO"
    MEDIO = "MEDIO"
    ATENCAO = "ATENCAO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"


class StatusAlerta(str, Enum):
    """Ciclo de vida do alerta."""
    ABERTO = "ABERTO"
    RESOLVIDO = "RESOLVIDO"
    IGNORADO = "IGNORADO"


class StatusAuditoria(str, Enum):
    """Status de auditoria do diagnóstico vs e-CAC."""
    APROVADO = "APROVADO"
    PENDENTE = "PENDENTE"
    REJEITADO = "REJEITADO"
