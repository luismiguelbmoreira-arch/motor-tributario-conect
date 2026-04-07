import urllib.request
import json
from pathlib import Path

def get_anexo_base(cnae_id: str) -> str:
    """
    Regra geral baseada na Lei Complementar 123/2006.
    """
    pref2 = cnae_id[:2]
    num = int(pref2)
    
    # INDÚSTRIA (Seções B e C) -> Anexo II
    if 5 <= num <= 33:
        return "II"
        
    # CONSTRUÇÃO CIVIL (Seção F) -> Anexo IV
    if num in (41, 42, 43):
        return "IV"
        
    # COMÉRCIO (Seção G) -> Anexo I
    if num in (45, 46, 47):
        return "I"
        
    # ALIMENTAÇÃO (Restaurantes, bares) -> Anexo I (LC 123/2006 Art 18 §4º, I)
    if num == 56:
        return "I"
        
    # SERVIÇOS INTELECTUAIS / Fator R (Exemplos gerais) -> Anexo V (podendo cair pro III)
    # 62 (TI), 69 (Contábil/Jurídico), 71 (Engenharia), 73 (Publicidade), 86 (Saúde)
    if num in (62, 63, 69, 70, 71, 72, 73, 74, 85, 86, 87, 88):
        return "V"
        
    # SERVIÇOS GERAIS, TRANSPORTE, ALOJAMENTO -> Anexo III
    return "III"

def aplicar_excecoes_conhecidas(mapa):
    """Aplica as exceções já mapeadas no projeto original."""
    excecoes = {
        # Indústria confundida com Comércio
        "4721101": "II", # Panificação
        "1091102": "II", # Biscoitos
        "2539001": "II", # Usinagem
        # Comércio específico
        "4757100": "I",
        # Serviços especializados que vão para Anexo IV
        "8011101": "IV", "8121400": "IV", "8129000": "IV",
    }
    for cnae, anexo in excecoes.items():
        if cnae in mapa:
            mapa[cnae] = anexo
    return mapa

def main():
    u = 'https://servicodados.ibge.gov.br/api/v2/cnae/subclasses'
    print("Baixando tabela de CNAEs do IBGE (API CONCLA)...")
    req = urllib.request.urlopen(u)
    data = json.loads(req.read().decode('utf-8'))
    
    mapa = {}
    for item in data:
        cnae = item['id'].replace("-", "").replace("/", "")
        anexo = get_anexo_base(cnae)
        mapa[cnae] = anexo
        
    # Applica as exceções que já existiam no motor
    mapa = aplicar_excecoes_conhecidas(mapa)
    
    out_path = Path(__file__).resolve().parent.parent / "data" / "cnae_completo.json"
    out_path.parent.mkdir(exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mapa, f, indent=4, sort_keys=True)
        
    print(f"Sucesso! {len(mapa)} CNAEs mapeados e salvos em {out_path}.")

if __name__ == "__main__":
    main()
