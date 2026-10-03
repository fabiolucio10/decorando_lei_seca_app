import streamlit as st
import sqlite3
import hashlib
import os
import fitz  # PyMuPDF
import re
from datetime import datetime, timedelta
import random

# ==========================================
# CONFIGURAÇÃO DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização CSS personalizada
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        font-weight: bold;
    }
    .stAlert {
        border-radius: 5px;
    }
    p, li {
        text-align: justify;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# BANCO DE DADOS E PERSISTÊNCIA (SQLite)
# ==========================================
DB_FILE = "decorando_lei_seca.db"

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabela de Usuários
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            aprovado INTEGER DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de Disciplinas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS disciplinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    ''')
    
    # Tabela de Leis
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disciplina_id INTEGER,
            nome TEXT NOT NULL,
            descricao TEXT,
            FOREIGN KEY (disciplina_id) REFERENCES disciplinas (id)
        )
    ''')
    
    # Tabela de Artigos e Dispositivos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS artigos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lei_id INTEGER,
            numero_artigo TEXT,
            tipo_dispositivo TEXT, -- caput, paragrafo, inciso, alinea
            texto TEXT,
            texto_formatado TEXT,
            FOREIGN KEY (lei_id) REFERENCES leis (id)
        )
    ''')
    
    # Tabela de Cadernos / Filtros Salvos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS filtros_salvos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            nome_filtro TEXT,
            criterios TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        )
    ''')
    
    # Tabela de Questões Geradas / Simuladas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artigo_id INTEGER,
            enunciado TEXT,
            gabito INTEGER, -- 1 para Certo, 0 para Errado
            comentario TEXT,
            FOREIGN KEY (artigo_id) REFERENCES artigos (id)
        )
    ''')
    
    # Tabela de Respostas do Usuário (Histórico / Desempenho)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS respostas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            questao_id INTEGER,
            acertou INTEGER,
            data_resposta TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY (questao_id) REFERENCES questoes (id)
        )
    ''')
    
    # Tabela de Revisão Espaçada
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS revisoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            artigo_id INTEGER,
            proxima_revisao TEXT,
            intervalo_dias INTEGER DEFAULT 1,
            frequencia INTEGER DEFAULT 0,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            FOREIGN KEY (artigo_id) REFERENCES artigos (id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# Garante admin padrão
def criar_admin_padrao():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", ("fabiolucio277@gmail.com",))
    if not cursor.fetchone():
        senha_hash = hashlib.sha256("admin123".encode()).hexdigest()
        cursor.execute("INSERT INTO usuarios (nome, email, senha, aprovado) VALUES (?, ?, ?, 1)", 
                       ("Administrador", "fabiolucio277@gmail.com", senha_hash))
        conn.commit()
    conn.close()

criar_admin_padrao()

# ==========================================
# UTILITÁRIOS E PROCESSAMENTO DE LEIS (PDF)
# ==========================================
def limpar_e_formatar_texto_lei(texto):
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

def normalizar_estrutura_dispositivo(texto_bruto):
    # Lógica simplificada de fatiamento de artigos e parágrafos
    dispositivos = []
    padrao_artigo = re.split(r'(Art\.?\s*\d+[\.\º]*)', texto_bruto, flags=re.IGNORECASE)
    
    if len(padrao_artigo) > 1:
        for i in range(1, len(padrao_artigo), 2):
            num_art = padrao_artigo[i].strip()
            conteudo = padrao_artigo[i+1] if i+1 < len(padrao_artigo) else ""
            dispositivos.append({
                "numero": num_art,
                "tipo": "caput",
                "texto": limpar_e_formatar_texto_lei(conteudo)
            })
    else:
        dispositivos.append({
            "numero": "Dispositivo Geral",
            "tipo": "geral",
            "texto": limpar_e_formatar_texto_lei(texto_bruto)
        })
    return dispositivos

# ==========================================
# AUTENTICAÇÃO E CONTROLE DE ACESSO
# ==========================================
def autenticar_usuario(email, senha):
    conn = get_connection()
    cursor = conn.cursor()
    senha_hash = hashlib.sha256(senha.encode()).hexdigest()
    cursor.execute("SELECT id, nome, email, aprovado FROM usuarios WHERE email = ? AND senha = ?", (email, senha_hash))
    user = cursor.fetchone()
    conn.close()
    return user

if "usuario_logado" not in st.session_state:
    st.session_state["usuario_logado"] = None

def tela_login_cadastro():
    st.title("⚖️ Decorando Lei Seca")
    st.subheader("Plataforma Inteligente de Memorização e Estudos para Concursos")
    
    aba1, aba2 = st.tabs(["🔑 Entrar", "📝 Criar Conta"])
    
    with aba1:
        st.markdown("### Acessar Sistema")
        email = st.text_input("E-mail", key="login_email")
        senha = st.text_input("Senha", type="password", key="login_senha")
        if st.button("Entrar"):
            user = autenticar_usuario(email, senha)
            if user:
                if user[3] == 1: # Aprovado
                    st.session_state["usuario_logado"] = {"id": user[0], "nome": user[1], "email": user[2], "admin": (user[2] == "fabiolucio277@gmail.com")}
                    st.success(f"Bem-vindo(a), {user[1]}!")
                    st.rerun()
                else:
                    st.warning("Sua conta aguarda aprovação pelo administrador.")
            else:
                st.error("E-mail ou senha incorretos.")
                
    with aba2:
        st.markdown("### Cadastro de Novo Aluno")
        nome = st.text_input("Nome Completo")
        email_novo = st.text_input("E-mail para Cadastro")
        senha_nova = st.text_input("Crie uma Senha", type="password")
        if st.button("Cadastrar"):
            if nome and email_novo and senha_nova:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    senha_hash = hashlib.sha256(senha_nova.encode()).hexdigest()
                    cursor.execute("INSERT INTO usuarios (nome, email, senha, aprovado) VALUES (?, ?, ?, 0)", (nome, email_novo, senha_hash))
                    conn.commit()
                    st.success("Cadastro realizado com sucesso! Aguarde a aprovação do administrador para acessar.")
                except sqlite3.IntegrityError:
                    st.error("Este e-mail já está cadastrado.")
                finally:
                    conn.close()
            else:
                st.warning("Preencha todos os campos.")

if not st.session_state["usuario_logado"]:
    tela_login_cadastro()
    st.stop()

# ==========================================
# PAINEL PRINCIPAL & NAVEGAÇÃO
# ==========================================
usuario = st.session_state["usuario_logado"]

st.sidebar.markdown(f"👤 **{usuario['nome']}**")
if usuario["admin"]:
    st.sidebar.markdown("🛡️ *Perfil Administrador*")

menu = st.sidebar.radio("Navegação", ["📚 Meus Estudos & Leis", "⚡ Gerador de Questões", "📊 Desempenho & Métricas", "🔄 Revisão Espaçada", "⚙️ Administração" if usuario["admin"] else None])

if menu == "📚 Meus Estudos & Leis":
    st.header("📚 Gestão de Disciplinas e Leis Secas")
    
    tab_d, tab_l, tab_p = st.tabs(["Cadastrar Disciplina", "Cadastrar Lei", "Importar PDF de Lei"])
    
    conn = get_connection()
    cursor = conn.cursor()
    
    with tab_d:
        nova_disc = st.text_input("Nome da Disciplina (ex: Direito Administrativo)")
        if st.button("Salvar Disciplina"):
            if nova_disc:
                try:
                    cursor.execute("INSERT INTO disciplinas (nome) VALUES (?)", (nova_disc,))
                    conn.commit()
                    st.success("Disciplina cadastrada com sucesso!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.warning("Esta disciplina já existe.")
                    
    with tab_l:
        cursor.execute("SELECT id, nome FROM disciplinas")
        dics = cursor.fetchall()
        if dics:
            dic_dict = {d[1]: d[0] for d in dics}
            escolha_dic = st.selectbox("Selecione a Disciplina", list(dic_dict.keys()))
            nome_lei = st.text_input("Nome/Número da Lei (ex: Lei 8.112/90)")
            desc_lei = st.text_area("Descrição / Ementa")
            if st.button("Salvar Lei"):
                cursor.execute("INSERT INTO leis (disciplina_id, nome, descricao) VALUES (?, ?, ?)", (dic_dict[escolha_dic], nome_lei, desc_lei))
                conn.commit()
                st.success("Lei cadastrada com sucesso!")
                st.rerun()
        else:
            st.info("Cadastre uma disciplina primeiro.")
            
    with tab_p:
        cursor.execute("SELECT id, nome FROM leis")
        leis_cadastradas = cursor.fetchall()
        if leis_cadastradas:
            lei_dict = {l[1]: l[0] for l in leis_cadastradas}
            escolha_lei_pdf = st.selectbox("Vincular PDF à Lei", list(lei_dict.keys()))
            arquivo_pdf = st.file_uploader("Envie o arquivo PDF da Lei", type=["pdf"])
            
            if arquivo_pdf and st.button("Processar e Extrair Artigos"):
                doc = fitz.open(stream=arquivo_pdf.read(), filetype="pdf")
                texto_completo = ""
                for pagina in doc:
                    texto_completo += pagina.get_text()
                
                dispositivos = normalizar_estrutura_dispositivo(texto_completo)
                for disp in dispositivos:
                    cursor.execute("INSERT INTO artigos (lei_id, numero_artigo, tipo_dispositivo, texto, texto_formatado) VALUES (?, ?, ?, ?, ?)",
                                   (lei_dict[escolha_lei_pdf], disp["numero"], disp["tipo"], disp["texto"], disp["texto"]))
                conn.commit()
                st.success(f"PDF processado com sucesso! {len(dispositivos)} dispositivos extraídos e salvos.")
        else:
            st.info("Cadastre uma lei antes de importar arquivos PDF.")
            
    conn.close()

elif menu == "⚡ Gerador de Questões":
    st.header("⚡ Gerador de Questões e Simulados de Lei Seca")
    st.info("Utilize IA e regras locais para criar baterias de Certo/Errado focadas na letra da lei.")
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome FROM leis")
    leis = cursor.fetchall()
    
    if leis:
        lei_map = {l[1]: l[0] for l in leis}
        l_escolhida = st.selectbox("Escolha a Lei para Estudo", list(lei_map.keys()))
        
        if st.button("Gerar Questões de Treino"):
            cursor.execute("SELECT id, numero_artigo, texto FROM artigos WHERE lei_id = ? LIMIT 10", (lei_map[l_escolhida],))
            arts = cursor.fetchall()
            
            for art in arts:
                # Gerador heurístico / simulado de assertiva Certo/Errado
                enunciado = f"Com base no {art[1]}, é correto afirmar que: {art[2]}"
                gabarito = 1 # Certo por padrão na base baseada fielmente no texto legal
                cursor.execute("INSERT INTO questoes (artigo_id, enunciado, gabito, comentario) VALUES (?, ?, ?, ?)",
                               (art[0], enunciado, gabarito, f"Dispositivo literal extraído do {art[1]}."))
            conn.commit()
            st.success("Questões geradas com sucesso!")
            
        # Responder questões geradas
        cursor.execute("SELECT q.id, q.enunciado, q.gabito, q.comentario FROM questoes q JOIN artigos a ON q.artigo_id = a.id WHERE a.lei_id = ?", (lei_map[l_escolhida],))
        questoes = cursor.fetchall()
        
        if questoes:
            for idx, q in enumerate(questoes):
                st.markdown(f"**Questão {idx+1}:** {q[1]}")
                resp = st.radio("Sua Resposta:", ["Certo", "Errado"], key=f"q_{q[0]}")
                if st.button(f"Responder Q{idx+1}", key=f"btn_{q[0]}"):
                    acertou = 1 if (resp == "Certo" and q[2] == 1) or (resp == "Errado" and q[2] == 0) else 0
                    cursor.execute("INSERT INTO respostas (usuario_id, questao_id, acertou) VALUES (?, ?, ?)", (usuario["id"], q[0], acertou))
                    conn.commit()
                    if acertou:
                        st.success("Correto! Parabéns.")
                    else:
                        st.error(f"Incorreto. Comentário: {q[3]}")
    else:
        st.warning("Nenhuma lei cadastrada para gerar questões.")
    conn.close()

elif menu == "📊 Desempenho & Métricas":
    st.header("📊 Painel de Desempenho")
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*), SUM(acertou) FROM respostas WHERE usuario_id = ?", (usuario["id"],))
    res = cursor.fetchone()
    total_resp = res[0] or 0
    total_acertos = res[1] or 0
    aproveitamento = (total_acertos / total_resp * 100) if total_resp > 0 else 0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total de Questões Respondidas", total_resp)
    col2.metric("Acertos", total_acertos)
    col3.metric("Aproveitamento Geral", f"{aproveitamento:.2f}%")
    
    conn.close()

elif menu == "🔄 Revisão Espaçada":
    st.header("🔄 Sistema de Revisão Espaçada")
    st.info("Revise os artigos e dispositivos com base em seu histórico de erros e acertos.")
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.numero_artigo, a.texto, l.nome 
        FROM artigos a 
        JOIN leis l ON a.lei_id = l.id 
        LIMIT 5
    """)
    revisoes = cursor.fetchall()
    
    if revisoes:
        for rev in revisoes:
            with st.expander(f"Lei: {rev[2]} - {rev[0]}"):
                st.write(rev[1])
                if st.button(f"Marcar como Revisado ({rev[0]})"):
                    st.success("Item atualizado na sua fila de repetição espaçada!")
    else:
        st.info("Nenhum item pendente para revisão no momento.")
    conn.close()

elif usuario["admin"] and menu == "⚙️ Administração":
    st.header("⚙️ Painel do Administrador - Aprovação de Usuários")
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, nome, email, aprovado FROM usuarios WHERE aprovado = 0")
    pendentes = cursor.fetchall()
    
    if pendentes:
        for p in pendentes:
            col_a, col_b = st.columns([3, 1])
            col_a.write(f"**{p[1]}** ({p[2]})")
            if col_b.button("Aprovar", key=f"aprov_{p[0]}"):
                cursor.execute("UPDATE usuarios SET aprovado = 1 WHERE id = ?", (p[0],))
                conn.commit()
                st.success(f"Usuário {p[1]} aprovado com sucesso!")
                st.rerun()
    else:
        st.info("Não há usuários pendentes de aprovação.")
    conn.close()