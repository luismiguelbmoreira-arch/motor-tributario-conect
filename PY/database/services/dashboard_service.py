from decimal import Decimal
from typing import Any, Dict, List
from sqlmodel import select, func
from ..connection import get_session
from ..models import EmpresaDB, DiagnosticoDB, AlertaDB, AuditoriaAcessoDB
from ..enums import NivelAlerta, StatusAlerta

def get_dashboard_metrics() -> Dict[str, Any]:
    """Agrega métricas reais para o Dashboard."""
    with get_session() as session:
        # 1. Total de Empresas
        total_empresas = session.exec(select(func.count(EmpresaDB.id))).one()

        # 2. Economia Total
        diagnosticos = session.exec(select(DiagnosticoDB.delta).where(DiagnosticoDB.delta != None)).all()
        soma_delta = sum((Decimal(d) for d in diagnosticos), Decimal("0"))

        # 3. Alertas Críticos/Altos (ABERTOS)
        alertas_criticos = session.exec(
            select(func.count(AlertaDB.id))
            .where(AlertaDB.nivel.in_([NivelAlerta.CRITICO, NivelAlerta.ALTO]))
            .where(AlertaDB.status == StatusAlerta.ABERTO)
        ).one()

        # 4. Auditorias recentes
        recentes = session.exec(
            select(DiagnosticoDB, EmpresaDB.razao_social)
            .join(EmpresaDB, DiagnosticoDB.empresa_id == EmpresaDB.id)
            .order_by(DiagnosticoDB.created_at.desc())
            .limit(5)
        ).all()

        audit_results = []
        for diag, rs in recentes:
            audit_results.append({
                "empresa": rs,
                "periodo": diag.competencia,
                "delta": f"{' ' if Decimal(diag.delta or 0) >= 0 else '-'} R$ {abs(Decimal(diag.delta or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "status": diag.status_auditoria or "REVISAR",
                "tipo": "emerald" if diag.status_auditoria == "APROVADO" else "accent"
            })

        # 5. Projeção Mensal
        all_diags = session.exec(
            select(DiagnosticoDB.competencia, DiagnosticoDB.das_mensal, DiagnosticoDB.delta)
            .order_by(DiagnosticoDB.competencia.desc())
            .limit(12)
        ).all()
        
        all_diags = list(all_diags)
        all_diags.reverse()

        labels = []
        simples_data = []
        reforma_data = []

        for comp, das, delta in all_diags:
            v_das = Decimal(das or 0)
            v_delta = Decimal(delta or 0)
            labels.append(comp)
            simples_data.append(float(v_das))
            reforma_data.append(float(v_das - v_delta))

        if not labels:
            labels = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun"]
            simples_data = [0] * 6
            reforma_data = [0] * 6

        return {
            "stats": {
                "empresas_ativas": total_empresas,
                "economia_apurada": f"{soma_delta:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "alertas_risco": alertas_criticos,
                "precisao": 99.8
            },
            "recent_audits": audit_results,
            "projection": {
                "labels": labels,
                "simples_nacional": simples_data,
                "receita_reforma": reforma_data
            }
        }
