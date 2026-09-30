import hashlib
import json
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st

try:
    import openai
except ImportError:
    openai = None

APP_DIR = Path(__file__).parent
DB_FILE = APP_DIR / "decorando_lei.db"
PDF_DIR = APP_DIR / "leis_importadas"
PDF_DIR.mkdir(exist_ok=True)

# Configuração da página
st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖",
    layout="wide"
)

# Estilização CSS para ocultar menus e cabeçalhos
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
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
    .stApp > header + div {padding-top: 0rem;}
    section[data-testid="stSidebar"] + div {padding-top: 0rem;}
    </style>
""", unsafe_allow_html=True)

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def limpar_e_formatar_texto_lei(texto):
    """
    Remove notas de alteração/inclusão legislativa, URLs, datas e quebras excessivas.
    """
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

    texto = re.sub(r'\r\n|\r|\n', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto)

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

    conn.execute("UPDATE usuarios SET autorizado = 1 WHERE LOWER(username) = 'fabiolucio277@gmail.com'")
    conn.commit()
    conn.close()

init_db()

def cadastrar_usuario(username, senha, autorizado=0):
    conn = db()
    u_clean = username.strip().lower()
    if u_clean == "fabiolucio277@gmail.com":
        autorizado = 1
    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (?, ?, ?, ?)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Cadastro realizado! Aguarde a liberação do administrador." if autorizado == 0 else "Usuário criado e autorizado!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Nome de usuário já existe!"

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
        u = st.text_input("Usuário / E-mail", key="login_user")
        p = st.text_input("Senha", type="password", key="login_pass")
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
                    st.warning("⚠️ Sua conta aguarda aprovação do administrador.")
            else:
                st.error("Usuário ou senha incorretos.")

    with tab_cadastro:
        new_u = st.text_input("Escolha um Usuário / E-mail", key="cad_user")
        new_p = st.text_input("Escolha uma Senha", type="password", key="cad_pass")
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

with st.sidebar:
    st.markdown(f"👤 Usuário: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()
    st.divider()

    if USERNAME.lower() == "fabiolucio277@gmail.com":
        st.subheader("⚙️ Painel do Administrador")
        with st.expander("👥 Gerenciar Usuários", expanded=False):
            usuarios_cadastrados = listar_usuarios()
            for u in usuarios_cadastrados:
                st.markdown(f"**{u['username']}**")
                c_status, c_del = st.columns([3, 1])
                is_admin = u['username'].lower() == "fabiolucio277@gmail.com"
                if is_admin:
                    c_status.caption("👑 Administrador Principal")
                else:
                    status_atual = bool(u['autorizado'])
                    novo_status = c_status.toggle("Autorizado", value=status_atual, key=f"aut_{u['id']}")
                    if novo_status != status_atual:
                        alterar_status_autorizacao(u['id'], 1 if novo_status else 0)
                        st.toast(f"Status alterado!")
                        st.rerun()

                    if c_del.button("❌", key=f"del_user_{u['id']}"):
                        excluir_usuario(u['id'])
                        st.rerun()
                st.divider()

def add_discipline(name):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO disciplinas(nome) VALUES(?)", (name.strip(),))
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
        "INSERT INTO leis(disciplina_id, nome, arquivo, criado_em) VALUES(?,?,?,?)",
        (discipline_id, name.strip(), filename, datetime.now().isoformat())
    )
    law_id = cur.lastrowid
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
        rows = conn.execute("SELECT * FROM leis WHERE disciplina_id=? ORDER BY nome", (discipline_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leis ORDER BY nome").fetchall()
    conn.close()
    return rows

def parse_and_store_pdf(pdf_path, law_id):
    """
    Leitura inteligente de PDF com fatiamento avançado:
    Garante enunciados curtos cortando por Parágrafos (§), Incisos e Frases.
    """
    doc = fitz.open(pdf_path)
    full_text = " ".join([page.get_text() for page in doc])
    doc.close()

    full_text = limpar_e_formatar_texto_lei(full_text)

    # Separar por Artigos (ex: Art. 1º, Art. 14-A)
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

        # Procura subdivisiones: Parágrafos (§ ou Parágrafo único), Incisos e Alíneas
        padrao_subdivisao = re.compile(r'(§\s*\d+º?|Parágrafo\s+único|[I|V|X]+\s*-|[a-z]\))', re.IGNORECASE)
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

                # Se a frase ainda passar de 200 caracteres, divide em frases/pontos
                if len(bloco) > 200:
                    frases = [f.strip() for f in re.split(r'\.\s+', bloco) if f.strip()]
                    for sub_idx, frase in enumerate(frases, 1):
                        txt_frase = frase if frase.endswith('.') else frase + '.'
                        unidades_finais.append((f"{num_art} - {rotulo} (parte {sub_idx})", txt_frase))
                else:
                    unidades_finais.append((f"{num_art} - {rotulo}", bloco))
                
                idx += 2
        else:
            if len(corpo) > 200:
                frases = [f.strip() for f in re.split(r'\.\s+', corpo) if f.strip()]
                for sub_idx, frase in enumerate(frases, 1):
                    txt_frase = frase if frase.endswith('.') else frase + '.'
                    unidades_finais.append((f"{num_art} (parte {sub_idx})", txt_frase))
            else:
                unidades_finais.append((num_art, corpo))

    conn = db()
    for num, txt in unidades_finais:
        if txt.strip() and len(txt.strip()) > 10:
            conn.execute(
                "INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)",
                (law_id, num, num, txt.strip())
            )
    conn.commit()
    conn.close()
    return len(unidades_finais)

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
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (USER_ID, name, discipline_id, law_id, art_str, qtd_questoes, datetime.now().isoformat()))
    filter_id = cur.lastrowid
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
        rows = conn.execute("""
            SELECT f.*, d.nome disciplina, l.nome lei
            FROM filtros_salvos f
            JOIN disciplinas d ON d.id = f.disciplina_id
            JOIN leis l ON l.id = f.lei_id
            WHERE f.usuario_id = ? AND f.disciplina_id = ?
            ORDER BY d.nome, f.id DESC
        """, (USER_ID, discipline_id)).fetchall()
    else:
        rows = conn.execute("""
            SELECT f.*, d.nome disciplina, l.nome lei
            FROM filtros_salvos f
            JOIN disciplinas d ON d.id = f.disciplina_id
            JOIN leis l ON l.id = f.lei_id
            WHERE f.usuario_id = ?
            ORDER BY d.nome, f.id DESC
        """, (USER_ID,)).fetchall()
    conn.close()
    return rows

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de obrigação ("deverá") por faculdade ("poderá")'),
        (r'\bpoderá\b', 'deverá', 'troca de faculdade ("poderá") por obrigação ("deverá")'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração de prazo legal de 24h para 48h'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão'),
        (r'\bobrigatório\b', 'facultativo', 'troca de obrigação por faculdade')
    ]
    
    texto_modificado = texto
    tipo_troca = None
    
    for padrao, sub, descricao in substituicoes:
        if re.search(padrao, texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = descricao
            break
            
    if not tipo_troca:
        if " não " in texto_modificado:
            texto_modificado = texto_modificado.replace(" não ", " ", 1)
            tipo_troca = 'supressão da negação "não"'
        else:
            words = texto_modificado.split()
            if len(words) > 3:
                words.insert(3, "não")
                texto_modificado = " ".join(words)
                tipo_troca = 'inserção indevida da negação "não"'

    return texto_modificado, tipo_troca

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, texto_modificado=None):
    if foi_correto:
        status_txt = "O item está **CORRETO**."
        detalhe_erro = f"O enunciado reproduz exatamente o disposto no **{art_num}**."
        resumo_erro_bloco = ""
    else:
        status_txt = "O item está **ERRADO**."
        detalhe_erro = f"A regra original foi modificada."
        resumo_erro_bloco = f"\n• **Erro da Questão:** Alteração do sentido por **{tipo_troca or 'modificação de termos'}**."

    return f"""💡 **Explicação Direta:**
{status_txt} {detalhe_erro}{resumo_erro_bloco}

📜 **Texto Oficial:**
> "{texto_original}"
"""

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="⚙️ Regra Padrão"):
    conn = db()
    if article_ids:
        placeholders = ",".join("?" * len(article_ids))
        arts = conn.execute(f"SELECT * FROM artigos WHERE id IN ({placeholders}) ORDER BY id", article_ids).fetchall()
    else:
        arts = conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()

    if not arts:
        conn.close()
        return 0

    generated = 0
    now = datetime.now().isoformat()
    artigos_pool = list(arts)
    random.shuffle(artigos_pool)

    for i in range(qtd_total):
        art = artigos_pool[i % len(artigos_pool)]
        text = limpar_e_formatar_texto_lei(art["texto"])
        is_correct = random.choice([True, False])

        if is_correct:
            enunciado = f"De acordo com o {art['numero']}:\n\n\"{text}\""
            gabarito = 1
            explicacao = gerar_explicacao_humana(art['numero'], text, True)
        else:
            modified_text, tipo_troca = alterar_texto_para_errado(text)
            enunciado = f"De acordo com a legislação:\n\n\"{modified_text}\""
            gabarito = 0
            explicacao = gerar_explicacao_humana(art['numero'], text, False, tipo_troca, modified_text)

        conn.execute("""
            INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (law_id, art["id"], discipline_id, filter_id, art["numero"], art["numero"], enunciado, gabarito, explicacao, motor_ia, now))
        generated += 1

    conn.commit()
    conn.close()
    return generated

def record_answer(question_id, answer, cycle):
    conn = db()
    q = conn.execute("SELECT * FROM questoes WHERE id=?", (question_id,)).fetchone()
    correct = int(answer == q["gabarito"])
    now = datetime.now()
    conn.execute("""
        INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo)
        VALUES(?, ?, ?, ?, ?, ?)
    """, (USER_ID, question_id, answer, correct, now.isoformat(), cycle))

    old = conn.execute("SELECT * FROM revisoes WHERE usuario_id=? AND questao_id=?", (USER_ID, question_id)).fetchone()
    hits = (old["acertos"] + 1) if old and correct else (1 if correct else 0)
    errors = (old["erros"] + 1) if old and not correct else (0 if correct else 1)
    
    priority = min(10, (old["prioridade"] if old else 1) + 2) if not correct else max(0, (old["prioridade"] if old else 1) - 1)
    intervals = [1, 3, 7, 15, 30]
    next_date = now if not correct else now + timedelta(days=intervals[min(len(intervals)-1, hits-1)])

    if old:
        conn.execute("""
            UPDATE revisoes SET prioridade=?, proxima_revisao=?, erros=?, acertos=?
            WHERE usuario_id=? AND questao_id=?
        """, (priority, next_date.isoformat(), errors, hits, USER_ID, question_id))
    else:
        conn.execute("""
            INSERT INTO revisoes(usuario_id, questao_id, prioridade, proxima_revisao, erros, acertos)
            VALUES(?, ?, ?, ?, ?, ?)
        """, (USER_ID, question_id, priority, next_date.isoformat(), errors, hits))

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
    
    b_disc = pd.read_sql_query("""
        SELECT d.nome disciplina,
               COUNT(r.id) respondidas,
               COALESCE(SUM(r.acertou),0) acertos,
               COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros,
               ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual
        FROM respostas r
        JOIN questoes q ON q.id=r.questao_id
        JOIN disciplinas d ON d.id=q.disciplina_id
        WHERE r.usuario_id = ?
        GROUP BY d.id ORDER BY percentual
    """, conn, params=(USER_ID,))

    b_filt = pd.read_sql_query("""
        SELECT f.nome filtro,
               d.nome disciplina,
               l.nome lei,
               COUNT(r.id) respondidas,
               COALESCE(SUM(r.acertou),0) acertos,
               COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros,
               ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual
        FROM respostas r
        JOIN questoes q ON q.id=r.questao_id
        JOIN filtros_salvos f ON f.id=q.filtro_id
        JOIN disciplinas d ON d.id=f.disciplina_id
        JOIN leis l ON l.id=f.lei_id
        WHERE r.usuario_id = ?
        GROUP BY f.id ORDER BY r.id DESC
    """, conn, params=(USER_ID,))

    b_cont = pd.read_sql_query("""
        SELECT d.nome disciplina, q.conteudo,
               COUNT(r.id) respondidas,
               COALESCE(SUM(r.acertou),0) acertos,
               COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros,
               ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual
        FROM respostas r
        JOIN questoes q ON q.id=r.questao_id
        JOIN disciplinas d ON d.id=q.disciplina_id
        WHERE r.usuario_id = ?
        GROUP BY d.id,q.conteudo ORDER BY percentual
    """, conn, params=(USER_ID,))

    due = conn.execute("""
        SELECT COUNT(*) n FROM revisoes
        WHERE usuario_id = ? AND proxima_revisao <= ?
    """, (USER_ID, datetime.now().isoformat())).fetchone()["n"]

    conn.close()
    return total, hits, errors, pct, b_disc, b_filt, b_cont, due

st.title("⚖️ Decorando Lei Seca")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📚 Importar Leis",
    "🎯 Criar Caderno / Filtro",
    "📝 Resolver Questões",
    "📊 Desempenho",
    "🔄 Revisões"
])

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

    st.subheader("Upload do PDF da Lei")
    law_title = st.text_input("Nome da Lei (ex: CF/88, Código Penal):")
    uploaded_file = st.file_uploader("Escolha o arquivo PDF", type=["pdf"])

    if st.button("Processar e Salvar Lei"):
        if not disc_sel or not law_title or not uploaded_file:
            st.error("Preencha todos os campos e selecione o PDF!")
        else:
            disc_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            file_path = PDF_DIR / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            law_id = add_law(disc_id, law_title, uploaded_file.name)
            qtd = parse_and_store_pdf(file_path, law_id)
            st.success(f"Sucesso! Lei dividida em {qtd} questões curtas.")

    st.divider()
    todas_leis = get_laws()
    if todas_leis:
        for l in todas_leis:
            lc1, lc2 = st.columns([4, 1])
            lc1.write(f"📄 **{l['nome']}**")
            if lc2.button("Excluir Lei", key=f"del_law_{l['id']}"):
                delete_law(l['id'])
                st.rerun()

with tab2:
    st.header("Criar Caderno de Questões")
    discs = get_disciplines()
    disc_dict = {d["nome"]: d["id"] for d in discs}
    
    disc_f = st.selectbox("1. Selecione a Disciplina", [""] + list(disc_dict.keys()), key="f_disc")
    
    if disc_f:
        d_id = disc_dict[disc_f]
        laws = get_laws(d_id)
        law_dict = {l["nome"]: l["id"] for l in laws}
        
        law_f = st.selectbox("2. Selecione a Lei", [""] + list(law_dict.keys()), key="f_law")
        
        if law_f:
            l_id = law_dict[law_f]
            articles = get_articles(l_id)
            art_dict = {f"{a['numero']} - {a['texto'][:60]}...": a["id"] for a in articles}
            
            selected_arts = st.multiselect("3. Selecione os Artigos/Trechos:", list(art_dict.keys()))
            total_arts = len(selected_arts) if selected_arts else len(articles)
            
            qtd_q = st.number_input("4. Quantidade de questões:", min_value=1, max_value=500, value=max(total_arts, 10))
            filter_name = st.text_input("5. Nome do seu Caderno / Filtro:")

            if st.button("Salvar Caderno e Gerar Questões"):
                if filter_name:
                    art_ids = [art_dict[k] for k in selected_arts]
                    f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                    qtd_geradas = generate_questions_for_articles(d_id, l_id, art_ids, qtd_q, filter_id=f_id)
                    st.success(f"Caderno '{filter_name}' criado com {qtd_geradas} questões!")
                    st.rerun()

with tab3:
    st.header("Resolver Questões")
    
    saved_filters = get_saved_filters()
    
    if not saved_filters:
        st.info("Nenhuma questão disponível. Importe um PDF na aba 'Importar Leis' e crie um caderno na aba 'Criar Caderno / Filtro'.")
    else:
        f_options = {f"{f['nome']} ({f['disciplina']} - {f['lei']})": f["id"] for f in saved_filters}
        sel_filter_label = st.selectbox("Selecione o Caderno para Treinar:", list(f_options.keys()), key="res_caderno_filter")
        sel_filter_id = f_options[sel_filter_label]

        if "last_filter_id" not in st.session_state or st.session_state["last_filter_id"] != sel_filter_id:
            st.session_state["last_filter_id"] = sel_filter_id
            st.session_state["q_index"] = 0

        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=? ORDER BY id", (sel_filter_id,)).fetchall()
        conn.close()

        if questoes:
            idx = st.session_state.get("q_index", 0)
            if idx >= len(questoes):
                st.success("🎉 Concluiu todas as questões deste caderno!")
                if st.button("Reiniciar Caderno"):
                    st.session_state["q_index"] = 0
                    st.rerun()
            else:
                q = questoes[idx]
                st.subheader(f"Questão {idx + 1} de {len(questoes)}")
                st.markdown(f"**Dispositivo:** {q['artigo_numero']}")
                st.markdown(q["enunciado"])

                resp = st.radio("Sua resposta:", ["Certo", "Errado"], key=f"q_{q['id']}")
                
                if st.button("Responder", key=f"btn_{q['id']}"):
                    val = 1 if resp == "Certo" else 0
                    acertou = record_answer(q["id"], val, cycle=1)
                    if acertou:
                        st.success("✨ Correto!")
                    else:
                        st.error("❌ Incorreto!")
                    st.markdown(f"**Gabarito / Explicação:**\n\n{q['explicacao']}")

                if st.button("Próxima Questão ➡️"):
                    st.session_state["q_index"] += 1
                    st.rerun()

with tab4:
    st.header("Seu Desempenho")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Respondidas", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")

    if not b_filt.empty:
        st.dataframe(b_filt, use_container_width=True)

with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    st.metric("Questões Pendentes para Revisão Hoje", due)

    if due > 0:
        conn = db()
        revs = conn.execute("""
            SELECT q.* FROM revisoes r
            JOIN questoes q ON q.id = r.questao_id
            WHERE r.usuario_id = ? AND r.proxima_revisao <= ?
            LIMIT 1
        """, (USER_ID, datetime.now().isoformat())).fetchone()
        conn.close()

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
                    st.error("❌ Errou! Ela voltará para revisão.")
                st.markdown(f"**Gabarito / Explicação:**\n\n{revs['explicacao']}")
    else:
        st.success("Tudo em dia! Não há revisões pendentes para hoje.")