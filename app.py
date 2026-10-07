import hashlib
json_mod = __import__('json')
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
# CONFIGURAÇÃO DE DIRETÓRIOS E PERSISTÊNCIA NA NUVEM / RENDER
# ==============================================================================
APP_DIR = Path(__file__).parent

# Se houver um disco persistente montado no Render em /data, utiliza-o. Caso contrário, usa a pasta local.
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
            d = json_mod.loads(m.group(0))
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
            req = urllib.request.Request(url, data=json_mod.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                result_raw = json_mod.loads(response.read().decode("utf-8"))
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
    """ if caput_texto and str(caput_texto).strip() != str(texto_original).strip() else ""

    return f"""
    <div style="margin-bottom: 10px; font-size: 13.5px;">
        💡 <strong>Gabarito e Justificativa:</strong> {status_txt} {detalhe_erro}{resumo_erro_bloco}
    </div>
    <div style="background-color: #f8fafc; border: 1px solid #bfdbfe; border-radius: 10px; padding: 15px; margin-bottom: 14px;">
        <div style="font-weight: 600; color: #1e3a8a; font-size: 13.5px; margin-bottom: 6px;">📖 Dispositivo Literal da Lei Seca ({art_num})</div>
        <div style="color: #334155; font-style: italic; border-left: 3px solid #3b82f6; padding-left: 12px; line-height: 1.5; font-size: 13px;">
            "{texto_original}"
        </div>
        {bloco_caput}
    </div>
    <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 18px; margin-bottom: 14px;">
        <div style="font-weight: 700; color: #78350f; font-size: 14px; margin-bottom: 10px;">
            💡 Exemplo Prático e Objetivo da Vida Real {tag_ia}
        </div>
        <div style="color: #1f2937; line-height: 1.6; font-size: 13px;">
            <p style="margin-bottom: 8px;"><strong>Situação Concreta:</strong> {situacao_real}</p>
            <p style="margin-bottom: 8px;"><strong>Aplicação Prática:</strong> {aplicacao_regra}</p>
            <p style="margin-bottom: 8px;"><strong>Objetivo da Regra:</strong> {objetivo_regra}</p>
            <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid #fef3c7; color: #92400e; font-weight: 600;">
                🎯 <strong>Bizu de Memorização:</strong> {bizu_memorizacao}
            </div>
        </div>
    </div>
    """

def generate_questions_for_articles(discipline_id, law_id, article_ids, qtd_total, filter_id=None, motor_ia="♊ Gemini IA", chave_ia_manual=None, progress_callback=None):
    conn = db()
    lei_row = conn.execute("SELECT nome FROM leis WHERE id=?", (law_id,)).fetchone()
    nome_lei = lei_row["nome"] if lei_row else "Legislação Aplicável"

    arts = conn.execute(f"SELECT * FROM artigos WHERE id IN ({','.join('?'*len(article_ids))}) ORDER BY id", article_ids).fetchall() if article_ids else conn.execute("SELECT * FROM artigos WHERE lei_id=? ORDER BY id", (law_id,)).fetchall()
    if not arts:
        conn.close()
        return 0

    alvos = []
    for art in arts:
        texto_artigo = limpar_e_formatar_texto_lei(art["texto"])
        caput_artigo = obter_texto_caput(art["id"])
        alvos.append({"art": art, "numero": art["numero"], "texto": texto_artigo, "caput": caput_artigo})

    if not alvos:
        conn.close()
        return 0

    random.shuffle(alvos)
    generated = 0
    now = datetime.now().isoformat()
    usar_gemini = "Gemini" in motor_ia
    cache_ia = {}

    for i in range(qtd_total):
        alvo = alvos[i % len(alvos)]
        art = alvo["art"]
        numero_dispositivo = alvo["numero"]
        rotulo_dispositivo = obter_rotulo_dispositivo(numero_dispositivo)
        text = limpar_e_formatar_texto_lei(alvo["texto"])
        caput_texto = alvo.get("caput")
        is_correct = random.choice([True, False])

        if progress_callback:
            try:
                progress_callback((i + 1) / qtd_total, f"Processando questão {i+1} de {qtd_total}...")
            except Exception:
                pass

        exemplo_ia = None
        if usar_gemini:
            chave_cache = (numero_dispositivo, text[:80])
            if chave_cache in cache_ia:
                exemplo_ia = cache_ia[chave_cache]
            else:
                exemplo_ia = gerar_exemplo_gemini(rotulo_dispositivo, text, chave_manual=chave_ia_manual)
                if exemplo_ia:
                    cache_ia[chave_cache] = exemplo_ia

        foi_ia_utilizada = bool(exemplo_ia is not None)
        assertiva_base = limpar_assertiva_dispositivo(text)
        assertiva_com_nexo = conectar_caput_com_dispositivo(caput_texto, assertiva_base, rotulo_dispositivo)

        if is_correct:
            gabarito = 1
            enunciado = construir_enunciado_com_nexo(nome_lei, rotulo_dispositivo, assertiva_com_nexo, caput_texto=caput_texto, num_art=art.get("titulo", art["numero"]))
            explicacao = gerar_explicacao_humana(numero_dispositivo, text, foi_correto=True, exemplo_customizado=exemplo_ia, foi_ia=foi_ia_utilizada, nome_ia="Gemini IA", caput_texto=caput_texto)
        else:
            assertiva_final, tipo_troca = alterar_texto_para_errado(assertiva_com_nexo)
            gabarito = 0
            enunciado = construir_enunciado_com_nexo(nome_lei, rotulo_dispositivo, assertiva_final, caput_texto=caput_texto, num_art=art.get("titulo", art["numero"]))
            explicacao = gerar_explicacao_humana(numero_dispositivo, text, foi_correto=False, tipo_troca=tipo_troca, texto_modificado=assertiva_final, exemplo_customizado=exemplo_ia, foi_ia=foi_ia_utilizada, nome_ia="Gemini IA", caput_texto=caput_texto)

        try:
            conn.execute("INSERT INTO questoes(lei_id, artigo_id, disciplina_id, filtro_id, artigo_numero, conteudo, enunciado, gabarito, explicacao, origem, criada_em) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (law_id, art["id"], discipline_id, filter_id, numero_dispositivo, numero_dispositivo, enunciado, gabarito, explicacao, motor_ia, now))
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
    conn.execute("INSERT INTO respostas(usuario_id, questao_id, resposta, acertou, respondida_em, ciclo) VALUES(?, ?, ?, ?, ?, ?)", (USER_ID, question_id, answer, correct, now.isoformat(), cycle))
    old = conn.execute("SELECT * FROM revisoes WHERE usuario_id=? AND questao_id=?", (USER_ID, question_id)).fetchone()
    errors = (old["erros"] + (0 if correct else 1)) if old else (0 if correct else 1)
    hits = (old["acertos"] + (1 if correct else 0)) if old else (1 if correct else 0)
    priority = min(10, (old["prioridade"] if old else 1) + 2) if not correct else max(0, (old["prioridade"] if old else 1) - 1)
    intervals = [1, 3, 7, 15, 30]
    next_date = now if not correct else now + timedelta(days=intervals[min(len(intervals)-1, hits-1)])
    conn.execute("INSERT OR REPLACE INTO revisoes(usuario_id, questao_id, prioridade, proxima_revisao, erros, acertos) VALUES(?, ?, ?, ?, ?, ?)", (USER_ID, question_id, priority, next_date.isoformat(), errors, hits))
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
    b_disc = pd.read_sql_query("SELECT d.nome disciplina, COUNT(r.id) respondidas, COALESCE(SUM(r.acertou),0) acertos, COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros, ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual FROM respostas r JOIN questoes q ON q.id=r.questao_id JOIN disciplinas d ON d.id=q.disciplina_id WHERE r.usuario_id = ? GROUP BY d.id ORDER BY percentual", conn, params=(USER_ID,))
    b_filt = pd.read_sql_query("SELECT f.nome filtro, d.nome disciplina, l.nome lei, COUNT(r.id) respondidas, COALESCE(SUM(r.acertou),0) acertos, COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros, ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual FROM respostas r JOIN questoes q ON q.id=r.questao_id JOIN filtros_salvos f ON f.id=q.filtro_id JOIN disciplinas d ON d.id=f.disciplina_id JOIN leis l ON l.id=f.lei_id WHERE r.usuario_id = ? GROUP BY f.id ORDER BY r.id DESC", conn, params=(USER_ID,))
    b_cont = pd.read_sql_query("SELECT d.nome disciplina, q.conteudo, COUNT(r.id) respondidas, COALESCE(SUM(r.acertou),0) acertos, COUNT(r.id)-COALESCE(SUM(r.acertou),0) erros, ROUND(COALESCE(SUM(r.acertou),0)*100.0/COUNT(r.id),1) percentual FROM respostas r JOIN questoes q ON q.id=r.questao_id JOIN disciplinas d ON d.id=q.disciplina_id WHERE r.usuario_id = ? GROUP BY d.id,q.conteudo ORDER BY percentual", conn, params=(USER_ID,))
    due = conn.execute("SELECT COUNT(*) n FROM revisoes WHERE usuario_id = ? AND proxima_revisao <= ?", (USER_ID, datetime.now().isoformat())).fetchone()["n"]
    conn.close()
    return total, hits, errors, pct, b_disc, b_filt, b_cont, due

# ==============================================================================
# INTERFACE DO USUÁRIO (STREAMLIT)
# ==============================================================================
with st.sidebar:
    st.markdown(f"👤 Utilizador: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state.clear()
        st.rerun()
    st.divider()

    st.markdown("### 🤖 Inteligência Artificial (IA)")
    chave_gemini_detectada = obter_chave_gemini()
    st.caption(f"Status: **{'🟢 Ativa (Gemini)' if chave_gemini_detectada else '⚪ Modo Contextual'}**")

    with st.expander("🔑 Chave API Gemini", expanded=(not bool(chave_gemini_detectada))):
        nova_chave = st.text_input("GEMINI_API_KEY:", value=st.session_state.get("gemini_api_key", chave_gemini_detectada or ""), type="password")
        if st.button("Salvar Chave"):
            if nova_chave.strip():
                st.session_state["gemini_api_key"] = nova_chave.strip()
                st.success("Chave salva!")
                st.rerun()
            else:
                st.session_state.pop("gemini_api_key", None)
                st.info("Chave removida.")
                st.rerun()
        st.caption("Obtenha grátis em [Google AI Studio](https://aistudio.google.com/app/apikey)")

    auto_ia = st.toggle("⚡ Gerar IA ao responder", value=st.session_state.get("auto_ia_responder", True), key="toggle_auto_ia")
    st.session_state["auto_ia_responder"] = auto_ia
    st.divider()

    if is_admin_user:
        st.subheader("⚙ Atalho Admin")
        with st.expander("👥 Gerir Utilizadores", expanded=False):
            for u in listar_usuarios():
                st.markdown(f"**{u['username']}**")
                c_status, c_del = st.columns([3, 1])
                if u['username'].strip().lower() != ADMIN_EMAIL:
                    novo_status = c_status.toggle("Autorizado", value=bool(u['autorizado']), key=f"aut_side_{u['id']}")
                    if novo_status != bool(u['autorizado']):
                        alterar_status_autorizacao(u['id'], 1 if novo_status else 0)
                        st.rerun()
                    if c_del.button("❌", key=f"del_side_{u['id']}"):
                        excluir_usuario(u['id'])
                        st.rerun()
                st.divider()

st.title("⚖ Decorando Lei Seca")

tabs_list = ["📚 Importar Leis", "🎯 Criar Caderno / Filtro", "📝 Resolver Questões", "📊 Desempenho", "🔄 Revisões"]
if is_admin_user:
    tabs_list.append("🛡 Painel Admin")
tabs = st.tabs(tabs_list)

with tabs[0]:
    st.header("Importar Nova Lei (PDF)")
    discs = get_disciplines()
    col1, col2 = st.columns(2)
    with col1:
        new_disc = st.text_input("Nova Disciplina:")
        if st.button("Cadastrar Disciplina") and new_disc:
            add_discipline(new_disc)
            st.success(f"Disciplina '{new_disc}' cadastrada!")
            st.rerun()
    with col2:
        disc_sel = st.selectbox("Selecione a Disciplina:", [""] + [d["nome"] for d in discs])

    law_title = st.text_input("Nome da Lei:")
    uploaded_file = st.file_uploader("Ficheiro PDF da lei", type=["pdf"])
    if st.button("Processar e Salvar Lei"):
        if disc_sel and law_title and uploaded_file:
            disc_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            file_path = PDF_DIR / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            law_id = add_law(disc_id, law_title, uploaded_file.name)
            qtd = parse_and_store_pdf(file_path, law_id)
            st.success(f"Lei processada! {qtd} dispositivos fragmentados importados.")
        else:
            st.error("Preencha todos os campos e envie o PDF.")

    st.divider()
    for l in get_laws():
        lc1, lc2 = st.columns([4, 1])
        lc1.write(f"📄 **{l['nome']}** _({l['disciplina_nome']})_")
        if lc2.button("Excluir", key=f"del_law_{l['id']}"):
            delete_law(l['id'])
            st.rerun()

with tabs[1]:
    st.header("Criar Caderno de Questões por Filtro")
    discs = get_disciplines()
    disc_dict = {d["nome"]: d["id"] for d in discs}
    disc_f = st.selectbox("1. Selecione a Disciplina", [""] + list(disc_dict.keys()), key="f_disc")
    if disc_f:
        laws = get_laws(disc_dict[disc_f])
        law_dict = {l["nome"]: l["id"] for l in laws}
        law_f = st.selectbox("2. Selecione a Lei", [""] + list(law_dict.keys()), key="f_law")
        if law_f:
            articles = get_articles(law_dict[law_f])
            art_dict = {f"{a['numero']} - {a['texto'][:60]}...": a["id"] for a in articles}
            selected_arts = st.multiselect("3. Selecione os Dispositivos (vazio para TODOS):", list(art_dict.keys()))
            total_sel = len(selected_arts) if selected_arts else len(articles)
            qtd_q = st.number_input("4. Quantidade de questões:", min_value=1, max_value=500, value=max(total_sel * 2, 10))
            motor_ia = st.radio("5. Motor de Geração:", ["♊ Gemini IA (Exemplos Reais)", "⚙️ Motor Contextual"])
            filter_name = st.text_input("6. Nome do Caderno:")
            if st.button("Salvar Caderno e Gerar Questões", type="primary") and filter_name:
                prog = st.progress(0, text="Gerando questões fragmentadas...")
                f_id = save_filter(filter_name, disc_dict[disc_f], law_dict[law_f], [art_dict[k] for k in selected_arts], qtd_q)
                geradas = generate_questions_for_articles(disc_dict[disc_f], law_dict[law_f], [art_dict[k] for k in selected_arts], qtd_q, filter_id=f_id, motor_ia=motor_ia, progress_callback=lambda p, t: prog.progress(p, text=t))
                prog.progress(1.0, text="Concluído!")
                st.success(f"Caderno '{filter_name}' criado com {geradas} questões geradas!")

    st.divider()
    for mf in get_saved_filters():
        fc1, fc2 = st.columns([4, 1])
        fc1.write(f"📁 **{mf['nome']}** _({mf['disciplina']} - {mf['lei']})_")
        if fc2.button("Excluir", key=f"del_filt_{mf['id']}"):
            delete_filter(mf['id'])
            st.rerun()

with tabs[2]:
    st.header("Resolver Questões")
    disc_options = {"Todas as Disciplinas": None}
    for d in get_disciplines():
        disc_options[d["nome"]] = d["id"]
    sel_disc = st.selectbox("Selecione a Disciplina:", list(disc_options.keys()), key="res_disc")
    saved_filters = get_saved_filters(disc_options[sel_disc])
    if saved_filters:
        f_options = {f"{f['nome']} ({f['disciplina']} - {f['lei']})": f["id"] for f in saved_filters}
        sel_f = st.selectbox("Selecione o Caderno:", list(f_options.keys()))
        sel_f_id = f_options[sel_f]

        if "last_filter_id" not in st.session_state or st.session_state["last_filter_id"] != sel_f_id:
            st.session_state["last_filter_id"] = sel_f_id
            st.session_state["q_index"] = 0
            st.session_state["answered_q"] = {}

        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=? ORDER BY id", (sel_f_id,)).fetchall()
        conn.close()

        if questoes:
            idx = st.session_state.get("q_index", 0)
            if idx >= len(questoes):
                st.success("🎉 Concluiu todas as questões deste caderno!")
                if st.button("Reiniciar"):
                    st.session_state["q_index"] = 0
                    st.session_state["answered_q"] = {}
                    st.rerun()
            else:
                q = questoes[idx]
                st.subheader(f"Questão {idx + 1} de {len(questoes)}")
                st.markdown(f"**Dispositivo:** `{obter_rotulo_dispositivo(q['artigo_numero'])}`")
                
                caput_text = obter_texto_caput(q["artigo_id"])
                if caput_text:
                    with st.expander("📜 Contexto: Artigo Principal (Caput)", expanded=False):
                        st.write(f"_{caput_text}_")

                st.markdown(q["enunciado"])
                q_id = q["id"]
                ja_resp = q_id in st.session_state.get("answered_q", {})
                resp = st.radio("A sua resposta:", ["Certo", "Errado"], key=f"q_{q_id}", disabled=ja_resp)

                if not ja_resp:
                    if st.button("Responder", key=f"btn_{q_id}", type="primary"):
                        val = 1 if resp == "Certo" else 0
                        acertou = record_answer(q_id, val, cycle=1)
                        st.session_state["answered_q"][q_id] = {"acertou": acertou, "resposta": resp}
                        
                        if obter_chave_gemini() and st.session_state.get("auto_ia_responder", True) and "✨ Gerado com" not in (q["explicacao"] or ""):
                            trechos = re.findall(r'"([^"]+)"', q["enunciado"])
                            t_lei = trechos[-1] if trechos else q["enunciado"]
                            novo_ex = gerar_exemplo_gemini(obter_rotulo_dispositivo(q['artigo_numero']), t_lei)
                            if novo_ex:
                                nova_exp = gerar_explicacao_humana(q['artigo_numero'], t_lei, foi_correto=(val == q["gabarito"]), exemplo_customizado=novo_ex, foi_ia=True, caput_texto=caput_text)
                                st.session_state[f"custom_explicacao_{q_id}"] = nova_exp
                                conn_u = db()
                                conn_u.execute("UPDATE questoes SET explicacao = ? WHERE id = ?", (nova_exp, q_id))
                                conn_u.commit()
                                conn_u.close()
                        st.rerun()
                else:
                    dados_resp = st.session_state["answered_q"][q_id]
                    if dados_resp["acertou"]:
                        st.markdown('<div style="background-color: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 10px; padding: 12px; margin-bottom: 12px; color: #065f46; font-weight: 700;">✨ Parabéns! Resposta Correta!</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="background-color: #fff1f2; border: 1px solid #fecdd3; border-radius: 10px; padding: 12px; margin-bottom: 12px; color: #9f1239; font-weight: 700;">❌ Resposta Incorreta!</div>', unsafe_allow_html=True)
                    
                    # CORREÇÃO CRUCIAL APLICADA: Uso de unsafe_allow_html=True para renderizar o cartão HTML perfeitamente
                    st.markdown(st.session_state.get(f"custom_explicacao_{q_id}", q['explicacao']), unsafe_allow_html=True)
                    
                    if st.button("Próxima Questão ➡️", key=f"next_{q_id}", type="primary"):
                        st.session_state["q_index"] += 1
                        st.rerun()

with tabs[3]:
    st.header("O seu Desempenho")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")
    if not b_filt.empty:
        st.dataframe(b_filt, use_container_width=True)
    if st.button("Zerar Histórico"):
        zerar_historico_dashboard()
        st.rerun()

with tabs[4]:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    st.metric("Pendentes para Hoje", due)
    if due > 0:
        conn = db()
        rev = conn.execute("SELECT q.* FROM revisoes r JOIN questoes q ON q.id = r.questao_id WHERE r.usuario_id = ? AND r.proxima_revisao <= ? LIMIT 1", (USER_ID, datetime.now().isoformat())).fetchone()
        conn.close()
        if rev:
            st.markdown(f"**Dispositivo:** `{obter_rotulo_dispositivo(rev['artigo_numero'])}`")
            st.markdown(rev["enunciado"])
            resp_r = st.radio("Resposta:", ["Certo", "Errado"], key=f"rev_{rev['id']}")
            if st.button("Enviar Revisão", type="primary"):
                record_answer(rev['id'], 1 if resp_r == "Certo" else 0, cycle=2)
                st.markdown(rev['explicacao'], unsafe_allow_html=True)
                st.rerun()

if is_admin_user:
    with tabs[5]:
        st.header("🛡 Painel Admin")
        for u in listar_usuarios():
            st.write(fulername := f"Utilizador: **{u['username']}**")
            if u['username'].strip().lower() != ADMIN_EMAIL:
                if st.button("Excluir", key=f"adm_del_{u['id']}"):
                    excluir_usuario(u['id'])
                    st.rerun()