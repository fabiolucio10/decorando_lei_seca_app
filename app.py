import json
import re

# Banco de dados de legislação (Exemplo com CPP)
LEGISLACAO_DATABASE = {
    "Art. 6o": {
        "caput": "Logo que tiver conhecimento da prática da infração penal, a autoridade policial deverá:",
        "incisos": {
            "I": "ouvir o ofendido;",
            "II": "ouvir o indiciado, com observância, no que for aplicável, do disposto no Capítulo III do Título Vll deste Livro, devendo o respectivo termo ser assinado por duas testemunhas que lhe tenham ouvido a leitura;",
            "III": "proceder a reconhecimento de pessoas e coisas e a acareações;",
            "IV": "determinar, se for o caso, que se proceda a exame de corpo de delito e a quaisquer outras perícias;",
            "V": "determinar que se procedam a buscas e apreensões, observando o disposto na legislação específica;",
            "VI": "proceder a reconhecimento de pessoas e coisas e a acareações;"
        }
    },
    "Art. 9o": {
        "caput": "Todas as peças do inquérito policial serão, num só processado, reduzidas a escrito ou datilografadas e, neste caso, rubricadas pela autoridade.",
        "incisos": {}
    }
}

def formatar_texto_artigo(artigo_num: str, inciso_or_paragrafo: str = None) -> str:
    """
    Retorna a estrutura completa do artigo.
    Se houver inciso/parágrafo, inclui o 'caput' antes do dispositivo específico.
    """
    artigo_data = LEGISLACAO_DATABASE.get(artigo_num)
    if not artigo_data:
        return ""
    
    caput = artigo_data["caput"]
    
    if inciso_or_paragrafo and inciso_or_paragrafo in artigo_data.get("incisos", {}):
        texto_dispositivo = artigo_data["incisos"][inciso_or_paragrafo]
        # Monta a estrutura formal: Caput + Inciso/Parágrafo
        return f"{artigo_num} {caput}\n{inciso_or_paragrafo} - {texto_dispositivo}"
    
    return f"{artigo_num} {caput}"


def gerar_prompt_ia(artigo_num: str, inciso_or_paragrafo: str = None) -> str:
    """
    Gera o prompt rigoroso para a IA criar o exemplo prático correto e contextualmente alinhado.
    """
    texto_legal_completo = formatar_texto_artigo(artigo_num, inciso_or_paragrafo)
    
    prompt = f"""
Você é um especialista em elaboração de questões de concursos públicos na área jurídica.

Dispositivo Legal Analisado:
{texto_legal_completo}

Sua tarefa é gerar uma explicação didática e um EXEMPLO PRÁTICO DA VIDA REAL estritamente específico para o dispositivo acima.

REGRAS OBRIGATÓRIAS:
1. O "Caso Concreto" DEVE retratar exatamente a conduta descrita no inciso/parágrafo/artigo especificado. NÃO use modelos genéricos ou genéricos de oitiva/depoimento a menos que o artigo seja especificamente sobre isso.
2. Se o dispositivo for o Art. 6º, VI (Reconhecimento/Acareação), o exemplo DEVE envolver a identificação do suspeito por vítima/testemunha ou o confronto de depoimentos divergentes.
3. Se o dispositivo for o Art. 9º (Formalização do Inquérito), o exemplo DEVE envolver a autuação, juntada e rubrica das peças do processo.

FORMATO DE SAÍDA ESPERADO (JSON strictly):
{{
  "explicacao_direta": "O item está [CERTO/ERRADO]. Explicar o motivo da alteração ou se o texto está correto.",
  "caso_concreto": "Descrição do caso real com nomes e situação fática correspondente ao dispositivo.",
  "aplicacao_norma": "Explicação jurídica vinculando o caso ao artigo/inciso citado.",
  "pegadinha_questao": "Detalhamento da alteração feita no enunciado (ex: inserção indevida de negação 'não')."
}}
"""
    return prompt


# Exemplo de payload formatado para exibição na interface do aluno
def montar_questao_formatada(numero_questao: int, artigo_num: str, inciso_num: str, alterado_com_erro: bool = True):
    texto_caput = LEGISLACAO_DATABASE[artigo_num]["caput"]
    texto_inciso = LEGISLACAO_DATABASE[artigo_num]["incisos"].get(inciso_num, "")
    
    # Simulação da alteração da banca (inserção indevida de "não")
    if alterado_com_erro:
        texto_inciso_enunciado = texto_inciso.replace("proceder a", "proceder não a")
    else:
        texto_inciso_enunciado = texto_inciso

    layout_questao = {
        "titulo": f"Questão {numero_questao} de 56",
        "dispositivo_head": f"{artigo_num}, inciso {inciso_num}",
        "enunciado": f"De acordo com o **{artigo_num}**:\n\"{texto_caput}\"\n\n**Inciso {inciso_num}**: \"{inciso_num} - {texto_inciso_enunciado}\"",
        "gabarito": "ERRADO" if alterado_com_erro else "CERTO",
        "explicacao": {
            "explicacao_direta": "O item está **ERRADO**. A banca alterou a regra original do artigo inserindo a palavra 'não'.",
            "exemplo_pratico": {
                "caso_concreto": "Durante uma investigação de roubo, a vítima afirma ter visto o suspeito. O Delegado de Polícia organiza um procedimento formal para que a vítima identifique o investigado entre outras pessoas com características semelhantes (reconhecimento de pessoas). Adicionalmente, existindo divergências entre os depoimentos de duas testemunhas, o Delegado coloca-as frente a frente para esclarecer os fatos (acareação).",
                "aplicacao_norma": f"A conduta da autoridade cumpre exatamente as diligências previstas no **{artigo_num}, inciso {inciso_num} do CPP**.",
                "pegadinha": "Houve **inserção indevida de negação ('não')** no texto apresentado no enunciado."
            },
            "texto_original": f"\"{artigo_num} {texto_caput}\n{inciso_num} - {texto_inciso}\""
        }
    }
    return layout_questao

# Execução de Teste
if __name__ == "__main__":
    resultado = montar_questao_formatada(6, "Art. 6o", "VI", alterado_com_erro=True)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))