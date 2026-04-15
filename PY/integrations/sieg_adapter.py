"""
sieg_adapter.py — Shim de compatibilidade.
Redireciona para database/sieg_service.py pós-faxina arquitetural.
"""
from .sieg_service import (
    SiegError,
    SiegRateLimitError,
    SiegXml,
    XML_TYPE_NFE,
    XML_TYPE_CTE,
    XML_TYPE_NFSE,
    XML_TYPE_NFCE,
    SiegService
)

class SiegAdapter(SiegService):
    """Herda de SiegService para prover nomes de métodos legados para testes."""
    
    def baixar_xmls(self, cnpj, data_inicio, data_fim, xml_type=XML_TYPE_NFE):
        # Mapeamento para o novo método público raw
        return self.baixar_xmls_raw(
            cnpj=cnpj,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=xml_type
        )
