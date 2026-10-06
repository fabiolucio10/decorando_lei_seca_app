import hashlib
import json
import os
import random
import re
import sqlite3
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

try:
    import openai
except ImportError:
    openai = None

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

ADMIN_EMAIL = "fabiolucio277@gmail.com"

st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
    
    .stMarkdown, p, div[data-testid="stMarkdownContainer"] {
        text-align: justify !important;
    }

    [data-testid="stSidebarCollapseButton"] {display: block !important; visibility: visible !important;}
    [data-testid="stHeader"] {background-color: transparent !important; z-index: 999;}
    </style>
""", unsafe_allow_html=True)

REGEX_ROMANO = r'(?:M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{1,3}))'

# ==============================================================================
# CONEXÃO HÍBRIDA SUPABASE (POSTGRESQL) / SQLITE LOCAL
# ==============================================================================
class PostgresCursorWrapper:
    """Wrapper para adaptar consultas SQLite para o PostgreSQL do Supabase"""
    def __init__(self, conn, cursor):
        self.conn = conn
        self.cursor = cursor

    def execute(self, query, params=None):
        if params:
            query_pg = query.replace('?', '%s')
            if "INSERT OR IGNORE" in query_pg:
                query_pg = query_pg.replace("INSERT OR IGNORE", "INSERT INTO").replace("VALUES", "ON CONFLICT DO NOTHING VALUES")
            self.cursor.execute(query_pg, params)
        else:
            self.cursor.execute(query)
        return self

    def executemany(self, query, seq_params):
        query_pg = query.replace('?', '%s')
        self.cursor.executemany(query_pg, seq_params)
        return self

    def executescript(self, script_sql):
        script_pg = script_sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        script_pg = script_pg.replace("UNIQUE(usuario_id, questao_id)", "CONSTRAINT unique_user_quest UNIQUE(usuario_id, questao_id)")
        self.cursor.execute(script_pg)
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        colnames = [desc[0] for desc in self.cursor.description]
        return {colnames[i]: row[i] for i in range(len(row))}

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return rows
        colnames = [desc[0] for desc in self.cursor.description]
        return [{colnames[i]: r[i] for i in range(len(r))} for r in rows]

    @property
    def lastrowid(self):
        try:
            return self.cursor.fetchone()[0]
        except Exception:
            return None

class PostgresConnWrapper:
    def __init__(self, pg_conn):
        self.pg_conn = pg_conn

    def cursor(self):
        cur = self.pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return PostgresCursorWrapper(self, cur)

    def execute(self, query, params=None):
        cur = self.cursor()
        return cur.execute(query, params)

    def executemany(self, query, seq_params):
        cur = self.cursor()
        return cur.executemany(query, seq_params)

    def executescript(self, script_sql):
        cur = self.cursor()
        return cur.executescript(script_sql)

    def commit(self):
        self.pg_conn.commit()

    def close(self):
        self.pg_conn.close()

def db():
    database_url = os.getenv("DATABASE_URL")
    try:
        if "DATABASE_URL" in st.secrets:
            database_url = st.secrets["DATABASE_URL"]
    except Exception:
        pass

    if database_url and psycopg2:
        try:
            pg_conn = psycopg2.connect(database_url)
            return PostgresConnWrapper(pg_conn)
        except Exception as e:
            logging.warning(f"Erro ao conectar no Supabase Postgres: {e}. Usando SQLite local.")

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def limpar_e_formatar_texto_lei(texto):
    if not texto: return ""
    padroes_remover = [
        r'\((?:Redação\vert{}Incluído\vert{}Vigência\vert{}Regulamento\vert{}Vide)\s+dada?\s+pel[ao][^)]*\)',
        r'\((?:Incluído\vert{}Restabelecido\vert{}Acrescido)\s+pel[ao][^)]*\)',
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
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL,
        autorizado INTEGER DEFAULT 0,
        criado_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS disciplinas (
        id SERIAL PRIMARY KEY,
        nome TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS leis (
        id SERIAL PRIMARY KEY,
        disciplina_id INTEGER NOT NULL,
        nome TEXT NOT NULL,
        arquivo TEXT,
        criado_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS artigos (
        id SERIAL PRIMARY KEY,
        lei_id INTEGER NOT NULL,
        numero TEXT NOT NULL,
        titulo TEXT,
        texto TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS filtros_salvos (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER,
        nome TEXT NOT NULL,
        disciplina_id INTEGER NOT NULL,
        lei_id INTEGER NOT NULL,
        artigos_ids TEXT NOT NULL,
        qtd_questoes INTEGER NOT NULL,
        criado_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS questoes (
        id SERIAL PRIMARY KEY,
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
        criada_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS respostas (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        resposta INTEGER NOT NULL,
        acertou INTEGER NOT NULL,
        respondida_em TEXT NOT NULL,
        ciclo INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS revisoes (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER,
        questao_id INTEGER NOT NULL,
        prioridade INTEGER DEFAULT 1,
        proxima_revisao TEXT,
        erros INTEGER DEFAULT 0,
        acertos INTEGER DEFAULT 0
    );
    """)
    conn.commit()
    conn.close()

init_db()

def cadastrar_usuario(username, senha, autorizado=0):
    conn = db()
    u_clean = username.strip().lower()
    autorizado = 1 if u_clean == ADMIN_EMAIL else 0
    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (?, ?, ?, ?)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Cadastro realizado com sucesso!" if autorizado == 1 else "Cadastro realizado! Aguarde a liberação do administrador."
    except Exception:
        conn.close()
        return False, "Nome de utilizador já existe!"

def alterar_status_autorizacao(user_id, status):
    conn = db()
    conn.execute("UPDATE usuarios SET autorizado = ? WHERE id = ?", (status, user_id))
    conn.commit()
    conn.close()

def excluir_usuario(user_id):
    conn = db()
    conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

def listar_usuarios():
    conn = db()
    users = conn.execute("SELECT id, username, autorizado, criado_em FROM usuarios ORDER BY id").fetchall()
    conn.close()
    return users

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
                if ok: st.info(msg)
                else: st.error(msg)
            else:
                st.warning("Preencha todos os campos.")
    st.stop()

USER_ID = st.session_state["user_id"]
USERNAME = st.session_state["username"]
is_admin_user = bool(USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL)

def add_discipline(name):
    conn = db()
    try:
        conn.execute("INSERT INTO disciplinas(nome) VALUES(?) ON CONFLICT (nome) DO NOTHING", (name.strip(),))
    except Exception:
        conn.execute("INSERT INTO disciplinas(nome) VALUES(?)", (name.strip(),))
    conn.commit()
    conn.close()

def get_disciplines():
    conn = db()
    rows = conn.execute("SELECT * FROM disciplinas ORDER BY nome").fetchall()
    conn.close()
    return rows

def add_law(discipline_id, name, filename):
    conn = db()
    cur = conn.execute(
        "INSERT INTO leis(disciplina_id, nome, arquivo, criado_em) VALUES(?,?,?,?) RETURNING id",
        (discipline_id, name.strip(), filename, datetime.now().isoformat())
    )
    row = cur.fetchone()
    law_id = row["id"] if isinstance(row, dict) else row[0]
    conn.commit()
    conn.close()
    return law_id

def delete_law(law_id):
    conn = db()
    conn.execute("DELETE FROM artigos WHERE lei_id = ?", (law_id,))
    conn.execute("DELETE FROM leis WHERE id = ?", (law_id,))
    conn.commit()
    conn.close()

def get_laws(discipline_id=None):
    conn = db()
    if discipline_id:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id WHERE l.disciplina_id=? ORDER BY l.nome", (discipline_id,)).fetchall()
    else:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id ORDER BY l.nome").fetchall()
    conn.close()
    return rows

def parse_and_store_pdf(pdf_path, law_id):
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()
    artigo_regex = re.compile(r'(?m)^(Art\.\s*\d+[\w\-]*[\.\º\ª]?)', re.IGNORECASE)
    partes = artigo_regex.split(full_text)
    conn = db()
    quantidade = 0
    if len(partes) > 1:
        for i in range(1, len(partes), 2):
            num_art = partes[i].strip()
            corpo_limpo = limpar_e_formatar_texto_lei(partes[i + 1] if (i + 1) < len(partes) else "")
            if corpo_limpo and len(corpo_limpo) > 10:
                conn.execute("INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)", (law_id, num_art, num_art, corpo_limpo))
                quantidade += 1
    conn.commit()
    conn.close()
    return quantidade

def get_articles(law_id):
    conn = db()
    rows = conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()
    conn.close()
    return rows

def save_filter(name, discipline_id, law_id, article_ids, qtd_questoes):
    conn = db()
    art_str = ",".join(map(str, article_ids))
    cur = conn.execute("""
        INSERT INTO filtros_salvos (usuario_id, nome, disciplina_id, lei_id, artigos_ids, qtd_questoes, criado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
    """, (USER_ID, name, discipline_id, law_id, art_str, qtd_questoes, datetime.now().isoformat()))
    row = cur.fetchone()
    filter_id = row["id"] if isinstance(row, dict) else row[0]
    conn.commit()
    conn.close()
    return filter_id

def delete_filter(filter_id):
    conn = db()
    conn.execute("DELETE FROM questoes WHERE filtro_id = ?", (filter_id,))
    conn.execute("DELETE FROM filtros_salvos WHERE id = ? AND usuario_id = ?", (filter_id, USER_ID))
    conn.commit()
    conn.close()

def get_saved_filters(discipline_id=None):
    conn = db()
    if discipline_id:
        rows = conn.execute("SELECT f.*, d.nome disciplina, l.nome lei FROM filtros_salvos f JOIN disciplinas d ON d.id = f.disciplina_id JOIN leis l ON l.id = f.lei_id WHERE f.usuario_id = ? AND f.disciplina_id = ? ORDER BY f.id DESC", (USER_ID, discipline_id)).fetchall()
    else:
        rows = conn.execute("SELECT f.*, d.nome disciplina, l.nome lei FROM filtros_salvos f JOIN disciplinas d ON d.id = f.disciplina_id JOIN leis l ON l.id = f.lei_id WHERE f.usuario_id = ? ORDER BY f.id DESC", (USER_ID,)).fetchall()
    conn.close()
    return rows

def record_answer(question_id, answer, cycle):
    conn = db()
    q = conn.execute("SELECT * FROM questoes WHERE id=?", (question_id,)).fetchone()
    correct = int(answer == q["gabarito"])
    conn.execute("INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo) VALUES(?,?,?,?,?,?)",
                 (USER_ID, question_id, answer, correct, datetime.now().isoformat(), cycle))
    conn.commit()
    conn.close()
    return correct

def zerar_historico_dashboard():
    conn = db()
    conn.execute("DELETE FROM respostas WHERE usuario_id = ?", (USER_ID,))
    conn.execute("DELETE FROM revisoes WHERE usuario_id = ?", (USER_ID,))
    conn.commit()
    conn.close()

def stats():
    conn = db()
    total = conn.execute("SELECT COUNT(*) n FROM respostas WHERE usuario_id=?", (USER_ID,)).fetchone()["n"]
    hits = conn.execute("SELECT COALESCE(SUM(acertou),0) n FROM respostas WHERE usuario_id=?", (USER_ID,)).fetchone()["n"]
    errors = total - hits
    pct = (hits / total * 100) if total else 0
    
    is_postgres = hasattr(conn, 'pg_conn')
    
    q_disc = """
        SELECT d.nome AS disciplina, COUNT(r.id) AS respondidas, COALESCE(SUM(r.acertou),0) AS acertos 
        FROM respostas r 
        JOIN questoes q ON q.id=r.questao_id 
        JOIN disciplinas d ON d.id=q.disciplina_id 
        WHERE r.usuario_id = ? 
        GROUP BY d.id, d.nome
    """
    q_filt = """
        SELECT f.nome AS filtro, COUNT(r.id) AS respondidas 
        FROM respostas r 
        JOIN questoes q ON q.id=r.questao_id 
        JOIN filtros_salvos f ON f.id=q.filtro_id 
        WHERE r.usuario_id = ? 
        GROUP BY f.id, f.nome
    """
    
    if is_postgres:
        q_disc = q_disc.replace('?', '%s')
        q_filt = q_filt.replace('?', '%s')
        b_disc = pd.read_sql_query(q_disc, conn.pg_conn, params=(USER_ID,)) if pd else None
        b_filt = pd.read_sql_query(q_filt, conn.pg_conn, params=(USER_ID,)) if pd else None
    else:
        b_disc = pd.read_sql_query(q_disc, conn, params=(USER_ID,)) if pd else None
        b_filt = pd.read_sql_query(q_filt, conn, params=(USER_ID,)) if pd else None

    due = conn.execute("SELECT COUNT(*) n FROM revisoes WHERE usuario_id = ? AND proxima_revisao <= ?", (USER_ID, datetime.now().isoformat())).fetchone()["n"]
    conn.close()
    return total, hits, errors, pct, b_disc, b_filt, due

with st.sidebar:
    st.markdown(f"👤 Utilizador: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state.clear()
        st.rerun()
    st.divider()
    if is_admin_user:
        st.subheader("⚙ Painel Admin")
        for u in listar_usuarios():
            st.write(f"**{u['username']}**")
            if u['username'].strip().lower() != ADMIN_EMAIL:
                if st.button(f"Excluir {u['username']}", key=f"del_u_{u['id']}"):
                    excluir_usuario(u['id'])
                    st.rerun()

st.title("⚖ Decorando Lei Seca")

if is_admin_user:
    tab1, tab2, tab3, tab4, tab5, tab_admin = st.tabs(["📚 Importar Leis", "🎯 Criar Caderno", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões", "🛡 Painel Admin"])
else:
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📚 Importar Leis", "🎯 Criar Caderno", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões"])

with tab1:
    st.header("Importar Nova Lei (PDF)")
    discs = get_disciplines()
    disc_names = [d["nome"] for d in discs]
    col1, col2 = st.columns(2)
    with col1:
        new_disc = st.text_input("Nova Disciplina:")
        if st.button("Cadastrar Disciplina"):
            if new_disc:
                add_discipline(new_disc)
                st.success(f"Disciplina '{new_disc}' cadastrada!")
                st.rerun()
    with col2:
        disc_sel = st.selectbox("Selecione a Disciplina:", [""] + disc_names)
    law_title = st.text_input("Nome da Lei:")
    uploaded_file = st.file_uploader("Ficheiro PDF", type=["pdf"])
    if st.button("Processar e Salvar Lei"):
        if disc_sel and law_title and uploaded_file:
            d_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            file_path = PDF_DIR / uploaded_file.name
            with open(file_path, "wb") as f: f.write(uploaded_file.getbuffer())
            law_id = add_law(d_id, law_title, uploaded_file.name)
            qtd = parse_and_store_pdf(file_path, law_id)
            st.success(f"Lei processada! {qtd} artigos importados.")

with tab2:
    st.header("Criar Caderno de Questões por Filtro")
    discs = get_disciplines()
    disc_dict = {d["nome"]: d["id"] for d in discs}
    disc_f = st.selectbox("Disciplina:", [""] + list(disc_dict.keys()), key="cb_disc")
    
    if disc_f:
        d_id = disc_dict[disc_f]
        laws = get_laws(d_id)
        law_dict = {l["nome"]: l["id"] for l in laws}
        law_f = st.selectbox("Lei:", [""] + list(law_dict.keys()), key="cb_law")
        
        if law_f:
            l_id = law_dict[law_f]
            articles = get_articles(l_id)
            art_dict = {f"{a['numero']} - {a['texto'][:50]}...": a["id"] for a in articles}
            selected_arts = st.multiselect("Artigos (vazio para todos):", list(art_dict.keys()))
            qtd_q = st.number_input("Quantidade de Questões:", min_value=1, value=10)
            filter_name = st.text_input("Nome do Caderno / Filtro:")
            
            if st.button("Salvar Caderno e Gerar Questões", type="primary"):
                if filter_name:
                    art_ids = [art_dict[k] for k in selected_arts] if selected_arts else [a["id"] for a in articles]
                    f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                    conn = db()
                    for aid in art_ids[:qtd_q]:
                        art_row = conn.execute("SELECT * FROM artigos WHERE id=?", (aid,)).fetchone()
                        if art_row:
                            conn.execute("""
                                INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, criada_em)
                                VALUES(?,?,?,?,?,?,?,?,?,?)
                            """, (l_id, aid, d_id, f_id, art_row["numero"], art_row["numero"], f"De acordo com o **{art_row['numero']}**:\n\n\"{art_row['texto']}\"", 1, "Dispositivo correto conforme a literalidade da lei.", datetime.now().isoformat()))
                    conn.commit()
                    conn.close()
                    st.success(f"Caderno '{filter_name}' criado com sucesso!")

with tab3:
    st.header("Resolver Questões")
    saved_filters = get_saved_filters()
    if not saved_filters:
        st.info("Nenhum caderno criado ainda.")
    else:
        filter_map = {f"{f['nome']} ({f['disciplina']} - {f['lei']})": f["id"] for f in saved_filters}
        sel_f_label = st.selectbox("Escolha o Caderno:", list(filter_map.keys()))
        f_id = filter_map[sel_f_label]
        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=?", (f_id,)).fetchall()
        conn.close()
        if not questoes:
            st.warning("Este caderno não possui questões.")
        else:
            if "q_idx" not in st.session_state: st.session_state["q_idx"] = 0
            idx = st.session_state["q_idx"]
            if idx >= len(questoes):
                st.success("Concluiu todas as questões deste caderno!")
                if st.button("Recomeçar"):
                    st.session_state["q_idx"] = 0
                    st.rerun()
            else:
                q = questoes[idx]
                st.markdown(f"**Dispositivo:** `{q['artigo_numero']}`")
                st.markdown(q["enunciado"])
                resp = st.radio("Sua resposta:", ["Certo", "Errado"], key=f"ans_{q['id']}")
                if st.button("Responder", type="primary"):
                    val = 1 if resp == "Certo" else 0
                    acertou = record_answer(q["id"], val, cycle=1)
                    if acertou: st.success("✨ Correto!")
                    else: st.error("❌ Incorreto!")
                    st.markdown(q["explicacao"], unsafe_allow_html=True)
                    if st.button("Próxima Questão ➡️"):
                        st.session_state["q_idx"] += 1
                        st.rerun()

with tab4:
    st.header("Seu Desempenho")
    tot, ac, err, pct, b_disc, b_filt, due = stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Respondidas", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")
    if st.button("Zerar Histórico"):
        zerar_historico_dashboard()
        st.success("Histórico zerado!")
        st.rerun()

with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, due = stats()
    st.metric("Questões Pendentes", due)
    st.info("Utilize os cadernos para alimentar suas revisões.")

if is_admin_user:
    with tab_admin:
        st.header("🛡 Painel Admin")
        for u in listar_usuarios():
            st.write(f"Utilizador: {u['username']} | Autorizado: {u['autorizado']}")