import os
import re
import sqlite3
from datetime import datetime, timedelta
import fitz  # PyMuPDF
import streamlit as st

DB_PATH = "sistema_questoes.db"

# ==========================================
# 1. BANCO DE DADOS E ESTRUTURA
# ==========================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    # Tabela de Leis
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL
        )
    """)
    # Tabela de Artigos / Dispositivos Fracionados
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artigos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lei_id INTEGER NOT NULL,
            numero TEXT NOT NULL,
            titulo TEXT,
            texto TEXT NOT NULL,
            caso_pratico TEXT,
            FOREIGN KEY(lei_id) REFERENCES leis(id) ON DELETE CASCADE
        )
    """)
    # Tabela de Revisões / Histórico
    conn.execute("""
        CREATE TABLE IF NOT EXISTS revisoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artigo_id INTEGER NOT NULL,
            proxima_revisao DATE NOT NULL,
            intervalo INTEGER DEFAULT 1,
            repetition INTEGER DEFAULT 0,
            FOREIGN KEY(artigo_id) REFERENCES artigos(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

# ==========================================
# 2. FRACIONAMENTO INTELIGENTE DE PDF (REGEX)
# ==========================================

def limpar_e_formatar_texto_lei(texto):
    texto = re.sub(r'\r\n|\r|\n', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()

def gerar_exemplo_pratico(texto_dispositivo):
    """Gera um pequeno caso prático para o dispositivo fracionado."""
    return f"Situação Hipotética: Durante um procedimento, foi aplicado o disposto no trecho '{texto_dispositivo[:60]}...'. A conduta adotada pela autoridade atendeu estritamente ao previsto na norma."

def parse_and_store_pdf(pdf_bytes, law_id):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = " ".join([page.get_text() for page in doc])
    doc.close()

    full_text = limpar_e_formatar_texto_lei(full_text)

    # 1. Identifica e separa por Artigos (ex: Art. 14., Art. 14-A.)
    padrao_artigo = re.compile(r'(Art\.\s*\d+[\w\d\-\.]*)', re.IGNORECASE)
    partes = padrao_artigo.split(full_text)

    artigos_brutos = []
    for i in range(1, len(partes), 2):
        num_art = partes[i].strip()
        corpo_art = partes[i+1] if (i+1) < len(partes) else ""
        artigos_brutos.append((num_art, corpo_art))

    unidades_finais = []

    for num_art, corpo in artigos_brutos:
        corpo = corpo.strip()
        if not corpo:
            continue

        # 2. Fracionamento interno: Procura por Parágrafos (§ ou Parágrafo único) ou Incisos
        padrao_subdivisao = re.compile(r'(§\s*\d+º?|Parágrafo\s+único|[I|V|X]+\s*-)', re.IGNORECASE)
        subpartes = padrao_subdivisao.split(corpo)

        if len(subpartes) > 1:
            caput = subpartes[0].strip()
            if caput:
                unidades_finais.append((f"{num_art} (caput)", caput))

            idx = 1
            while idx < len(subpartes):
                rotulo = subpartes[idx].strip()
                texto_sub = subpartes[idx+1].strip() if (idx+1) < len(subpartes) else ""
                bloco = f"{rotulo} {texto_sub}".strip()

                # Se o bloco ainda for longo, fraciona por frases/pontos
                if len(bloco) > 250:
                    frases = [f.strip() for f in re.split(r'\.\s+', bloco) if f.strip()]
                    for sub_idx, frase in enumerate(frases, 1):
                        txt_frase = frase if frase.endswith('.') else frase + '.'
                        unidades_finais.append((f"{num_art} - {rotulo} (parte {sub_idx})", txt_frase))
                else:
                    unidades_finais.append((f"{num_art} - {rotulo}", bloco))
                
                idx += 2
        else:
            # Se não tiver § nem incisos, mas for longo, quebra por frases
            if len(corpo) > 250:
                frases = [f.strip() for f in re.split(r'\.\s+', corpo) if f.strip()]
                for sub_idx, frase in enumerate(frases, 1):
                    txt_frase = frase if frase.endswith('.') else frase + '.'
                    unidades_finais.append((f"{num_art} (parte {sub_idx})", txt_frase))
            else:
                unidades_finais.append((num_art, corpo))

    # 3. Salva no banco de dados cada micro-trecho separado com seu caso prático
    conn = db()
    hoje = datetime.now().date().isoformat()
    for num, txt in unidades_finais:
        if txt.strip() and len(txt.strip()) > 10:
            exemplo = gerar_exemplo_pratico(txt)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO artigos(lei_id, numero, titulo, texto, caso_pratico) VALUES(?,?,?,?,?)",
                (law_id, num, num, txt.strip(), exemplo)
            )
            artigo_id = cursor.lastrowid
            
            # Agenda a primeira revisão
            conn.execute(
                "INSERT INTO revisoes(artigo_id, proxima_revisao, intervalo, repetition) VALUES(?,?,?,?)",
                (artigo_id, hoje, 1, 0)
            )
            
    conn.commit()
    conn.close()
    return len(unidades_finais)

# ==========================================
# 3. LÓGICA DE REVISÃO ESPAÇADA
# ==========================================

def record_answer(artigo_id, acertou, cycle=1):
    """Registra a resposta e calcula a próxima data de revisão."""
    conn = db()
    rev = conn.execute("SELECT * FROM revisoes WHERE artigo_id = ?", (artigo_id,)).fetchone()
    
    if rev:
        intervalo = rev["intervalo"]
        repetition = rev["repetition"]

        if acertou == 1:
            repetition += 1
            intervalo = intervalo * 2 if repetition > 1 else 1
        else:
            repetition = 0
            intervalo = 1

        proxima = (datetime.now().date() + timedelta(days=intervalo)).isoformat()

        conn.execute("""
            UPDATE revisoes 
            SET proxima_revisao = ?, intervalo = ?, repetition = ? 
            WHERE artigo_id = ?
        """, (proxima, intervalo, repetition, artigo_id))
        conn.commit()
    conn.close()
    return acertou == 1

def buscar_revisao_pendente():
    """Busca questões com revisão agendada para hoje ou atrasadas."""
    conn = db()
    hoje = datetime.now().date().isoformat()
    row = conn.execute("""
        SELECT a.id, a.numero, a.texto, a.caso_pratico 
        FROM artigos a
        JOIN revisoes r ON a.id = r.artigo_id
        WHERE r.proxima_revisao <= ?
        ORDER BY r.proxima_revisao ASC
        LIMIT 1
    """, (hoje,)).fetchone()
    conn.close()
    
    if row:
        return {
            "id": row["id"],
            "enunciado": f"**Dispositivo:** {row['numero']}\n\n**Texto da Norma:** {row['texto']}\n\n**Caso Prático:** {row['caso_pratico']}",
            "explicacao": f"Dispositivo legal: {row['numero']}\nTexto oficial: {row['texto']}"
        }
    return None

# ==========================================
# 4. INTERFACE STREAMLIT
# ==========================================

init_db()
st.set_page_config(page_title="Sistema de Legislação", layout="centered")

st.title("📚 Sistema de Questões e Revisão")

menu = st.sidebar.selectbox("Navegação", ["Praticar Questões", "Revisões Pendentes", "Importar PDF"])

if menu == "Importar PDF":
    st.header("📥 Importar Nova Lei (PDF)")
    nome_lei = st.text_input("Nome da Lei / Matéria:")
    uploaded_file = st.file_uploader("Escolha o ficheiro PDF", type=["pdf"])

    if st.button("Processar e Fracionar PDF"):
        if nome_lei and uploaded_file:
            conn = db()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO leis(nome) VALUES(?)", (nome_lei,))
            lei_id = cursor.lastrowid
            conn.commit()
            conn.close()

            total = parse_and_store_pdf(uploaded_file.read(), lei_id)
            st.success(f"✨ Sucesso! A lei foi dividida em {total} questões curtas e objetivas.")
        else:
            st.warning("Por favor, preencha o nome da lei e envie um ficheiro PDF.")

elif menu == "Praticar Questões":
    st.header("📝 Praticar Questões")
    conn = db()
    questoes = conn.execute("SELECT * FROM artigos ORDER BY id ASC").fetchall()
    conn.close()

    if "idx" not in st.session_state:
        st.session_state["idx"] = 0

    if questoes and st.session_state["idx"] < len(questoes):
        questao = questoes[st.session_state["idx"]]
        
        st.subheader(f"Questão {st.session_state['idx'] + 1} de {len(questoes)}")
        st.info(f"**Dispositivo:** {questao['numero']}")
        
        st.markdown(f"**De acordo com a legislação:**\n\n> \"{questao['texto']}\"")
        st.markdown(f"**Exemplo Prático:**\n\n_{questao['caso_pratico']}_")

        resp = st.radio("Sua resposta:", ["Certo", "Errado"], key=f"q_{questao['id']}")
        
        if st.button("Enviar Resposta"):
            gabarito = "Certo"
            acertou = (resp == gabarito)
            
            record_answer(questao['id'], 1 if acertou else 0, cycle=1)
            
            if acertou:
                st.success("✨ Resposta Correta!")
            else:
                st.error("❌ Resposta Incorreta!")

            if st.button("Próxima Questão ➔"):
                st.session_state["idx"] += 1
                st.rerun()
    elif questoes:
        st.success("🎉 Você concluiu todas as questões disponíveis!")
        if st.button("Reiniciar"):
            st.session_state["idx"] = 0
            st.rerun()
    else:
        st.info("Nenhuma questão disponível. Importe um PDF primeiro na aba 'Importar PDF'.")

elif menu == "Revisões Pendentes":
    st.header("🔄 Módulo de Revisão Espaçada")
    revs = buscar_revisao_pendente()

    if revs:
        st.subheader("Questão para Revisão")
        st.markdown(revs["enunciado"])
        resp_rev = st.radio("Sua resposta:", ["Certo", "Errado"], key="rev_ans")
        
        if st.button("Enviar Resposta da Revisão"):
            val = 1 if resp_rev == "Certo" else 0
            acertou = record_answer(revs["id"], val, cycle=2)
            
            if acertou:
                st.success("✨ Excelente! Próxima revisão agendada.")
            else:
                st.error("❌ Errou! Ela voltará para revisão em breve.")
                
            st.markdown(f"**Gabarito / Explicação:**\n\n{revs['explicacao']}")
            
            if st.button("Próxima Revisão ➔"):
                st.rerun()
    else:
        st.success("Tudo em dia! Não há revisões pendentes para hoje.")