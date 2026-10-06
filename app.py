import hashlib
import json
import os
import random
import re
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

import fitz  # PyMuPDF
import pandas as pd
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

# Estilização CSS aprimorada para justificar os textos e alinhar o layout
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
    
    /* Cartão de destaque para o fragmento estudado */
    .fragmento-card {
        background-color: #f8fafc;
        border-left: 4px solid #3b82f6;
        padding: 14px 18px;
        border-radius: 6px;
        margin-bottom: 15px;
    }

    /* Garante que o botão de alternar/expandir a sidebar permaneça sempre visível */
    [data-testid="stSidebarCollapseButton"] {display: block !important; visibility: visible !important;}
    [data-testid="stHeader"] {background-color: transparent !important; z-index: 999;}
    </style>
""", unsafe_allow_html=True)

# Regex universal para algarismos romanos de I até CCC (1 a 300+)
REGEX_ROMANO = r'(?:M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{1,3}))'

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
                    st.warning("⚠️ A sua conta aguarda aprovação do administrador. Entre em contacto para liberação.")
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

with st.sidebar:
    st.markdown(f"👤 Utilizador: **{USERNAME}**")
    if st.button("🚪 Sair / Logout"):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()
    st.divider()

    if is_admin_user:
        st.subheader("⚙ Atalho Admin")
        with st.expander("👥 Gerir Utilizadores", expanded=False):
            usuarios_cadastrados = listar_usuarios()
            st.write(f"**Total de utilizadores:** {len(usuarios_cadastrados)}")
            for u in usuarios_cadastrados:
                st.markdown(f"**{u['username']}**")
                c_status, c_del = st.columns([3, 1])
                is_this_admin = u['username'].strip().lower() == ADMIN_EMAIL
                if is_this_admin:
                    c_status.caption("👑 Admin Principal")
                else:
                    status_atual = bool(u['autorizado'])
                    novo_status = c_status.toggle("Autorizado", value=status_atual, key=f"aut_side_{u['id']}")
                    if novo_status != status_atual:
                        alterar_status_autorizacao(u['id'], 1 if novo_status else 0)
                        st.toast(f"Status de {u['username']} alterado!")
                        st.rerun()
                    if c_del.button("❌", key=f"del_side_{u['id']}", help="Excluir Utilizador"):
                        excluir_usuario(u['id'])
                        st.success(f"Utilizador {u['username']} removido!")
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

# ==============================================================================
# MOTOR DE ESTRUTURAÇÃO E FRAGMENTAÇÃO INTELIGENTE (CORRIGIDO E AMPLIADO)
# ==============================================================================

def normalizar_estrutura_dispositivo(texto):
    """
    Normaliza o texto do dispositivo legal para que cada parágrafo, inciso ou alínea
    inicie em uma nova linha com padrão limpo. Suporta algarismos romanos de I a CCC+.
    """
    if not texto:
        return ""

    texto = texto.replace("\r", "\n")
    texto = re.sub(r'[ \t]+', ' ', texto)

    # Quebra linha antes de Parágrafos
    texto = re.sub(r'\s+(§\s*\d+º?|Parágrafo único)\s*', r'\n\1 ', texto, flags=re.IGNORECASE)

    # Quebra linha antes de Incisos (suporta I até LXXIX e além!)
    padrao_inciso = rf'\s+(?={REGEX_ROMANO}\s*[-–—]\s*)'
    texto = re.sub(padrao_inciso, '\n', texto, flags=re.IGNORECASE)

    # Quebra linha antes de Alíneas (a) -, b) -, c) -)
    texto = re.sub(r'\s+(?=[a-z]\s*[\)\-]\s*)', '\n', texto, flags=re.IGNORECASE)

    # Quebra linha antes de itens numéricos (1., 2., 1 -)
    texto = re.sub(r'(?<=[;])\s+(?=\d+[\)\.-]\s*)', '\n', texto)

    texto = re.sub(r'\n{2,}', '\n', texto)
    return texto.strip()

def eh_marcador_paragrafo(linha):
    return bool(re.match(r'^(§\s*\d+º?|Parágrafo único)\b', linha.strip(), re.IGNORECASE))

def eh_marcador_inciso(linha):
    # Regex universal para incisos em numeração romana (I, II, ..., XLVIII, LXXIX, etc.)
    return bool(re.match(rf'^{REGEX_ROMANO}\s*[-–—\.]\s*', linha.strip(), re.IGNORECASE))

def eh_marcador_alinea(linha):
    return bool(re.match(r'^[a-z]\s*[\)\-]\s*', linha.strip(), re.IGNORECASE))

def extrair_blocos_por_marcador(texto, tipo):
    """
    Extrai blocos estruturados (marcador, conteúdo) linha por linha.
    """
    linhas = [l.strip() for l in texto.split('\n') if l.strip()]
    if not linhas:
        return []

    if tipo == 'paragrafo':
        matcher = eh_marcador_paragrafo
    elif tipo == 'inciso':
        matcher = eh_marcador_inciso
    else:
        matcher = eh_marcador_alinea

    blocos = []
    atual_marcador = None
    atual_texto = []

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
            else:
                blocos.append((None, linha))

    if atual_marcador is not None:
        blocos.append((atual_marcador, ' '.join(atual_texto).strip()))

    return [(m, t) for m, t in blocos if t.strip()]

def fragmentar_texto_muito_longo(rotulo_base, texto, max_chars=450):
    """
    Se mesmo um inciso ou parágrafo específico for excepcionalmente extenso
    (ex: mais de 450 caracteres), fragmenta por orações/períodos para garantir
    que a leitura da questão seja rápida, objetiva e confortável.
    """
    texto = texto.strip()
    if len(texto) <= max_chars:
        return [{'numero': rotulo_base, 'texto': texto}]

    # Tenta quebrar por ponto e vírgula ou por períodos com sentido completo
    partes = [p.strip() for p in re.split(r'(?<=;)\s+|(?<=\.)\s+', texto) if len(p.strip()) > 15]
    if len(partes) <= 1:
        return [{'numero': rotulo_base, 'texto': texto}]

    resultado = []
    acumulado = ""
    parte_idx = 1
    for p in partes:
        if len(acumulado) + len(p) + 1 <= max_chars:
            acumulado = f"{acumulado} {p}".strip()
        else:
            if acumulado:
                resultado.append({
                    'numero': f"{rotulo_base} (trecho {parte_idx})",
                    'texto': acumulado
                })
                parte_idx += 1
            acumulado = p

    if acumulado:
        resultado.append({
            'numero': f"{rotulo_base} (trecho {parte_idx})" if parte_idx > 1 else rotulo_base,
            'texto': acumulado
        })

    return resultado if resultado else [{'numero': rotulo_base, 'texto': texto}]

def fracionar_artigo_extenso(num_art, corpo_limpo):
    """
    FRAGMENTAÇÃO INTELIGENTE:
    Separa de forma completa qualquer artigo com parágrafos, incisos e alíneas.
    Resolve definitivamente o problema de agrupar dezenas de incisos no caput
    (como ocorria nos incisos XXI ao LXXIX do Art. 5º).
    """
    texto = normalizar_estrutura_dispositivo(corpo_limpo)

    # Identifica parágrafos e incisos
    paragrafos = extrair_blocos_por_marcador(texto, 'paragrafo')
    incisos = extrair_blocos_por_marcador(texto, 'inciso')

    # Se o artigo NÃO possui parágrafos nem incisos:
    if len(paragrafos) == 0 and len(incisos) == 0:
        # Se for curto, retorna direto. Se for muito extenso, fragmenta por trecho
        if len(corpo_limpo) > 500:
            return fragmentar_texto_muito_longo(f"{num_art} (caput)", corpo_limpo)
        return [{'numero': f"{num_art} (caput)" if len(corpo_limpo) > 100 else num_art, 'texto': corpo_limpo.strip()}]

    alvos = []

    # 1. Extrai o CAPUT (texto antes do primeiro parágrafo ou inciso)
    marcadores = []
    padroes_primeiro = [
        r'(?m)^§\s*\d+º?',
        r'(?m)^Parágrafo único\b',
        rf'(?m)^{REGEX_ROMANO}\s*[-–—\.]\s*'
    ]
    for padrao in padroes_primeiro:
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            marcadores.append(m.start())

    if marcadores:
        inicio = texto[:min(marcadores)].strip()
    else:
        inicio = texto.strip()

    # Se houver caput independente, adiciona como item de questão próprio
    if inicio and len(inicio) > 10:
        # Remove eventuais numerações residuais
        inicio_limpo = re.sub(r'^Art\.\s*\d+[\w\-]*[\.\º\ª]?\s*[-–—]?\s*', '', inicio, flags=re.IGNORECASE).strip()
        if inicio_limpo:
            alvos.append({'numero': f'{num_art} (caput)', 'texto': inicio_limpo})

    # 2. Extrai INCISOS DO CAPUT (antes de qualquer parágrafo)
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
            num_formatado = f'{num_art}, Inciso {marcador.rstrip("-–—.").strip()}'
            
            # Se o inciso possui alíneas internas (a, b, c...), fragmenta cada alínea se for longo!
            texto_inciso_norm = normalizar_estrutura_dispositivo(texto_inciso)
            alineas = extrair_blocos_por_marcador(texto_inciso_norm, 'alinea')
            
            if len(alineas) > 0 and len(texto_inciso) > 250:
                # Adiciona cada alínea como dispositivo individual
                for marc_al, txt_al in alineas:
                    num_al = f"{num_formatado}, alínea {marc_al.rstrip(')-').strip()}"
                    alvos.append({'numero': num_al, 'texto': f"{marc_al} {txt_al}".strip()})
                    numeros_existentes.add(num_al)
            else:
                alvos.append({'numero': num_formatado, 'texto': f'{marcador} {texto_inciso}'.strip()})
                numeros_existentes.add(num_formatado)

    # 3. Extrai PARÁGRAFOS e seus eventuais incisos/alíneas internos
    for marcador_par, texto_par in paragrafos:
        if not marcador_par or not texto_par or len(texto_par) <= 5:
            continue

        texto_par_estruturado = normalizar_estrutura_dispositivo(texto_par)
        
        # Verifica se o parágrafo possui incisos ou alíneas
        incisos_do_paragrafo = extrair_blocos_por_marcador(texto_par_estruturado, 'inciso')
        alineas_do_paragrafo = extrair_blocos_por_marcador(texto_par_estruturado, 'alinea')

        if incisos_do_paragrafo and len(texto_par) > 250:
            for marc_inc, txt_inc in incisos_do_paragrafo:
                num_sub = f'{num_art}, {marcador_par}, Inciso {marc_inc.rstrip("-–—.").strip()}'
                alvos.append({'numero': num_sub, 'texto': f'{marc_inc} {txt_inc}'.strip()})
                numeros_existentes.add(num_sub)
        elif alineas_do_paragrafo and len(texto_par) > 250:
            for marc_al, txt_al in alineas_do_paragrafo:
                num_sub = f'{num_art}, {marcador_par}, alínea {marc_al.rstrip(")-").strip()}'
                alvos.append({'numero': num_sub, 'texto': f'{marc_al} {txt_al}'.strip()})
                numeros_existentes.add(num_sub)
        else:
            num_par = f'{num_art}, {marcador_par}'
            alvos.append({'numero': num_par, 'texto': f'{marcador_par} {texto_par}'.strip()})
            numeros_existentes.add(num_par)

    # 4. Varredura de segurança para incisos posteriores
    todos_incisos = extrair_blocos_por_marcador(texto, 'inciso')
    for marcador, texto_inciso in todos_incisos:
        if marcador and texto_inciso and len(texto_inciso) > 5:
            numero = f'{num_art}, Inciso {marcador.rstrip("-–—.").strip()}'
            if numero not in numeros_existentes:
                alvos.append({'numero': numero, 'texto': f'{marcador} {texto_inciso}'.strip()})
                numeros_existentes.add(numero)

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
    else:
        artigo_regex_alt = re.compile(r'(Art\.\s*\d+[\w\-]*[\.\º\ª]?)', re.IGNORECASE)
        partes = artigo_regex_alt.split(full_text)
        for i in range(1, len(partes), 2):
            num_art = partes[i].strip()
            corpo_art = partes[i + 1] if (i + 1) < len(partes) else ""
            corpo_limpo = limpar_e_formatar_texto_lei(corpo_art)
            if corpo_limpo and len(corpo_limpo) > 10:
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

def obter_texto_caput(artigo_id):
    """
    Retorna apenas o texto do caput (excluindo os incisos e parágrafos)
    para servir de contexto transparente na questão fragmentada.
    """
    if not artigo_id:
        return None
    conn = db()
    artigo = conn.execute("SELECT texto FROM artigos WHERE id = ?", (artigo_id,)).fetchone()
    conn.close()
    if artigo and artigo["texto"]:
        texto_limpo = limpar_e_formatar_texto_lei(artigo["texto"])
        texto_normalizado = normalizar_estrutura_dispositivo(texto_limpo)
        
        m = re.search(
            rf'(?m)^(?:§\s*\d+º?|Parágrafo único\b|{REGEX_ROMANO}\s*[-–—\.]\s*)', 
            texto_normalizado, 
            re.IGNORECASE
        )
        if m:
            caput = texto_normalizado[:m.start()].strip()
        else:
            caput = texto_normalizado.strip()
            
        return caput if caput else texto_normalizado.strip()
    return None

def alterar_texto_para_errado(texto):
    substituicoes = [
        (r'\bdeverá\b', 'poderá', 'troca de obrigação ("deverá") por faculdade ("poderá")'),
        (r'\bpoderá\b', 'deverá', 'troca de faculdade ("poderá") por obrigação ("deverá")'),
        (r'\b24 \(vinte e quatro\) horas\b', '48 (quarenta e oito) horas', 'alteração de prazo legal de 24h para 48h'),
        (r'\b48 \(quarenta e oito\) horas\b', '24 (vinte e quatro) horas', 'alteração de prazo legal de 48h para 24h'),
        (r'\b72 \(setenta e duas\) horas\b', '24 (vinte e quatro) horas', 'alteração de prazo legal de 72h para 24h'),
        (r'\b12 \(doze\) horas\b', '24 (vinte e quatro) horas', 'alteração do prazo de 12h para 24h'),
        (r'\b30 \(trinta\) dias\b', '15 (quinze) dias', 'alteração de prazo legal de 30 para 15 dias'),
        (r'\b15 \(quinze\) dias\b', '30 (trinta) dias', 'alteração de prazo legal de 15 para 30 dias'),
        (r'\bpermitido\b', 'vedado', 'inversão de permissão para proibição'),
        (r'\bvedado\b', 'permitido', 'inversão de proibição para permissão'),
        (r'\bexigido\b', 'dispensado', 'troca de exigência por dispensa'),
        (r'\bdispensado\b', 'exigido', 'troca de dispensa por exigência'),
        (r'\bobrigatório\b', 'facultativo', 'troca de obrigatório por facultativo'),
        (r'\bfacultativo\b', 'obrigatório', 'troca de facultativo por obrigatório'),
        (r'\bindependentemente de autorização judicial\b', 'mediante prévia autorização judicial', 'exigência indevida de autorização judicial'),
        (r'\bmediante autorização judicial\b', 'independentemente de autorização judicial', 'supressão indevida da reserva de jurisdição'),
        (r'\bsalvo em caso de guerra declarada\b', 'mesmo em caso de guerra declarada', 'supressão da exceção constitucional'),
        (r'\bcom prévia autorização\b', 'independentemente de prévia autorização', 'inversão do requisito de prévia autorização'),
        (r'\bpresunção de inocência\b', 'presunção de culpabilidade', 'inversão da garantia da presunção de inocência')
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

def obter_rotulo_dispositivo(numero_dispositivo):
    num_lower = numero_dispositivo.lower()

    if "alínea" in num_lower or "alinea" in num_lower:
        return f"Alínea ({numero_dispositivo})"
    elif "§" in num_lower or "parágrafo" in num_lower or "paragrafo" in num_lower:
        return f"Parágrafo ({numero_dispositivo})"
    elif "inciso" in num_lower or re.search(rf'\b{REGEX_ROMANO}\b', numero_dispositivo, re.IGNORECASE):
        return f"Inciso ({numero_dispositivo})"
    else:
        return f"Artigo ({numero_dispositivo})"

# ==============================================================================
# GERADOR DE EXEMPLOS OBJETIVOS E PRÁTICOS CONFORME O DISPOSITIVO ESTUDADO
# ==============================================================================

def extrair_exemplo_objetivo_personalizado(art_num, texto_original):
    """
    Analisa os termos jurídicos do artigo, inciso ou parágrafo específico
    e constrói um exemplo prático, objetivo e memorável da vida real.
    """
    txt = texto_original.lower()

    if any(k in txt for k in ["pena de morte", "caráter perpétuo", "trabalhos forçados", "banimento", "cruéis"]):
        return (
            "No Brasil, o Código Penal Militar prevê pena de morte por fuzilamento apenas se houver guerra formalmente declarada. Em tempo de paz, nenhuma autoridade judicial pode aplicar pena perpétua ou de morte.",
            f"• **Aplicação no {art_num}:** Impede penas desumanas ou perpétuas no sistema penal brasileiro comum.",
            "Proteger a dignidade da pessoa humana e evitar punições estatais irreversíveis e cruéis."
        )

    if any(k in txt for k in ["extradit", "brasileiro nato", "naturalizado"]):
        return (
            "João, brasileiro nato, cometeu homicídio na Itália e fugiu para o Brasil. O Brasil jamais autorizará sua extradição, pois nato nunca é extraditado (poderá responder pelo crime perante a Justiça brasileira). Já o naturalizado só pode ser extraditado por crime comum praticado antes da naturalização ou por tráfico ilícito a qualquer tempo.",
            f"• **Aplicação no {art_num}:** Garante a prerrogativa constitucional de não extradição do brasileiro nato.",
            "Proteger os nacionais da jurisdição punitiva estrangeira em território nacional."
        )

    if any(k in txt for k in ["presidiária", "amamenta", "filhos"]):
        return (
            "Uma detenta deu à luz durante o cumprimento de pena em presídio feminino. O estabelecimento prisional é obrigado a dispor de creche/berçário para que ela amamente o bebê durante os primeiros meses.",
            f"• **Aplicação no {art_num}:** Direito subjetivo da mãe presa e do recém-nascido de permanecerem juntos durante a amamentação.",
            "Garantir a saúde, nutrição e proteção da infância do recém-nascido independentemente da condenação da mãe."
        )

    if any(k in txt for k in ["dados pessoais", "meios digitais"]):
        return (
            "Uma empresa de tecnologia ou órgão público sofre vazamento de dados de cidadãos sem consentimento. O titular pode acionar o Poder Judiciário invocando direito fundamental à proteção de dados digitais.",
            f"• **Aplicação no {art_num}:** Eleva a privacidade digital ao patamar de cláusula pétrea fundamental.",
            "Resguardar a autodeterminação informativa no ambiente cibernético."
        )

    if any(k in txt for k in ["domicílio", "casa é asilo", "inviolável"]):
        return (
            "A polícia não pode invadir a residência de um suspeito à noite sem consentimento ou flagrante delito. Durante o dia, exige-se mandado judicial prévio fundamentado.",
            f"• **Aplicação no {art_num}:** Protege a intimidade doméstica contra abusos estatais.",
            "Garantir que a residência seja um refúgio inviolável do indivíduo."
        )

    if any(k in txt for k in ["habeas corpus", "locomoção", "liberdade de ir e vir"]):
        return (
            "Um cidadão tem prisão preventiva decretada por juiz incompetente ou sem fundamentação válida. O advogado impetra habeas corpus diretamente no Tribunal para expedição imediata de alvará de soltura.",
            f"• **Aplicação no {art_num}:** Remédio constitucional de ação gratuita contra prisão ilegal ou ameaça de prisão.",
            "Restabelecer a liberdade de locomoção cerceada por abuso de poder."
        )

    if any(k in txt for k in ["mandado de segurança", "direito líquido e certo"]):
        return (
            "Um candidato aprovado em 1º lugar em concurso público dentro do número de vagas vê o prazo de validade expirar sem nomeação. Cabe Mandado de Segurança demonstrando o direito líquido e certo à posse.",
            f"• **Aplicação no {art_num}:** Protege direitos comprováveis de plano por documentos, quando não amparados por habeas corpus ou habeas data.",
            "Sanar ilegalidades administrativas evidentes com celeridade processual."
        )

    if any(k in txt for k in ["ação popular", "anular ato lesivo", "patrimônio público"]):
        return (
            "Um eleitor descobre que o prefeito do seu município contratou obra superfaturada favorecendo parente. Como cidadão no gozo dos direitos políticos, ele ingressa com Ação Popular para anular o contrato e ressarcir o erário.",
            f"• **Aplicação no {art_num}:** Instrumento de fiscalização cidadã contra imoralidade e lesão ao patrimônio coletivo.",
            "Permitir o controle social direto dos atos administrativos corruptos ou ilegais."
        )

    if any(k in txt for k in ["transitou em julgado", "culpado", "presunção"]):
        return (
            "Um réu foi condenado em primeira e segunda instância, mas interpôs recursos especial e extraordinário aos Tribunais Superiores. Ele não pode ser tratado formalmente como culpado definitivo até o julgamento final.",
            f"• **Aplicação no {art_num}:** Presunção de não culpabilidade até o trânsito em julgado.",
            "Evitar efeitos punitivos definitivos antes do esgotamento da via recursal."
        )

    if any(k in txt for k in ["sinal", "estação de cobertura", "radiofrequência"]):
        return (
            "Em uma investigação de extorsão mediante sequestro, a autoridade policial requisita a operadora as ERBs (antenas) pelas quais o celular da vítima transitou.",
            f"• **Aplicação no {art_num}:** Localização aproximada por estação de cobertura sem quebra de sigilo telefônico.",
            "Agilizar o resgate de vítimas sem demandar autorização judicial prévia para mera triangulação geográfica."
        )

    if any(k in txt for k in ["competência privativa", "decretar", "sancionar", "vetar"]):
        return (
            "O Presidente da República decide vetar parcialmente um projeto de lei aprovado pelo Congresso Nacional, fundamentando que o dispositivo é inconstitucional.",
            f"• **Aplicação no {art_num}:** Exercício privativo de prerrogativas do Chefe do Poder Executivo da União.",
            "Harmonizar o sistema de freios e contrapesos entre Executivo e Legislativo."
        )

    # Exemplo contextual padrão aprimorado
    return (
        f"Na prática jurídica cotidiana, os agentes e magistrados aplicam este dispositivo para delimitar direitos e deveres formais expressos na literalidade legal.",
        f"• **Aplicação no {art_num}:** Impõe cumprimento taxativo da previsão normativa, vedando interpretações que contrariem o texto expresso da lei.",
        "Assegurar a previsibilidade das decisões judiciais e a estabilidade das relações jurídicas."
    )

def gerar_explicacao_humana(art_num, texto_original, foi_correto=False, tipo_troca=None, texto_modificado=None):
    situacao_real, aplicacao_regra, objetivo_regra = extrair_exemplo_objetivo_personalizado(art_num, texto_original)

    if foi_correto:
        status_txt = "O item está **CORRETO**."
        detalhe_erro = "O enunciado reproduz com exatidão a literalidade da legislação."
        resumo_erro_bloco = ""
    else:
        status_txt = "O item está **ERRADO**."
        detalhe_erro = "O enunciado promoveu alteração indevida da regra legal."
        resumo_erro_bloco = f"\n\n⚠️ **Pegadinha da Questão:** {tipo_troca or 'Substituição de palavra-chave ou prazo legal'}."

    explicacao_formatada = f"""💡 **Gabarito e Justificativa:** {status_txt} {detalhe_erro}{resumo_erro_bloco}

📖 **Dispositivo Literal da Lei Seca ({art_num}):**
> "{texto_original}"

📌 **Exemplo Prático e Objetivo da Vida Real:**
{situacao_real}

{aplicacao_regra}

🎯 **Objetivo da Regra:** {objetivo_regra}
"""
    return explicacao_formatada

# ==============================================================================
# GERAÇÃO DE QUESTÕES COM FRAGMENTAÇÃO
# ==============================================================================

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

    alvos = []
    for art in arts:
        texto_artigo = limpar_e_formatar_texto_lei(art["texto"])
        alvos_artigo = fracionar_artigo_extenso(art["numero"], texto_artigo)
        for alvo in alvos_artigo:
            alvos.append({
                "art": art,
                "numero": alvo["numero"],
                "texto": alvo["texto"]
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
        rotulo_dispositivo = obter_rotulo_dispositivo(numero_dispositivo)
        text = limpar_e_formatar_texto_lei(alvo["texto"])
        is_correct = random.choice([True, False])

        if "Ollama" in motor_ia:
            import requests
            try:
                prompt = (
                    "Crie uma questão Certo/Errado curta baseada EXCLUSIVAMENTE no trecho literal "
                    f"do {rotulo_dispositivo}. Preserve o sentido jurídico e não invente informações.\n\n"
                    f"{text}"
                )
                res = requests.post("http://localhost:11434/api/generate", json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False
                }, timeout=5)
                data = res.json()
                enunciado = data.get("response", f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\"")
                gabarito = 1 if is_correct else 0
                explicacao = gerar_explicacao_humana(numero_dispositivo, text, is_correct)
            except Exception:
                if is_correct:
                    enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\""
                    gabarito = 1
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, True)
                else:
                    modified_text, tipo_troca = alterar_texto_para_errado(text)
                    enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{modified_text}\""
                    gabarito = 0
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, False, tipo_troca, modified_text)

        elif "Gemini" in motor_ia:
            gemini_key = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY"))
            if gemini_key and genai:
                try:
                    prompt = (
                        "Você é uma banca examinadora de concursos públicos. "
                        "Crie uma afirmação de Certo ou Errado focada estritamente no trecho da lei fornecido. "
                        "Mantenha o enunciado conciso e direto. Não invente informações.\n\n"
                        f"Dispositivo: {rotulo_dispositivo}\n"
                        f"Texto legal: {text}\n"
                        f"Gabarito pretendido: {'CERTO' if is_correct else 'ERRADO'}"
                    )
                    
                    if hasattr(genai, "Client"):
                        client = genai.Client(api_key=gemini_key)
                        response = client.models.generate_content(
                            model="gemini-3.8-flash",
                            contents=prompt
                        )
                        enunciado = response.text
                    else:
                        genai.configure(api_key=gemini_key)
                        model = genai.GenerativeModel("gemini-3.8-flash")
                        response = model.generate_content(prompt)
                        enunciado = response.text
                        
                    gabarito = 1 if is_correct else 0
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, is_correct)
                except Exception as e:
                    logging.warning(f"Erro na API Gemini: {e}. Aplicando motor de regra padrão.")
                    if is_correct:
                        enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\""
                        gabarito = 1
                        explicacao = gerar_explicacao_humana(numero_dispositivo, text, True)
                    else:
                        modified_text, tipo_troca = alterar_texto_para_errado(text)
                        enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{modified_text}\""
                        gabarito = 0
                        explicacao = gerar_explicacao_humana(numero_dispositivo, text, False, tipo_troca, modified_text)
            else:
                if is_correct:
                    enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\""
                    gabarito = 1
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, True)
                else:
                    modified_text, tipo_troca = alterar_texto_para_errado(text)
                    enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{modified_text}\""
                    gabarito = 0
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, False, tipo_troca, modified_text)

        elif "OpenAI" in motor_ia:
            api_key = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
            if api_key and openai:
                try:
                    client = openai.OpenAI(api_key=api_key)
                    prompt_system = (
                        "Você é uma banca examinadora de concursos públicos. "
                        "Crie uma afirmação de Certo ou Errado focada estritamente no trecho da lei fornecido. "
                        "Mantenha o enunciado conciso e direto. Não invente informações."
                    )
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": prompt_system},
                            {"role": "user", "content": (
                                f"Dispositivo: {rotulo_dispositivo}\n"
                                f"Texto legal: {text}\n\n"
                                f"Gabarito pretendido: {'CERTO' if is_correct else 'ERRADO'}"
                            )}
                        ]
                    )
                    enunciado = completion.choices[0].message.content
                    gabarito = 1 if is_correct else 0
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, is_correct)
                except Exception:
                    if is_correct:
                        enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\""
                        gabarito = 1
                        explicacao = gerar_explicacao_humana(numero_dispositivo, text, True)
                    else:
                        modified_text, tipo_troca = alterar_texto_para_errado(text)
                        enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{modified_text}\""
                        gabarito = 0
                        explicacao = gerar_explicacao_humana(numero_dispositivo, text, False, tipo_troca, modified_text)
            else:
                if is_correct:
                    enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\""
                    gabarito = 1
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, True)
                else:
                    modified_text, tipo_troca = alterar_texto_para_errado(text)
                    enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{modified_text}\""
                    gabarito = 0
                    explicacao = gerar_explicacao_humana(numero_dispositivo, text, False, tipo_troca, modified_text)

        else:
            if is_correct:
                enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{text}\""
                gabarito = 1
                explicacao = gerar_explicacao_humana(numero_dispositivo, text, True)
            else:
                modified_text, tipo_troca = alterar_texto_para_errado(text)
                enunciado = f"De acordo com o **{rotulo_dispositivo}**:\n\n\"{modified_text}\""
                gabarito = 0
                explicacao = gerar_explicacao_humana(numero_dispositivo, text, False, tipo_troca, modified_text)

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

    conn.execute("""
        INSERT OR REPLACE INTO revisoes(usuario_id, questao_id, prioridade, proxima_revisao, erros, acertos)
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

st.title("⚖ Decorando Lei Seca")

is_admin_user = bool(USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL)

if is_admin_user:
    tab1, tab2, tab3, tab4, tab5, tab_admin = st.tabs([
        "📚 Importar Leis",
        "🎯 Criar Caderno / Filtro",
        "📝 Resolver Questões",
        "📊 Desempenho",
        "🔄 Revisões",
        "🛡 Painel Admin"
    ])
else:
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
        new_disc = st.text_input("Nova Disciplina (ou selecione ao lado):")
        if st.button("Cadastrar Disciplina"):
            if new_disc:
                add_discipline(new_disc)
                st.success(f"Disciplina '{new_disc}' cadastrada!")
                st.rerun()

    with col2:
        disc_sel = st.selectbox("Selecione a Disciplina:", [""] + disc_names)

    st.subheader("Upload do PDF da Lei")
    law_title = st.text_input("Nome da Lei (ex: CF/88, Código Penal, etc.):")
    uploaded_file = st.file_uploader("Escolha o ficheiro PDF da lei", type=["pdf"])

    if st.button("Processar e Salvar Lei"):
        if not disc_sel:
            st.error("Selecione uma disciplina!")
        elif not law_title:
            st.error("Informe o nome da lei!")
        elif not uploaded_file:
            st.error("Envie um ficheiro PDF!")
        else:
            disc_id = [d["id"] for d in discs if d["nome"] == disc_sel][0]
            file_path = PDF_DIR / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            law_id = add_law(disc_id, law_title, uploaded_file.name)
            qtd = parse_and_store_pdf(file_path, law_id)
            st.success(f"Lei processada com sucesso! {qtd} artigos importados.")

    st.divider()
    st.subheader("🗑 Leis Cadastradas por Disciplina")
    todas_leis = get_laws()
    if todas_leis:
        leis_por_disciplina = {}
        for l in todas_leis:
            disc_nome = l['disciplina_nome']
            if disc_nome not in leis_por_disciplina:
                leis_por_disciplina[disc_nome] = []
            leis_por_disciplina[disc_nome].append(l)

        for disc_nome, lista_leis in leis_por_disciplina.items():
            with st.expander(f"📚 **{disc_nome}** ({len(lista_leis)} Lei(s))", expanded=False):
                for l in lista_leis:
                    lc1, lc2 = st.columns([4, 1])
                    lc1.write(f"📄 **{l['nome']}**")
                    if lc2.button("Excluir Lei", key=f"del_law_{l['id']}"):
                        delete_law(l['id'])
                        st.success(f"Lei '{l['nome']}' excluída com sucesso!")
                        st.rerun()
    else:
        st.info("Nenhuma lei cadastrada ainda.")

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
            art_dict = {f"{a['numero']} - {a['texto'][:60]}...": a["id"] for a in articles}
            
            selected_arts = st.multiselect("3. Selecione os Artigos/Trechos (deixe vazio para TODOS):", list(art_dict.keys()))
            
            total_arts_selecionados = len(selected_arts) if selected_arts else len(articles)
            sugestao_qtd = max(total_arts_selecionados * 2, 10)
            
            st.info(f"💡 **Sugestão do Sistema:** Esta lei/seleção possui **{total_arts_selecionados} artigo(s)/dispositivo(s)**.")

            qtd_q = st.number_input(
                "4. Quantidade de questões para este filtro:",
                min_value=total_arts_selecionados if total_arts_selecionados > 0 else 1,
                max_value=500,
                value=sugestao_qtd
            )
            
            motor_ia = st.radio(
                "5. Selecione o Motor para Geração de Questões:",
                ["⚙️ Regra Padrão", "🦙 Ollama (Local)", "🤖 OpenAI (Nuvem)", "♊ Gemini (Nuvem)"]
            )

            filter_name = st.text_input("6. Nome do seu Caderno / Filtro:")

            if st.button("Salvar Caderno e Gerar Questões"):
                if not filter_name:
                    st.error("Informe um nome para o seu caderno!")
                else:
                    with st.spinner("Aguarde sincronização... Gerando questões fragmentadas e estruturando o caderno..."):
                        art_ids = [art_dict[k] for k in selected_arts]
                        f_id = save_filter(filter_name, d_id, l_id, art_ids, qtd_q)
                        qtd_geradas = generate_questions_for_articles(d_id, l_id, art_ids, qtd_q, filter_id=f_id, motor_ia=motor_ia)
                    st.success(f"Caderno '{filter_name}' criado com sucesso! {qtd_geradas} questões fragmentadas geradas.")

    st.divider()
    st.subheader("🗑 Meus Cadernos / Filtros Salvos por Disciplina")
    meus_filtros = get_saved_filters()
    
    if meus_filtros:
        filtros_por_disciplina = {}
        for mf in meus_filtros:
            disc = mf['disciplina']
            if disc not in filtros_por_disciplina:
                filtros_por_disciplina[disc] = []
            filtros_por_disciplina[disc].append(mf)

        for disc_nome, lista_filtros in filtros_por_disciplina.items():
            with st.expander(f"📚 **{disc_nome}** ({len(lista_filtros)} Caderno(s))", expanded=False):
                for mf in lista_filtros:
                    fc1, fc2 = st.columns([4, 1])
                    fc1.write(f"📁 **{mf['nome']}** _(Lei: {mf['lei']})_")
                    if fc2.button("Excluir Caderno", key=f"del_filt_{mf['id']}"):
                        delete_filter(mf['id'])
                        st.success(f"Caderno '{mf['nome']}' removido com sucesso!")
                        st.rerun()

# ==============================================================================
# TELA DE RESOLVER QUESTÕES (TOTALMENTE AJUSTADA COM FRAGMENTAÇÃO E EXEMPLOS)
# ==============================================================================

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
            st.session_state["answered_q"] = {}

        conn = db()
        questoes = conn.execute("SELECT * FROM questoes WHERE filtro_id=? ORDER BY id", (sel_filter_id,)).fetchall()
        conn.close()

        if not questoes:
            st.warning("Nenhuma questão gerada para este caderno.")
        else:
            if "q_index" not in st.session_state:
                st.session_state["q_index"] = 0
            if "answered_q" not in st.session_state:
                st.session_state["answered_q"] = {}

            idx = st.session_state["q_index"]
            if idx >= len(questoes):
                st.success("🎉 Concluiu todas as questões deste caderno!")
                if st.button("Reiniciar Caderno"):
                    st.session_state["q_index"] = 0
                    st.session_state["answered_q"] = {}
                    st.rerun()
            else:
                q = questoes[idx]
                st.subheader(f"Questão {idx + 1} de {len(questoes)}")
                
                num_disp = q['artigo_numero']
                rotulo_formatado = obter_rotulo_dispositivo(num_disp)
                
                col_disp, col_badge = st.columns([4, 1])
                with col_disp:
                    st.markdown(f"**Dispositivo em Estudo:** `{rotulo_formatado}`")
                with col_badge:
                    tamanho = len(q["enunciado"])
                    if tamanho < 250:
                        st.caption("⚡ Dispositivo Curto / Direto")
                    else:
                        st.caption("🧩 Dispositivo Fragmentado")

                # Se o dispositivo for um Inciso, Parágrafo ou Alínea, exibe o Caput como contexto útil
                is_subdevice = any(tag in num_disp.lower() for tag in ["§", "parágrafo", "inciso", "alínea", "alinea"]) or re.search(rf'\b{REGEX_ROMANO}\b', num_disp, re.IGNORECASE)
                if is_subdevice:
                    caput_text = obter_texto_caput(q["artigo_id"])
                    if caput_text:
                        with st.expander("📜 Contexto: Artigo Principal (Caput)", expanded=False):
                            st.write(f"_{caput_text}_")

                # Enunciado focado e delimitado
                st.markdown(q["enunciado"])

                q_id = q["id"]
                ja_respondida = q_id in st.session_state["answered_q"]

                resp = st.radio("A sua resposta:", ["Certo", "Errado"], key=f"q_{q_id}", disabled=ja_respondida)
                
                if not ja_respondida:
                    if st.button("Responder", key=f"btn_{q_id}", type="primary"):
                        val = 1 if resp == "Certo" else 0
                        acertou = record_answer(q_id, val, cycle=1)
                        st.session_state["answered_q"][q_id] = {
                            "acertou": acertou,
                            "resposta": resp
                        }
                        st.rerun()
                else:
                    dados_resp = st.session_state["answered_q"][q_id]
                    if dados_resp["acertou"]:
                        st.success("✨ Resposta Correta! Parabéns!")
                    else:
                        st.error("❌ Resposta Incorreta! Atenção aos detalhes!")

                    # Exibição da justificativa com o exemplo prático e objetivo
                    with st.container():
                        st.markdown(f"{q['explicacao']}")

                    if st.button("Próxima Questão ➡️", key=f"next_{q_id}"):
                        st.session_state["q_index"] += 1
                        st.rerun()

with tab4:
    st.header("O seu Desempenho")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Respondidas", tot)
    c2.metric("Acertos", ac)
    c3.metric("Erros", err)
    c4.metric("Aproveitamento", f"{pct:.1f}%")

    st.subheader("Desempenho por Caderno / Filtro")
    if not b_filt.empty:
        st.dataframe(b_filt, use_container_width=True)
    else:
        st.info("Nenhuma questão respondida ainda.")

    st.subheader("Desempenho por Disciplina")
    if not b_disc.empty:
        st.dataframe(b_disc, use_container_width=True)

    st.divider()
    st.subheader("⚠ Redefinir Estatísticas")
    if st.button("Zerar Histórico de Respostas / Limpar Dashboard", type="secondary"):
        zerar_historico_dashboard()
        st.success("O seu histórico de respostas e indicadores do dashboard foram zerados!")
        st.rerun()

with tab5:
    st.header("Revisão Espaçada")
    tot, ac, err, pct, b_disc, b_filt, b_cont, due = stats()
    st.metric("Questões Pendentes para Revisão Hoje", due)

    if due > 0:
        conn = db()
        agora_str = datetime.now().isoformat()
        revs = conn.execute("""
            SELECT q.* FROM revisoes r
            JOIN questoes q ON q.id = r.questao_id
            WHERE r.usuario_id = ? AND r.proxima_revisao <= ?
            ORDER BY r.proxima_revisao ASC
            LIMIT 1
        """, (USER_ID, agora_str)).fetchone()
        
        if not revs:
            revs = conn.execute("""
                SELECT q.* FROM revisoes r
                JOIN questoes q ON q.id = r.questao_id
                WHERE r.usuario_id = ?
                LIMIT 1
            """, (USER_ID,)).fetchone()
            
        conn.close()

        if revs:
            st.subheader("Questão para Revisão")
            
            num_disp = revs['artigo_numero']
            st.markdown(f"**Dispositivo:** `{obter_rotulo_dispositivo(num_disp)}`")

            is_subdevice = any(tag in num_disp.lower() for tag in ["§", "parágrafo", "inciso", "alínea", "alinea"]) or re.search(rf'\b{REGEX_ROMANO}\b', num_disp, re.IGNORECASE)
            if is_subdevice and "artigo_id" in revs.keys() and revs["artigo_id"]:
                caput_text = obter_texto_caput(revs["artigo_id"])
                if caput_text:
                    with st.expander("📜 Contexto: Artigo Principal (Caput)", expanded=False):
                        st.write(f"_{caput_text}_")

            st.markdown(revs["enunciado"])
            
            q_id_rev = revs["id"]
            resp_rev = st.radio("A sua resposta:", ["Certo", "Errado"], key=f"rev_ans_{q_id_rev}")
            
            if st.button("Enviar Resposta da Revisão", key=f"btn_rev_{q_id_rev}", type="primary"):
                val = 1 if resp_rev == "Certo" else 0
                acertou = record_answer(q_id_rev, val, cycle=2)
                if acertou:
                    st.success("✨ Excelente! Próxima revisão agendada.")
                else:
                    st.error("❌ Errou! Ela voltará para revisão em breve.")
                st.markdown(f"{revs['explicacao']}")
                st.rerun()
        else:
            st.info("Nenhuma questão detalhada encontrada para revisão neste momento.")
    else:
        st.success("Tudo em dia! Não há revisões pendentes para hoje.")

if is_admin_user:
    with tab_admin:
        st.header("🛡 Painel de Controlo do Administrador")
        st.write("Gerencie e aprove o acesso de novos utilizadores ao sistema de forma rápida e segura.")
        
        usuarios_cadastrados = listar_usuarios()
        st.info(f"**Total de utilizadores cadastrados no sistema:** {len(usuarios_cadastrados)}")
        
        st.subheader("👥 Lista de Utilizadores e Autorizações")
        for u in usuarios_cadastrados:
            with st.container(border=True):
                col_info, col_toggle, col_del = st.columns([3, 2, 1])
                
                col_info.markdown(f"**E-mail / Utilizador:** `{u['username']}`")
                col_info.caption(f"Criado em: {u['criado_em'][:10]}")
                
                is_this_admin = u['username'].strip().lower() == ADMIN_EMAIL
                
                if is_this_admin:
                    col_toggle.markdown("👑 **Administrador Principal**")
                else:
                    status_atual = bool(u['autorizado'])
                    novo_status = col_toggle.toggle("Acesso Autorizado", value=status_atual, key=f"aut_tab_{u['id']}")
                    if novo_status != status_atual:
                        alterar_status_autorizacao(u['id'], 1 if novo_status else 0)
                        st.toast(f"Status de autorização de {u['username']} atualizado com sucesso!")
                        st.rerun()

                    if col_del.button("🗑️ Excluir", key=f"del_tab_{u['id']}", help="Remover Utilizador"):
                        excluir_usuario(u['id'])
                        st.success(f"Utilizador {u['username']} removido do sistema!")
                        st.rerun()

        st.divider()
        st.subheader("➕ Criar Novo Utilizador Autorizado Diretamente")
        col_au1, col_au2 = st.columns(2)
        with col_au1:
            adm_new_u = st.text_input("E-mail do Novo Utilizador", key="adm_u_tab")
        with col_au2:
            adm_new_p = st.text_input("Palavra-passe Inicial", type="password", key="adm_p_tab")
            
        if st.button("Cadastrar e Autorizar Imediatamente", type="primary"):
            if adm_new_u and adm_new_p:
                ok, msg = cadastrar_usuario(adm_new_u, adm_new_p, autorizado=1)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("Preencha todos os campos para prosseguir.")
