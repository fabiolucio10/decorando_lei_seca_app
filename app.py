import hashlib
import html
import json
import os
import random
import re
import sqlite3
import logging
import textwrap
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    import pandas as pd
except ImportError:
    pd = None

import streamlit as st

try:
    import openai
except ImportError:
    openai = None

# Suporte ao SDK atualizado google-genai e ao legado google.generativeai
try:
    from google import genai
except ImportError:
    try:
        import google.generativeai as genai
    except ImportError:
        genai = None

APP_DIR = Path(__file__).parent
DB_FILE = APP_DIR / "decorando_lei.db"
PDF_DIR = APP_DIR / "leis_importadas"
PDF_DIR.mkdir(exist_ok=True)

# Definição do e-mail de administrador exclusivo
ADMIN_EMAIL = "fabiolucio277@gmail.com"

# Configuração da página - Mantém a barra lateral sempre expandida por padrão
st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização CSS aprimorada para justificar os textos e alinhar o layout em cartões modernos
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stAppDeployButton"] {display: none !important;}
    .viewerBadge_container__1S-xd {display: none !important;}
    [data-testid="stStatusWidget"] {display: none !important;}
    div[class*="stAppToolbar"] {display: none !important;}
    div[class*="viewerBadge"] {display: none !important;}
    div[class*="styles_viewerBadge"] {display: none !important;}
    button[title="Manage app"] {display: none !important;}
    button[title="Gerenciar aplicativo"] {display: none !important;}
    div[class^="stActionButton"] {display: none !important;}
    
    /* Garante alinhamento justificado e legibilidade perfeita dos enunciados e citações */
    .stMarkdown, p, div[data-testid="stMarkdownContainer"] {
        text-align: justify !important;
    }

    /* Garante que o botão de alternar/expandir a sidebar permaneça sempre visível */
    [data-testid="stSidebarCollapseButton"] {display: block !important; visibility: visible !important;}
    [data-testid="stHeader"] {background-color: transparent !important; z-index: 999;}

    /* ==================== CARTÕES DA QUESTÃO ==================== */
    .questao-estudo-wrapper { margin: 10px 0 18px 0; }
    .questao-ref-card {
        background: linear-gradient(135deg, #eff6ff, #f8fafc);
        border: 1px solid #bfdbfe;
        border-left: 5px solid #2563eb;
        border-radius: 12px;
        padding: 13px 16px;
        margin-bottom: 9px;
    }
    .questao-ref-label {
        color: #1d4ed8;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .5px;
        margin-bottom: 5px;
    }
    .questao-ref-text {
        color: #1e3a8a;
        font-size: 13.5px;
        line-height: 1.55;
        font-weight: 650;
    }
    .questao-comando-card {
        background: #f5f3ff;
        border: 1px solid #ddd6fe;
        border-left: 5px solid #7c3aed;
        border-radius: 12px;
        padding: 13px 16px;
        margin-bottom: 9px;
    }
    .questao-comando-label {
        color: #6d28d9;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .5px;
        margin-bottom: 5px;
    }
    .questao-comando-text {
        color: #4c1d95;
        font-size: 13.5px;
        line-height: 1.6;
        font-weight: 600;
    }
    .questao-assertiva-card {
        background: #ffffff;
        border: 2px solid #93c5fd;
        border-radius: 14px;
        padding: 18px 20px;
        box-shadow: 0 2px 8px rgba(30, 64, 175, .07);
    }
    .questao-assertiva-label {
        color: #0f766e;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .5px;
        margin-bottom: 8px;
    }
    .questao-assertiva-text {
        color: #172033;
        font-size: 17px;
        line-height: 1.7;
        font-weight: 650;
        text-align: left;
    }
        </style>
""", unsafe_allow_html=True)

# Regex universal para algarismos romanos de I até CCC (1 a 300+)
REGEX_ROMANO = r'(?=[MDCLXVI])M*(?:C[MD]|D?C{0,3})(?:X[CL]|L?X{0,3})(?:I[XV]|V?I{0,3})'

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def limpar_conteudo_html_para_renderizacao(conteudo):
    if conteudo is None:
        return ""
    texto = str(conteudo).strip()
    texto = re.sub(r"^\s*```(?:html|HTML)?\s*", "", texto)
    texto = re.sub(r"\s*```\s*$", "", texto)
    if "&lt;div" in texto or "&lt;style" in texto or "&gt;" in texto:
        texto = html.unescape(texto)
    return texto.strip()

def limpar_e_formatar_texto_lei(texto):
    if not texto:
        return ""
    padroes_remover = [
        r'\((?:Redação|Incluído|Vigência|Regulamento|Vide)\s+dada?\s+pel[ao][^)]*\)',
        r'\((?:Incluído|Restabelecido|Acrescido)\s+pel[ao][^)]*\)',
        r'https?://\S+',
        r'\b\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}\b',
        r'DEL\d+compilado',
        r'\b\d+/\d+\b'
    ]
    for padrao in padroes_remover:
        texto = re.sub(padrao, '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n\s*\n', '\n', texto)
    return texto.strip()

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        autorizado INTEGER DEFAULT 0,
        criado_em TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS disciplinas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS leis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        disciplina_id INTEGER NOT NULL,
        nome TEXT NOT NULL,
        arquivo TEXT,
        criado_em TEXT NOT NULL,
        FOREIGN KEY(disciplina_id) REFERENCES disciplinas(id)
    );

    CREATE TABLE IF NOT EXISTS artigos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lei_id INTEGER NOT NULL,
        numero TEXT NOT NULL,
        titulo TEXT,
        texto TEXT NOT NULL,
        FOREIGN KEY(lei_id) REFERENCES leis(id)
    );

    CREATE TABLE IF NOT EXISTS filtros_salvos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        nome TEXT NOT NULL,
        disciplina_id INTEGER NOT NULL,
        lei_id INTEGER NOT NULL,
        artigos_ids TEXT NOT NULL,
        qtd_questoes INTEGER NOT NULL,
        criado_em TEXT NOT NULL,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(disciplina_id) REFERENCES disciplinas(id),
        FOREIGN KEY(lei_id) REFERENCES leis(id)
    );

    CREATE TABLE IF NOT EXISTS questoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lei_id INTEGER NOT NULL,
        artigo_id INTEGER,
        disciplina_id INTEGER NOT NULL,
        filtro_id INTEGER,
        artigo_numero TEXT,
        conteudo TEXT,
        enunciado TEXT NOT NULL,
        gabarito INTEGER NOT NULL,
        explicacao TEXT,
        dificuldade TEXT DEFAULT 'Média',
        origem TEXT DEFAULT 'regra',
        criada_em TEXT NOT NULL,
        FOREIGN KEY(filtro_id) REFERENCES filtros_salvos(id)
    );

    CREATE TABLE IF NOT EXISTS respostas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        resposta INTEGER NOT NULL,
        acertou INTEGER NOT NULL,
        respondida_em TEXT NOT NULL,
        ciclo INTEGER NOT NULL,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(questao_id) REFERENCES questoes(id)
    );

    CREATE TABLE IF NOT EXISTS revisoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        prioridade INTEGER DEFAULT 1,
        proxima_revisao TEXT,
        erros INTEGER DEFAULT 0,
        acertos INTEGER DEFAULT 0,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(questao_id) REFERENCES questoes(id),
        UNIQUE(usuario_id, questao_id)
    );
    """)
    try:
        conn.execute("ALTER TABLE usuarios ADD COLUMN autorizado INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE usuarios SET autorizado = 1 WHERE LOWER(TRIM(username)) = ?", (ADMIN_EMAIL,))
    conn.commit()
    conn.close()

init_db()

def cadastrar_usuario(username, senha, autorizado=0):
    conn = db()
    u_clean = username.strip().lower()
    if u_clean == ADMIN_EMAIL:
        autorizado = 1
    else:
        autorizado = 0
    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (?, ?, ?, ?)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Cadastro realizado! Aguarde a liberação do administrador para acessar o sistema." if autorizado == 0 else "Utilizador criado e autorizado!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Nome de utilizador já existe!"

def autenticar_usuario(username, senha):
    conn = db()
    user = conn.execute(
        "SELECT * FROM usuarios WHERE username = ? AND senha = ?",
        (username.strip().lower(), hash_password(senha))
    ).fetchone()
    conn.close()
    return user

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["user_id"] = None
    st.session_state["username"] = None

if not st.session_state["logged_in"]:
    st.title("⚖ Decorando Lei Seca")
    tab_login, tab_cadastro = st.tabs(["🔑 Entrar", "📝 Criar Conta"])

    with tab_login:
        u = st.text_input("Utilizador / E-mail", key="login_user")
        p = st.text_input("Palavra-passe", type="password", key="login_pass")
        if st.button("Entrar", type="primary"):
            user = autenticar_usuario(u, p)
            if user:
                if user["autorizado"] == 1:
                    st.session_state["logged_in"] = True
                    st.session_state["user_id"] = user["id"]
                    st.session_state["username"] = user["username"]
                    st.success(f"Bem-vindo, {user['username']}!")
                    st.rerun()
                else:
                    st.warning("⚠️ A sua conta aguarda aprovação do administrador.")
            else:
                st.error("Utilizador ou palavra-passe incorretos.")

    with tab_cadastro:
        new_u = st.text_input("Escolha um Utilizador / E-mail", key="cad_user")
        new_p = st.text_input("Escolha uma Palavra-passe", type="password", key="cad_pass")
        if st.button("Cadastrar Conta"):
            if new_u and new_p:
                ok, msg = cadastrar_usuario(new_u, new_p, autorizado=0)
                if ok:
                    st.info(msg)
                else:
                    st.error(msg)
            else:
                st.warning("Preencha todos os campos.")
    st.stop()

USER_ID = st.session_state["user_id"]
USERNAME = st.session_state["username"]
is_admin_user = bool(USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL)

def get_disciplines():
    conn = db()
    rows = conn.execute("SELECT * FROM disciplinas ORDER BY nome").fetchall()
    conn.close()
    return rows

def get_laws(discipline_id=None):
    conn = db()
    if discipline_id:
        rows = conn.execute("""
            SELECT l.*, d.nome as disciplina_nome 
            FROM leis l 
            JOIN disciplinas d ON d.id = l.disciplina_id 
            WHERE l.disciplina_id=? 
            ORDER BY d.nome, l.nome
        """, (discipline_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT l.*, d.nome as disciplina_nome 
            FROM leis l 
            JOIN disciplinas d ON d.id = l.disciplina_id 
            ORDER BY d.nome, l.nome
        """).fetchall()
    conn.close()
    return rows

def renderizar_enunciado_estudo(enunciado, num_disp=None):
    if not enunciado:
        return
    texto = limpar_conteudo_html_para_renderizacao(enunciado)
    if "questao-comando-card" in texto or "questao-assertiva-card" in texto:
        ref_match = re.search(r'(?:Referência Normativa:\s*)(.*?)(?=<div\s+class=["\']questao-comando-card|$)', texto, flags=re.IGNORECASE | re.DOTALL)
        referencia = ref_match.group(1).strip() if ref_match else ""
        comando_match = re.search(r'<div\s+class=["\']questao-comando-text["\']\s*>(.*?)</div>', texto, flags=re.IGNORECASE | re.DOTALL)
        assertiva_match = re.search(r'<div\s+class=["\']questao-assertiva-text["\']\s*>(.*?)</div>', texto, flags=re.IGNORECASE | re.DOTALL)
        comando = html.unescape(re.sub(r'<[^>]+>', '', comando_match.group(1))) if comando_match else "À luz da literalidade da legislação e do dispositivo legal em exame, julgue o item a seguir:"
        assertiva = html.unescape(re.sub(r'<[^>]+>', '', assertiva_match.group(1))) if assertiva_match else ""
        referencia = html.unescape(re.sub(r'<[^>]+>', '', referencia))
    else:
        linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
        referencia = re.sub(r'\*\*', '', linhas[0]).strip() if linhas else ""
        m = re.search(r'(À luz da literalidade.*?)(?:\n\n|\n|$)', texto, flags=re.IGNORECASE | re.DOTALL)
        comando = re.sub(r'\s+', ' ', m.group(1)).strip() if m else "À luz da literalidade da legislação e do dispositivo legal em exame, julgue o item a seguir:"
        m_assertiva = re.search(r'>\s*["“](.*?)["”]\s*$', texto, flags=re.DOTALL)
        if m_assertiva:
            assertiva = m_assertiva.group(1).strip()
        else:
            partes = texto.split('\n\n')
            assertiva = partes[-1].strip().lstrip('> ').strip('"“”') if partes else texto

    referencia = html.escape(referencia.strip())
    comando = html.escape(comando.strip())
    assertiva = html.escape(assertiva.strip())

    html_enunciado = f"""
    <div class="questao-estudo-wrapper">
        <div class="questao-ref-card">
            <div class="questao-ref-label">📚 REFERÊNCIA NORMATIVA</div>
            <div class="questao-ref-text">{referencia}</div>
        </div>
        <div class="questao-comando-card">
            <div class="questao-comando-label">🎯 COMANDO DA QUESTÃO</div>
            <div class="questao-comando-text">{comando}</div>
        </div>
        <div class="questao-assertiva-card">
            <div class="questao-assertiva-label">⚖️ ITEM PARA JULGAMENTO</div>
            <div class="questao-assertiva-text">“{assertiva}”</div>
        </div>
    </div>
    """
    st.markdown(limpar_conteudo_html_para_renderizacao(textwrap.dedent(html_enunciado)), unsafe_allow_html=True)

# Menu Lateral e Navegação Principal do App
st.sidebar.title(f"👤 {USERNAME}")
if is_admin_user:
    st.sidebar.markdown("🔒 **Painel do Administrador**")

menu = st.sidebar.radio("Navegação", ["📖 Estudar / Questões", "⚙️ Gestão de Leis", "📊 Meu Desempenho"])

if menu == "📖 Estudar / Questões":
    st.title("📖 Sessão de Estudos - Lei Seca")
    st.info("Utilize os filtros ao lado ou selecione uma lei cadastrada para iniciar os seus estudos práticos com assertivas baseadas no padrão Cebraspe/FGV.")
    
    disciplinas = get_disciplines()
    if not disciplinas:
        st.warning("Nenhuma disciplina cadastrada. Acesse 'Gestão de Leis' para cadastrar disciplinas e leis.")
    else:
        disc_options = {d["nome"]: d["id"] for d in disciplinas}
        selected_disc_name = st.selectbox("Selecione a Disciplina", list(disc_options.keys()))
        disc_id = disc_options[selected_disc_name]
        
        leis = get_laws(disc_id)
        if not leis:
            st.warning("Nenhuma lei cadastrada para esta disciplina.")
        else:
            lei_options = {l["nome"]: l["id"] for l in leis}
            selected_lei_name = st.selectbox("Selecione a Lei / Norma", list(lei_options.keys()))
            st.success(f"Lei selecionada pronta para estudo: **{selected_lei_name}**")

elif menu == "⚙️ Gestão de Leis":
    st.title("⚙️ Gestão de Disciplinas e Leis")
    st.write("Aqui você pode cadastrar novas matérias, importar arquivos PDF de legislação e gerenciar o conteúdo.")
    
    with st.expander("➕ Cadastrar Nova Disciplina"):
        nova_disc = st.text_input("Nome da Disciplina")
        if st.button("Salvar Disciplina"):
            if nova_disc:
                conn = db()
                conn.execute("INSERT OR IGNORE INTO disciplinas(nome) VALUES(?)", (nova_disc.strip(),))
                conn.commit()
                conn.close()
                st.success(f"Disciplina '{nova_disc}' cadastrada com sucesso!")
                st.rerun()
            else:
                st.warning("Digite o nome da disciplina.")

elif menu == "📊 Meu Desempenho":
    st.title("📊 Painel de Desempenho")
    st.write("Acompanhe suas estatísticas de acertos, revisões e evolução no estudo da Lei Seca.")
    st.metric(label="Questões Respondidas", value="0")
    st.metric(label="Taxa de Acerto", value="0%")

if st.sidebar.button("🚪 Encerrar Sessão"):
    st.session_state["logged_in"] = False
    st.session_state["user_id"] = None
    st.session_state["username"] = None
    st.rerun()








