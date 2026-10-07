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

try:
    from google import genai
except ImportError:
    try:
        import google.generativeai as genai
    except ImportError:
        genai = None

# ==============================================================================
# CONFIGURAÇÃO DE DIRETÓRIOS E DISCO PERSISTENTE NO RENDER
# ==============================================================================
APP_DIR = Path(__file__).parent

PERSISTENT_DIR = Path("/data") if Path("/data").exists() else APP_DIR
DB_FILE = PERSISTENT_DIR / "decorando_lei.db"
PDF_DIR = PERSISTENT_DIR / "leis_importadas"
PDF_DIR.mkdir(parents=True, exist_ok=True)

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

REGEX_ROMANO = r'(?=[MDCLXVI])M*(?:C[MD]|D?C{0,3})(?:X[CL]|L?X{0,3})(?:I[XV]|V?I{0,3})'

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def limpar_e_formatar_texto_lei(texto):
    if not texto:
        return ""
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
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
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
    autorizado = 1 if u_clean == ADMIN_EMAIL else 0
    try:
        conn.execute(
            "INSERT INTO usuarios (username, senha, autorizado, criado_em) VALUES (?, ?, ?, ?)",
            (u_clean, hash_password(senha), autorizado, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        return True, "Cadastro realizado! Aguarde liberação do administrador." if autorizado == 0 else "Utilizador criado e autorizado!"
    except sqlite3.IntegrityError:
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
                st.info(msg) if ok else st.error(msg)
            else:
                st.warning("Preencha todos os campos.")
    st.stop()

USER_ID = st.session_state["user_id"]
USERNAME = st.session_state["username"]
is_admin_user = bool(USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL)

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
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id WHERE l.disciplina_id=? ORDER BY d.nome, l.nome", (discipline_id,)).fetchall()
    else:
        rows = conn.execute("SELECT l.*, d.nome as disciplina_nome FROM leis l JOIN disciplinas d ON d.id = l.disciplina_id ORDER BY d.nome, l.nome").fetchall()
    conn.close()
    return rows

# ==============================================================================
# FRAGMENTAÇÃO INTELIGENTE DE ARTIGOS
# ==============================================================================
def normalizar_estrutura_dispositivo(texto):
    if not texto:
        return ""
    texto = texto.replace("\r", "\n")
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'(?:;|\.|\n|\s)\s*(§\s*\d+º?|Parágrafo único)\b', r'\n\1 ', texto, flags=re.IGNORECASE)
    texto = re.sub(rf'(?:;|\.|\n|\s)\s*(?={REGEX_ROMANO}\s*[-–—\.]\s*)', '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'(?:;|\.|\n|\s)\s*(?=[a-z]\s*[\)\-]\s*)', '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'(?<=[;])\s+(?=\d+[\)\.-]\s*)', '\n', texto)
    texto = re.sub(r'\n{2,}', '\n', texto)
    return texto.strip()

def eh_marcador_paragrafo(linha):
    return bool(re.match(r'^(§\s*\d+º?|Parágrafo único)\b', linha.strip(), re.IGNORECASE))

def eh_marcador_inciso(linha):
    return bool(re.match(rf'^{REGEX_ROMANO}\s*[-–—\.]\s*', linha.strip(), re.IGNORECASE))

def eh_marcador_alinea(linha):
    return bool(re.match(r'^[a-z]\s*[\)\-]\s*', linha.strip(), re.IGNORECASE))

def extrair_blocos_por_marcador(texto, tipo):
    linhas = [l.strip() for l in texto.split('\n') if l.strip()]
    if not linhas:
        return []
    matcher = eh_marcador_paragrafo if tipo == 'paragrafo' else (eh_marcador_inciso if tipo == 'inciso' else eh_marcador_alinea)
    blocos, atual_marcador, atual_texto = [], None, []
    for linha in linhas:
        if matcher(linha):
            if atual_marcador is not None:
                blocos.append((atual_marcador, ' '.join(atual_texto).strip()))
            if tipo == 'paragrafo':
                m = re.match(r'^(§\s*\d+º?|Parágrafo único)', linha, re.IGNORECASE)
            elif tipo == 'inciso':
                m = re.match(rf'^({REGEX_ROMANO}\s*[-–—\.]\s*)', linha, re.IGNORECASE)
            else:
                m = re.match(r'^([a-z]\s*[\)\-]\s*)', linha, re.IGNORECASE)
            atual_marcador = m.group(1).strip() if m else linha.split()[0]
            atual_texto = [linha[m.end():].strip() if m else linha]
        else:
            if atual_marcador is not None:
                atual_texto.append(linha)
    if atual_marcador is not None:
        blocos.append((atual_marcador, ' '.join(atual_texto).strip()))
    return [(m, t) for m, t in blocos if m and t.strip()]

def fracionar_artigo_extenso(num_art, corpo_limpo):
    texto = normalizar_estrutura_dispositivo(corpo_limpo)
    paragrafos = extrair_blocos_por_marcador(texto, 'paragrafo')
    incisos = extrair_blocos_por_marcador(texto, 'inciso')
    if len(paragrafos) == 0 and len(incisos) == 0:
        return [{'numero': f"{num_art} (caput)" if len(corpo_limpo) > 100 else num_art, 'texto': corpo_limpo.strip()}]
    
    alvos = []
    marcadores = []
    for padrao in [r'(?m)^§\s*\d+º?', r'(?m)^Parágrafo único\b', rf'(?m)^{REGEX_ROMANO}\s*[-–—\.]\s*']:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            marcadores.append(m.start())
    inicio = texto[:min(marcadores)].strip() if marcadores else texto.strip()
    if inicio and len(inicio) > 10:
        inicio_limpo = re.sub(r'^Art\.\s*\d+[\w\-]*[\.\º\ª]?\s*[-–—]?\s*', '', inicio, flags=re.IGNORECASE).strip()
        if inicio_limpo:
            alvos.append({'numero': f'{num_art} (caput)', 'texto': inicio_limpo})

    posicao_primeiro_paragrafo = None
    if paragrafos:
        m = re.search(r'(?m)^(?:§\s*\d+º?|Parágrafo único)\b', texto, re.IGNORECASE)
        if m:
            posicao_primeiro_paragrafo = m.start()

    trecho_incisos_caput = texto[:posicao_primeiro_paragrafo].strip() if posicao_primeiro_paragrafo is not None else texto
    incisos_caput = extrair_blocos_por_marcador(trecho_incisos_caput, 'inciso')
    numeros_existentes = {a['numero'] for a in alvos}

    for marcador, texto_inciso in incisos_caput:
        if marcador and texto_inciso and len(texto_inciso) > 5:
            clean_marc = str(marcador).rstrip("-–—.").strip()
            num_formatado = f'{num_art}, Inciso {clean_marc}'
            alvos.append({'numero': num_formatado, 'texto': f'{marcador} {texto_inciso}'.strip()})
            numeros_existentes.add(num_formatado)

    for marcador_par, texto_par in paragrafos:
        if not marcador_par or not texto_par or len(texto_par) <= 5:
            continue
        num_par = f'{num_art}, {marcador_par}'
        alvos.append({'numero': num_par, 'texto': f'{marcador_par} {texto_par}'.strip()})
        numeros_existentes.add(num_par)

    if not alvos:
        return [{'numero': num_art, 'texto': corpo_limpo.strip()}]
    return alvos

def parse_and_store_pdf(pdf_path, law_id):
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    doc.close()
    artigo_regex = re.compile(r'(?m)^(Art\.\s*\d+[\w\-]*[\.\º\ª]?)', re.IGNORECASE)
    partes = artigo_regex.split(full_text)
    artigos_brutos = []
    if len(partes) > 1:
        for i in range(1, len(partes), 2):
            num_art = partes[i].strip()
            corpo_art = partes[i + 1] if (i + 1) < len(partes) else ""
            corpo_limpo = limpar_e_formatar_texto_lei(corpo_art)
            if corpo_limpo and len(corpo_limpo) > 10:
                artigos_brutos.append((num_art, corpo_limpo))
    conn = db()
    quantidade = 0
    for num_art, corpo_limpo in artigos_brutos:
        fragmentos = fracionar_artigo_extenso(num_art, corpo_limpo)
        for frag in fragmentos:
            conn.execute("INSERT INTO artigos(lei_id, numero, titulo, texto) VALUES(?,?,?,?)", (law_id, frag['numero'], num_art, frag['texto']))
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
    cur = conn.execute("INSERT INTO filtros_salvos (usuario_id, nome, disciplina_id, lei_id, artigos_ids, qtd_questoes, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)", (USER_ID, name, discipline_id, law_id, art_str, qtd_questoes, datetime.now().isoformat()))
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
        rows = conn.execute("SELECT f.*, d.nome disciplina, l.nome lei FROM filtros_salvos f JOIN disciplinas d ON d.id = f.disciplina_id JOIN leis l ON l.id = f.lei_id WHERE f.usuario_id = ? AND f.disciplina_id = ? ORDER BY d.nome, f.id DESC", (USER_ID, discipline_id)).fetchall()
    else:
        rows = conn.execute("SELECT f.*, d.nome disciplina, l.nome lei FROM filtros_salvos f JOIN disciplinas d ON d.id = f.disciplina_id JOIN leis l ON l.id = f.lei_id WHERE f.usuario_id = ? ORDER BY d.nome, f.id DESC", (USER_ID,)).fetchall()
    conn.close()
    return rows

def obter_texto_caput(artigo_id):
    if not artigo_id:
        return None
    conn = db()
    artigo = conn.execute("SELECT texto, titulo FROM artigos WHERE id = ?", (artigo_id,)).fetchone()
    conn.close()
    if artigo and artigo["titulo"]:
        conn2 = db()
        caput = conn2.execute("SELECT texto FROM artigos WHERE lei_id = (SELECT lei_id FROM artigos WHERE id = ?) AND numero = ? LIMIT 1", (artigo_id, f"{artigo['titulo']} (caput)")).fetchone()
        conn2.close()
        if caput and caput["texto"]:
            return caput["texto"]
    return None

# ==============================================================================
# GERAÇÃO DE ASSERTIVAS E PEGADINHAS COM NEXO JURÍDICO
# ==============================================================================
def limpar_assertiva_dispositivo(texto):
    if not texto:
        return ""
    t = texto.strip()
    t = re.sub(rf'^(?:{REGEX_ROMANO}\s*[-–—\.]\s*|§\s*\d+º?\s*[-–—\.]?\s*|Parágrafo único\s*[-–—\.]?\s*|[a-z]\s*[\)\-]\s*)', '', t, flags=re.IGNORECASE).strip()
    t = re.sub(r'[\s;:,]+$', '', t).strip()
    if not t:
        return texto.strip()
    t = t[0].upper() + t[1:]
    if not t.endswith('.'):
        t += '.'
    return t

def conectar_caput_com_dispositivo(caput_texto, assertiva_limpa, rotulo_dispositivo):
    if not caput_texto or not assertiva_limpa:
        return assertiva_limpa
    cap = caput_texto.strip()
    if cap.endswith(':') and len(cap) < 120:
        cap_sem_dois_pontos = cap.rstrip(':').strip()
        if not assertiva_limpa.lower().startswith(cap_sem_dois_pontos.lower()[:20]):
            verbo_ajustado = assertiva_limpa[0].lower() + assertiva_limpa[1:]
            return f"{cap_sem_dois_pontos} {verbo_ajustado}"
    return assertiva_limpa

def formatar_nome_lei_contextual(nome_lei):
    if not nome_lei:
        return "Constituição Federal / Lei Seca"
    nl = str(nome_lei).strip()
    return f"Constituição Federal de 1988 ({nl})" if re.match(r'^art(?:igo)?s?\.?\s*\d+', nl, re.IGNORECASE) else nl

def construir_enunciado_com_nexo(nome_lei, rotulo_dispositivo, assertiva_texto, caput_texto=None, num_art=None):
    ref_rotulo = obter_rotulo_dispositivo(rotulo_dispositivo)
    lei_formatada = formatar_nome_lei_contextual(nome_lei)
    vinculo = f" (pertencente ao {num_art})" if num_art and num_art not in ref_rotulo else ""
    return (
        f"**Referência Normativa:** {lei_formatada} — **{ref_rotulo}**{vinculo}\n\n"
        f"À luz da literalidade da legislação e do dispositivo legal em exame, julgue o item a seguir:\n\n"
        f"> \"{assertiva_texto}\""
    )

def obter_rotulo_dispositivo(numero_dispositivo):
    if not numero_dispositivo:
        return "Dispositivo da Lei"
    s = str(numero_dispositivo).strip()
    return re.sub(r'^(?:Inciso|Parágrafo|Alínea|Artigo)\s*\((.+)\)$', r'\1', s, flags=re.IGNORECASE)

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de obrigação ("deverá") por faculdade ("poderá")'),
        (r'\bpoderá\b', 'deverá obrigatoriamente', 'troca de faculdade ("poderá") por imposição obrigatória'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão legal para vedação'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição expressa para permissão'),
        (r'\bexigido\b', 'dispensado', 'troca de exigência legal por dispensa indevida'),
        (r'\bdispensado\b', 'exigido', 'troca de dispensa legal por exigência indevida'),
        (r'\bobrigatório\b', 'facultativo', 'troca de obrigatoriedade legal por facultatividade'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração indevida de prazo legal de 24h para 48h'),
        (r'\b30 \(trinta\) dias\b', '15 (quinze) dias', 'alteração indevida de prazo legal de 30 para 15 dias')
    ]
    texto_modificado = texto
    tipo_troca = None
    for padrao, sub, desc in substituicoes:
        if re.search(padrao, texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(padrao, sub, texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = desc
            break
    if not tipo_troca:
        if re.search(r'^É assegurado\b', texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(r'^É assegurado\b', 'Não é assegurado', texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = 'inversão do direito assegurado para negativa'
        elif re.search(r'^São invioláveis\b', texto_modificado, re.IGNORECASE):
            texto_modificado = re.sub(r'^São invioláveis\b', 'Não são invioláveis', texto_modificado, count=1, flags=re.IGNORECASE)
            tipo_troca = 'supressão da inviolabilidade constitucional'
        else:
            texto_modificado = f"{texto_modificado.rstrip('.')}, ressalvada decisão discricionária em sentido contrário."
            tipo_troca = 'criação de ressalva não prevista na literalidade da lei'
    if texto_modificado:
        texto_modificado = texto_modificado[0].upper() + texto_modificado[1:]
        if not texto_modificado.endswith('.'):
            texto_modificado += '.'
    return texto_modificado, tipo_troca

# ==============================================================================
# INTELIGÊNCIA ARTIFICIAL: EXEMPLOS PRÁTICOS DINÂMICOS
# ==============================================================================
def obter_chave_gemini():
    if st.session_state.get("gemini_api_key"):
        return str(st.session_state["gemini_api_key"]).strip()
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
        if "GOOGLE_API_KEY" in st.secrets:
            return str(st.secrets["GOOGLE_API_KEY"]).strip()
    except Exception:
        pass
    env_k = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return str(env_k).strip() if env_k else None

def extrair_json_exemplo(raw_text, rotulo_dispositivo):
    if not raw_text:
        return None
    clean = re.sub(r'```(?:json)?\s*', '', raw_text)
    clean = re.sub(r'```', '', clean).strip()
    m = re.search(r'\{[\s\S]*\}', clean)
    if m:
        try:
            d = json.loads(m.group(0))
            sit = d.get("situacao_real") or d.get("situacaoReal")
            ap = d.get("aplicacao_regra") or d.get("aplicacaoRegra")
            obj = d.get("objetivo_regra") or d.get("objetivoRegra")
            biz = d.get("bizu_memorizacao") or d.get("bizuMemorizacao")
            if sit:
                return (
                    sit.strip(),
                    f"• **Aplicação no {rotulo_dispositivo}:** {ap.strip() if ap else 'Aplicação direta da literalidade normativa.'}",
                    obj.strip() if obj else "Garantir segurança jurídica e legalidade estrita.",
                    biz.strip() if biz else "Atente-se às palavras-chave cobradas pelas bancas."
                )
        except Exception:
            pass
    return None

def gerar_exemplo_gemini(rotulo_dispositivo, texto_dispositivo, chave_manual=None):
    chave = chave_manual or obter_chave_gemini()
    if not chave:
        return None

    texto_puro = texto_dispositivo
    if "De acordo com o" in texto_puro:
        m = re.search(r':\s*"(.*)"\s*$', texto_puro, re.DOTALL)
        if m:
            texto_puro = m.group(1).strip()

    prompt = f"""Você é um professor de Direito para concursos públicos no Brasil.
Dispositivo legal: {rotulo_dispositivo}
Texto literal: "{texto_puro}"

Crie um exemplo prático e objetivo da vida real (2 a 3 frases) demonstrando como esse dispositivo exato é aplicado na prática com nomes fictícios.

Responda EXCLUSIVAMENTE em formato JSON com as chaves:
{{
  "situacao_real": "Narrativa objetiva de 2 a 3 frases de um caso concreto aplicando este dispositivo com nomes fictícios",
  "aplicacao_regra": "Como a regra foi aplicada ao caso concreto",
  "objetivo_regra": "Qual a finalidade protetiva ou jurídica da norma",
  "bizu_memorizacao": "Dica rápida de memorização ou pegadinha comum de banca"
}}"""

    for model_name in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={chave}"
            headers = {"Content-Type": "application/json"}
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                result_raw = json.loads(response.read().decode("utf-8"))
                candidate = result_raw.get("candidates", [])[0]["content"]["parts"][0]["text"]
                res = extrair_json_exemplo(candidate, rotulo_dispositivo)
                if res:
                    return res
        except Exception:
            pass
    return None

def gerar_exemplo_dinamico_heuristico(art_num, texto_original):
    txt = texto_original.strip()
    txt_lower = txt.lower()
    ator = "O cidadão Pedro"
    if "servidor" in txt_lower:
        ator = "O servidor público Marcos"
    elif "juiz" in txt_lower or "tribunal" in txt_lower:
        ator = "O magistrado titular"
    elif "polícia" in txt_lower or "autoridade" in txt_lower:
        ator = "A autoridade policial"
    elif "preso" in txt_lower or "pena" in txt_lower:
        ator = "O custodiado Lucas"

    situacao = f"Em uma situação prática envolvendo {ator}, aplicou-se diretamente a diretriz prevista no {art_num} para pacificar o conflito de interesses de acordo com a literalidade legal."
    aplicacao = f"• **Aplicação no {art_num}:** Vinculação estrita aos ditames normativos."
    objetivo = "Garantir a segurança jurídica e a ordem pública."
    bizu = f"Em provas de concurso, a cobrança do {art_num} exige atenção literal aos termos empregados."
    return situacao, aplicacao, objetivo, bizu

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, texto_modificado=None, exemplo_customizado=None, foi_ia=False, nome_ia="Gemini IA", caput_texto=None):
    if exemplo_customizado and len(exemplo_customizado) == 4:
        situacao_real, aplicacao_regra, objetivo_regra, bizu_memorizacao = exemplo_customizado
    else:
        situacao_real, aplicacao_regra, objetivo_regra, bizu_memorizacao = gerar_exemplo_dinamico_heuristico(art_num, texto_original)

    status_txt = "O item está **CORRETO**." if foi_correto else "O item está **ERRADO**."
    detalhe_erro = "O enunciado reproduz com exatidão a literalidade da legislação." if foi_correto else "O enunciado promoveu alteração indevida da regra legal."
    resumo_erro_bloco = "" if foi_correto else f"<br>⚠️ <strong>Pegadinha da Questão:</strong> {tipo_troca or 'Modificação de termos legais'}."
    tag_ia = f'<span style="background-color: #fef3c7; color: #b45309; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; margin-left: 8px;">✨ Gerado com {nome_ia}</span>' if foi_ia else '<span style="background-color: #eff6ff; color: #1d4ed8; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; margin-left: 8px;">⚖️ Exemplo Prático da Lei</span>'

    bloco_caput = f"""
    <div style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed #cbd5e1; font-size: 12.5px; color: #475569;">
        <span style="font-weight: 600; color: #1e3a8a;">📜 Contexto do Artigo Principal (Caput de Origem):</span><br>
        <span style="font-style: italic;">"{str(caput_texto).strip()}"</span>
    </div>