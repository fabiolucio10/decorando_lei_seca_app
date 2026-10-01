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

# Estilização CSS para ocultar menus e barras indesejadas
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
    
    /* Caixa de destaque para enunciado legal */
    .lei-box {
        background-color: #f8f9fa;
        border-left: 5px solid #2b5c8f;
        padding: 15px;
        border-radius: 5px;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        font-size: 15px;
        line-height: 1.6;
        color: #1a1a1a;
        margin-bottom: 15px;
    }
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
    Limpa notas de rodapé, números de páginas, URLs e organiza a quebra de incisos e parágrafos.
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

    # Organiza quebras de linha antes de Incisos (I -, II -, V -, etc) e Parágrafos (§)
    texto = re.sub(r'(\s+)(?=[I|V|X|L|C|D|M]+\s*[-–])', '\n\n', texto)
    texto = re.sub(r'(\s+)(?=\§\s*\d+º?)', '\n\n', texto)
    
    texto = re.sub(r' +', ' ', texto)
    texto = re.sub(r'\n\s*\n', '\n\n', texto)

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
                        st.toast(f"Status de {u['username']} alterado!")
                        st.rerun()

                    if c_del.button("❌", key=f"del_user_{u['id']}", help="Excluir Usuário"):
                        excluir_usuario(u['id'])
                        st.success(f"Usuário {u['username']} removido!")
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

def parse_and_store_pdf(pdf_path, law_id):
    """
    Lê o PDF e subdivide com precisão tanto Artigos principais quanto Incisos individuais,
    evitando aglutinar múltiplos incisos em uma só questão.
    """
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()

    artigo_regex = re.compile(r'(?m)^(Art\.\s*\d+[\w\d\-\.º]*[-–]?\w*)', re.IGNORECASE)
    partes = artigo_regex.split(full_text)
    
    artigos_brutos = []

    for i in range(1, len(partes), 2):
        num_art = partes[i].strip()
        corpo_art = partes[i + 1] if (i + 1) < len(partes) else ""
        corpo_limpo = limpar_e_formatar_texto_lei(corpo_art)
        
        # Procura por incisos dentro do corpo do artigo (ex: V - ..., VI - ...)
        incisos_regex = re.compile(r'(?m)^([I|V|X|L|C|D|M]+\s*[-–]\s*)', re.IGNORECASE)
        sub_partes = incisos_regex.split(corpo_limpo)

        if len(sub_partes) > 1:
            # O primeiro elemento sub_partes[0] é o caput do artigo
            caput = sub_partes[0].strip()
            if caput:
                artigos_brutos.append((num_art, caput))
            
            # Adiciona cada inciso como um item isolado e identificado
            for k in range(1, len(sub_partes), 2):
                inciso_label = sub_partes[k].strip()
                inciso_texto = sub_partes[k+1].strip() if (k+1) < len(sub_partes) else ""
                
                # Isola apenas o texto deste inciso (corta se encontrar o próximo)
                inciso_texto_unico = inciso_texto.split('\n\n')[0] 
                
                num_completo = f"{num_art}, inciso {inciso_label.replace('-', '').strip()}"
                artigos_brutos.append((num_completo, f"{inciso_label} {inciso_texto_unico}"))
        else:
            if corpo_limpo:
                artigos_brutos.append((num_art, corpo_limpo))

    conn = db()
    quantidade = 0
    for num_art, corpo_limpo in artigos_brutos:
        conn.execute(
            "INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)",
            (law_id, num_art, num_art, corpo_limpo)
        )
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
    """
    Modifica pontualmente o texto para criar uma questão de "ERRADO" bem sutil.
    """
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de dever por faculdade'),
        (r'\bpoderá\b', 'deverá', 'troca de faculdade por dever'),
        (r'\bduas testemunhas\b', 'uma testemunha', 'alteração da quantidade de testemunhas exigidas'),
        (r'\bse possível\b', 'obrigatoriamente', 'torna obrigatório o que é condicional'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão'),
        (r'\bantes e depois\b', 'apenas após', 'restrição do período de apuração')
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
            tipo_troca = 'supressão da palavra "não"'
        else:
            words = texto_modificado.split()
            if len(words) > 3:
                words.insert(3, "não")
                texto_modificado = " ".join(words)
                tipo_troca = 'inserção indevida de negação'

    return texto_modificado, tipo_troca

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, motor_ia="🤖 OpenAI / Gemini (Nuvem)"):
    """
    Gera um CASO PRÁTICO REAL e narrativo fático (com nomes de personagens e condutas policiais/jurídicas).
    """
    exemplo_pratico = ""

    # Prompt instruindo a IA a criar um exemplo fático real e dinâmico
    prompt_ex = (
        f"Você é um professor preparatório de Direito Processual Penal e Constitucional.\n"
        f"Com base na norma: '{art_num}' cujo texto é: '{texto_original}'\n"
        "Crie um EXEMPLO PRÁTICO DA VIDA REAL fático, com personagens (ex: Delegado Dr. Marcos, o investigado João, etc).\n"
        "Descreva a cena de uma investigação ou atuação policial/judicial onde essa regra é aplicada exatamente no cotidiano.\n"
        "Formate OBRIGATORIAMENTE assim:\n"
        "• **Caso Concreto na Prática:** [Descreva em 2 a 3 linhas a história fática da atuação policial ou judiciária]\n"
        "• **Aplicação da Norma:** [Explique em 1 linha o porquê essa conduta observou ou descumpriu a lei]."
    )

    if "OpenAI" in motor_ia or "Gemini" in motor_ia:
        api_key = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
        if api_key and openai:
            try:
                client = openai.OpenAI(api_key=api_key)
                comp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt_ex}],
                    temperature=0.7
                )
                exemplo_pratico = comp.choices[0].message.content
            except Exception as e:
                pass

    elif "Ollama" in motor_ia:
        import requests
        try:
            res = requests.post("http://localhost:11434/api/generate", json={
                "model": "llama3",
                "prompt": prompt_ex,
                "stream": False
            }, timeout=4)
            exemplo_pratico = res.json().get("response", "")
        except Exception:
            pass

    # Fallback fático e detalhado se a IA não for chamada/configurada
    if not exemplo_pratico:
        exemplo_pratico = (
            f"• **Caso Concreto na Prática:** Durante uma investigação de roubo, o Delegado de Polícia chamou o investigado Carlos para ser ouvido. Ao final do interrogatório, o termo foi lido e assinado por duas testemunhas presenciais que acompanharam a oitiva.\n"
            f"• **Aplicação da Norma:** A conduta da autoridade cumpriu exatamente o {art_num}, garantindo a legalidade do ato de colheita de prova no Inquérito Policial."
        )

    if foi_correto:
        status_txt = "O item está **CORRETO**."
        detalhe_erro = f"O enunciado reproduziu a redação exata do **{art_num}**."
        resumo_erro_bloco = ""
    else:
        status_txt = "O item está **ERRADO**."
        detalhe_erro = f"A banca alterou a regra original do artigo."
        resumo_erro_bloco = f"\n• **Pegadinha da Questão:** Houve **{tipo_troca or 'alteração de termos legais'}** no texto apresentado no enunciado."

    explicacao_formatada = f"""💡 **Explicação Direta:**
{status_txt} {detalhe_erro}

📌 **Exemplo Prático da Vida Real (Aplicação Prática do {art_num}):**

{exemplo_pratico}{resumo_erro_bloco}

📜 **Texto Original e Literal da Lei:**
> "{texto_original}"
"""
    return explicacao_formatada

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="🤖 OpenAI / Gemini (Nuvem)"):
    conn = db()
    if article_ids:
        placeholders = ",".join("?" * len(article_ids))
        arts = conn.execute(f"SELECT * FROM artigos WHERE id IN ({placeholders}) ORDER BY id", article_ids).fetchall()
    else:
        arts = conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()

    if not arts:
        conn.close()
        return 0

    alvos = []
    for art in arts:
        texto_artigo = limpar_e_formatar_texto_lei(art["texto"])
        alvos.append({
            "art": art,
            "numero": art["numero"],
            "texto": texto_artigo
        })

    if not alvos:
        conn.close()
        return 0

    random.shuffle(alvos)
    generated = 0
    now = datetime.now().isoformat()

    for i in range(qtd_total):
        alvo = alvos[i % len(alvos)]
        art = alvo["art"]
        numero_dispositivo = alvo["numero"]
        text = alvo["texto"]
        is_correct = random.choice([True, False])

        if is_correct:
            enunciado_texto = text
            tipo_troca = None
        else:
            enunciado_texto, tipo_troca = alterar_texto_para_errado(text)

        enunciado = f"De acordo com o **{numero_dispositivo}**:\n\n\"{enunciado_texto}\""
        gabarito = 1 if is_correct else 0
        explicacao = gerar_explicacao_humana(numero_dispositivo, text, is_correct, tipo_troca, motor_ia=motor_ia)

        try:
            conn.execute("""
                INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (
                law_id,
                art["id"],
                discipline_id,
                filter_id,
                numero_dispositivo,
                numero_dispositivo,
                enunciado,
                gabarito,
                explicacao,
                motor_ia,
                now
            ))
            generated += 1
        except sqlite3.IntegrityError:
            pass

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
    if old:
        errors = old["erros"] + (0 if correct else 1)
        hits = old["acertos"] + (1 if correct else 0)
    else:
        errors = 0 if correct else 1
        hits = 1 if correct else 0

    if not correct:
        priority = min(10, (old["prioridade"] if old else 1) + 2)
        next_date = now
    else:
        priority = max(0, (old["prioridade"] if old else 1) - 1)
        intervals = [1, 3, 7, 15, 30]
        idx = min(len(intervals)-1, hits-1)
        next_date = now + timedelta(days=intervals[idx])

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

    due = conn.execute("""
        SELECT COUNT(*) n FROM revisoes
        WHERE usuario_id = ? AND proxima_revisao <= ?
    """, (USER_ID, datetime.now().isoformat())).fetchone()["n"]

    conn.close()
    return total, hits, errors, pct, b_disc, b_filt, None, due

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

    law_title = st.text_input("Nome da Lei (ex: Código de Processo Penal):")
    uploaded_file = st.file_uploader("Escolha o arquivo PDF da lei", type=["pdf"])

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
            st.success(f"Lei processada com sucesso! {qtd} dispositivos (artigos/incisos isolados) mapeados.")

    st.divider()
    st.subheader("🗑️ Leis Cadastradas")
    todas_leis = get_laws()
    if todas_leis:
        for l in todas_leis:
            lc1, lc2 = st.columns([4, 1])
            lc1.write(f"📄 **{l['nome']}** _({l['disciplina_nome']})_")
            if lc2.button("Excluir", key=f"del_law_{l['id']}"):
                delete_law(l['id'])
                st.rerun()

with tab2:
    st.header("Criar Caderno de Questões por Filtro")
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
            art_dict = {f"{a['numero']} - {a['texto'][:70]}...": a["id"] for a in articles}
            
            selected_arts = st.multiselect("3. Selecione os Artigos/Incisos Específicos (ou deixe vazio para Todos):", list(art_dict.keys()))
            
            total_arts_selecionados = len(selected_arts) if selected_arts else len(articles)
            sugestao_qtd = max(total_arts_selecionados * 2, 10)
            
            qtd_q = st.number_input("4. Quantidade de questões para este filtro:", min_value=1, max_value=500, value=sugestao_qtd)
            
            motor_ia = st.radio(
                "5. Selecione o Motor para Geração de Casos Práticos:",
                ["🤖 OpenAI / Gemini (Nuvem)", "⚙️ Regra Padrão", "🦙 Ollama (Local)"]
            )

            filter_name = st.text_input("6. Nome do seu Caderno / Filtro:")

            if st.button("Salvar Caderno e Gerar Questões"):
                if not filter_name:
                    st.error("Informe um nome para o seu caderno!")
                else:
                    art_ids = [art_dict[k] for k in selected_arts]
                    f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                    qtd_geradas = generate_questions_for_articles(d_id, l_id, art_ids, qtd_q, filter_id=f_id, motor_ia=motor_ia)
                    st.success(f"Caderno '{filter_name}' criado com sucesso! {qtd_geradas} questões organizadas.")

with tab3:
    st.header("Resolver Questões")
    
    discs = get_disciplines()
    disc_options = {"Todas as Disciplinas": None}
    for d in discs:
        disc_options[d["nome"]] = d["id"]

    selected_disc_label = st.selectbox("Selecione a Disciplina:", list(disc_options.keys()), key="res_disc_filter")
    selected_disc_id = disc_options[selected_disc_label]

    saved_filters = get_saved_filters(selected_disc_id)
    
    if not saved_filters:
        st.info("Nenhum caderno de questões encontrado para a disciplina selecionada.")
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

        if not questoes:
            st.warning("Nenhuma questão gerada para este caderno.")
        else:
            if "q_index" not in st.session_state:
                st.session_state["q_index"] = 0

            idx = st.session_state["q_index"]
            if idx >= len(questoes):
                st.success("🎉 Você concluiu todas as questões deste caderno!")
                if st.button("Reiniciar Caderno"):
                    st.session_state["q_index"] = 0
                    st.rerun()
            else:
                q = questoes[idx]
                st.subheader(f"Questão {idx + 1} de {len(questoes)}")
                st.markdown(f"**Dispositivo:** `{q['artigo_numero']}`")
                
                # Exibição bonita com estilo estilizado
                st.markdown(f'<div class="lei-box">{q["enunciado"]}</div>', unsafe_allow_html=True)

                resp = st.radio("Sua resposta:", ["Certo", "Errado"], key=f"q_{q['id']}")
                
                if st.button("Responder", key=f"btn_{q['id']}"):
                    val = 1 if resp == "Certo" else 0
                    acertou = record_answer(q["id"], val, cycle=1)
                    if acertou:
                        st.success("✨ Resposta Correta!")
                    else:
                        st.error("❌ Resposta Incorreta!")
                    st.markdown(f"{q['explicacao']}")

                if st.button("Próxima Questão ➡️"):
                    st.session_state["q_index"] += 1
                    st.rerun()

with tab4:
    st.header("Seu Desempenho")
    tot, ac, err, pct, b_disc, b_filt, _, due = stats()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Respondidas", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")

    st.subheader("Desempenho por Caderno")
    if not b_filt.empty:
        st.dataframe(b_filt, use_container_width=True)
    else:
        st.info("Nenhuma questão respondida ainda.")

    st.divider()
    if st.button("Zerar Histórico de Respostas"):
        zerar_historico_dashboard()
        st.success("Histórico zerado!")
        st.rerun()

with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, _, due = stats()
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
            st.markdown(f'<div class="lei-box">{revs["enunciado"]}</div>', unsafe_allow_html=True)
            resp_rev = st.radio("Sua resposta:", ["Certo", "Errado"], key="rev_ans")
            if st.button("Enviar Resposta da Revisão"):
                val = 1 if resp_rev == "Certo" else 0
                acertou = record_answer(revs["id"], val, cycle=2)
                if acertou:
                    st.success("✨ Excelente!")
                else:
                    st.error("❌ Errou!")
                st.markdown(f"{revs['explicacao']}")
    else:
        st.success("Tudo em dia! Não há revisões pendentes para hoje.")