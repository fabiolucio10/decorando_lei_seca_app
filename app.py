import hashlib
import json
import os
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor, Json

# Gemini é opcional. O aplicativo continua funcionando sem a chave.
try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None


# ============================================================
# CONFIGURAÇÕES
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pppe_tatico")

ADMIN_EMAIL = "fabiolucio277@gmail.com"

# Configure DATABASE_URL nas variáveis de ambiente do Render.
# Não coloque senha ou chave diretamente neste arquivo.
DATABASE_URL = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("SUPABASE_DB_URL")
    or ""
).strip()

API_KEY_ENV = os.environ.get("GEMINI_API_KEY", "").strip()

st.set_page_config(
    page_title="PPPE Tático - Preparação de Alto Rendimento",
    page_icon="🛡️",
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
[data-testid="stSidebarCollapseButton"] {
    display: block !important;
    visibility: visible !important;
}
[data-testid="stHeader"] {
    background-color: transparent !important;
    z-index: 999;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# CONEXÃO COM POSTGRESQL / SUPABASE
# ============================================================

def preparar_database_url(url):
    """
    Garante sslmode=require sem exibir ou registrar a senha.
    Não altera usuário, senha, host ou identificador do projeto.
    """
    if not url:
        return ""

    try:
        partes = urlparse(url)
        parametros = dict(parse_qsl(partes.query, keep_blank_values=True))
        parametros["sslmode"] = "require"
        nova_query = urlencode(parametros)
        return urlunparse(partes._replace(query=nova_query))
    except Exception:
        return url


def db():
    if not DATABASE_URL:
        raise RuntimeError(
            "A variável DATABASE_URL não está configurada no Render. "
            "Cadastre a URL PostgreSQL do Supabase nas Environment Variables."
        )

    url = preparar_database_url(DATABASE_URL)

    try:
        return psycopg2.connect(
            url,
            cursor_factory=RealDictCursor,
            connect_timeout=20,
            application_name="pppe_tatico"
        )
    except psycopg2.OperationalError as exc:
        mensagem = str(exc).lower()

        if "tenant" in mensagem or "user" in mensagem and "not found" in mensagem:
            orientacao = (
                "O Supabase não reconheceu o usuário/tenant informado na URL. "
                "Confira no Supabase > Connect a connection string correta. "
                "Se estiver usando o Pooler, confirme se o usuário está no formato "
                "postgres.<PROJECT-REF> e se o host, a porta e a referência do projeto "
                "pertencem ao mesmo projeto. Não invente nem acrescente o identificador: "
                "copie a URL fornecida pelo próprio Supabase."
            )
        elif "password authentication failed" in mensagem:
            orientacao = (
                "A senha do banco PostgreSQL foi recusada. Copie novamente a senha "
                "do banco nas configurações do Supabase e atualize DATABASE_URL no Render."
            )
        elif "could not translate host name" in mensagem or "name or service not known" in mensagem:
            orientacao = (
                "O endereço do servidor PostgreSQL não foi localizado. Confira o host "
                "na URL copiada do Supabase e se o projeto está ativo."
            )
        else:
            orientacao = (
                "Não foi possível conectar ao PostgreSQL. Confira DATABASE_URL, "
                "host, porta, usuário, senha e status do projeto Supabase."
            )

        logger.error("Falha de conexão PostgreSQL: %s", exc.__class__.__name__)
        raise RuntimeError(orientacao) from None


def mostrar_erro_banco(exc):
    st.error("Não foi possível acessar o banco de dados.")
    st.warning(str(exc))
    st.info(
        "No Render, abra o serviço do aplicativo → Environment → DATABASE_URL. "
        "Compare a URL com a opção Connect do projeto correto no Supabase. "
        "Não publique a URL, a senha ou as chaves em mensagens ou no GitHub."
    )


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def json_load(valor, padrao):
    if valor is None or valor == "":
        return padrao
    if isinstance(valor, (list, dict)):
        return valor
    try:
        return json.loads(valor)
    except (TypeError, json.JSONDecodeError):
        return padrao


def json_para_banco(valor):
    return Json(valor, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


def registrar_backup(cursor, tabela, registro_id, dados, acao):
    """
    Guarda uma cópia do registro ANTES de uma atualização.
    Não existe rotina automática de limpeza deste histórico.
    """
    cursor.execute("""
        INSERT INTO historico_backup
            (tabela, registro_id, dados_anteriores, acao, criado_em)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        tabela,
        str(registro_id),
        json_para_banco(dict(dados)),
        acao,
        datetime.now(timezone.utc).isoformat()
    ))


# ============================================================
# INICIALIZAÇÃO E MIGRAÇÃO SEGURA DO BANCO
# ============================================================

def init_db():
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS usuarios (
                        id SERIAL PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        senha TEXT NOT NULL,
                        autorizado INTEGER DEFAULT 0,
                        criado_em TEXT NOT NULL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conteudo_estudo (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER,
                        disciplina TEXT NOT NULL,
                        assunto TEXT NOT NULL,
                        modulo TEXT,
                        banca TEXT,
                        desc_resumo TEXT,
                        mnemonicos TEXT,
                        mapa TEXT,
                        cards TEXT,
                        prazos TEXT,
                        pegadinhas TEXT
                    );
                """)

                # Histórico de versões anteriores: não apaga conteúdo.
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS historico_backup (
                        id BIGSERIAL PRIMARY KEY,
                        tabela TEXT NOT NULL,
                        registro_id TEXT NOT NULL,
                        dados_anteriores JSONB NOT NULL,
                        acao TEXT NOT NULL,
                        criado_em TEXT NOT NULL
                    );
                """)

                # Migrações aditivas: não removem nem recriam tabelas/colunas.
                cursor.execute("""
                    ALTER TABLE usuarios
                    ADD COLUMN IF NOT EXISTS autorizado INTEGER DEFAULT 0;
                """)
                cursor.execute("""
                    ALTER TABLE conteudo_estudo
                    ADD COLUMN IF NOT EXISTS user_id INTEGER;
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_conteudo_disciplina_assunto
                    ON conteudo_estudo (disciplina, assunto);
                """)

                # Apenas garante a autorização do administrador.
                cursor.execute("""
                    UPDATE usuarios
                    SET autorizado = 1
                    WHERE LOWER(TRIM(username)) = %s
                      AND COALESCE(autorizado, 0) <> 1;
                """, (ADMIN_EMAIL,))

                # Conteúdo inicial somente se a tabela estiver realmente vazia.
                cursor.execute("SELECT COUNT(*) AS total FROM conteudo_estudo;")
                total = cursor.fetchone()["total"]

                if total == 0:
                    pegadinha_inicial = [{
                        "enunciado": (
                            "Constatado que o investigado agiu em manifesto estado "
                            "de legítima defesa, poderá o Delegado de Polícia arquivar "
                            "fundamentadamente o Inquérito Policial."
                        ),
                        "opcoes": ["CERTO", "ERRO"],
                        "gabarito": "ERRO",
                        "explicacao": (
                            "O Delegado de Polícia não pode arquivar autos de "
                            "inquérito policial (Art. 17 do CPP)."
                        )
                    }]

                    cursor.execute("""
                        INSERT INTO conteudo_estudo
                        (user_id, disciplina, assunto, modulo, banca, desc_resumo,
                         mnemonicos, mapa, cards, prazos, pegadinhas)
                        VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """, (
                        "Direito Processual Penal",
                        "Inquérito Policial (IP)",
                        "Módulo Operacional • Pacote Anticrime",
                        json.dumps(["CEBRASPE", "INSTITUTO AOCP", "FGV", "VUNESP"]),
                        "Estudo aprofundado das características, instauração e limites do Inquérito Policial.",
                        json.dumps([{
                            "termo": "IDESTA",
                            "significado": "Inquisitivo, Dispensável, Escrito, Sigiloso, Temporário e Atípico."
                        }], ensure_ascii=False),
                        json.dumps([{
                            "titulo": "Natureza Jurídica & Características",
                            "itens": [
                                "Procedimento administrativo informativo, de caráter preparatório."
                            ]
                        }], ensure_ascii=False),
                        json.dumps([{
                            "p": "O Inquérito Policial possui contraditório e ampla defesa plenos?",
                            "r": "NÃO. Por ser um procedimento administrativo de investigação (inquisitivo), não há contraditório nem ampla defesa em sentido estrito."
                        }], ensure_ascii=False),
                        json.dumps([{
                            "sit": "Regra Geral CPP (Crimes Comuns Estaduais)",
                            "preso": "10 Dias (Improrrogável)",
                            "solto": "30 Dias (Prorrogável)",
                            "prorrogacao": "Art. 10 do CPP"
                        }], ensure_ascii=False),
                        json.dumps(pegadinha_inicial, ensure_ascii=False)
                    ))

    finally:
        conn.close()


# Executa inicialização e informa falhas de conexão sem exibir credenciais.
try:
    init_db()
except Exception as erro:
    st.error("Falha ao iniciar o banco de dados do PPPE TÁTICO.")
    st.error(str(erro))
    st.info(
        "Verifique DATABASE_URL nas variáveis de ambiente do Render. "
        "A aplicação foi interrompida para evitar operar sem o banco persistente."
    )
    st.stop()


# ============================================================
# CONTEÚDO DE ESTUDO
# ============================================================

def carregar_banco_estudo():
    conn = db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM conteudo_estudo ORDER BY id DESC;")
            rows = cursor.fetchall()

        banco_carregado = []
        for r in rows:
            banco_carregado.append({
                "id": r["id"],
                "disciplina": r["disciplina"],
                "assunto": r["assunto"],
                "modulo": r["modulo"] or "",
                "banca": json_load(r["banca"], []),
                "desc": r["desc_resumo"] or "",
                "mnemonicos": json_load(r["mnemonicos"], []),
                "mapa": json_load(r["mapa"], []),
                "cards": json_load(r["cards"], []),
                "prazos": json_load(r["prazos"], []),
                "pegadinhas": json_load(r["pegadinhas"], [])
            })

        return banco_carregado
    finally:
        conn.close()


def salvar_ou_atualizar_assunto(
    form_disc, form_assunto, form_modulo, bancas_selecionadas, dados_gerados
):
    """
    Salva o assunto.
    Se já existir, preserva campos antigos quando o novo conteúdo vier vazio.
    Antes de atualizar, grava uma cópia integral do registro anterior.
    """
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT *
                    FROM conteudo_estudo
                    WHERE LOWER(TRIM(disciplina)) = %s
                      AND LOWER(TRIM(assunto)) = %s
                    ORDER BY id
                    LIMIT 1
                    FOR UPDATE;
                """, (
                    form_disc.strip().lower(),
                    form_assunto.strip().lower()
                ))
                existente = cursor.fetchone()

                campos_json = [
                    "prazos", "pegadinhas", "cards", "mapa", "mnemonicos"
                ]

                if existente:
                    # Backup antes de qualquer alteração.
                    registrar_backup(
                        cursor,
                        "conteudo_estudo",
                        existente["id"],
                        existente,
                        "ATUALIZACAO"
                    )

                    banca_atual = json_load(existente["banca"], [])
                    for banca in bancas_selecionadas:
                        if banca not in banca_atual:
                            banca_atual.append(banca)

                    valores = {}
                    for campo in campos_json:
                        novo_valor = dados_gerados.get(campo)
                        valor_antigo = json_load(existente[campo], [])
                        valores[campo] = novo_valor if novo_valor else valor_antigo

                    nova_desc = (
                        dados_gerados.get("desc")
                        or existente["desc_resumo"]
                        or ""
                    )

                    cursor.execute("""
                        UPDATE conteudo_estudo
                        SET modulo = %s,
                            banca = %s,
                            desc_resumo = %s,
                            mnemonicos = %s,
                            mapa = %s,
                            cards = %s,
                            prazos = %s,
                            pegadinhas = %s
                        WHERE id = %s;
                    """, (
                        form_modulo or existente["modulo"],
                        json.dumps(banca_atual, ensure_ascii=False),
                        nova_desc,
                        json.dumps(valores["mnemonicos"], ensure_ascii=False),
                        json.dumps(valores["mapa"], ensure_ascii=False),
                        json.dumps(valores["cards"], ensure_ascii=False),
                        json.dumps(valores["prazos"], ensure_ascii=False),
                        json.dumps(valores["pegadinhas"], ensure_ascii=False),
                        existente["id"]
                    ))
                    item_id = existente["id"]

                else:
                    cursor.execute("""
                        INSERT INTO conteudo_estudo
                        (user_id, disciplina, assunto, modulo, banca, desc_resumo,
                         mnemonicos, mapa, cards, prazos, pegadinhas)
                        VALUES (NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id;
                    """, (
                        form_disc.strip(),
                        form_assunto.strip(),
                        form_modulo,
                        json.dumps(bancas_selecionadas, ensure_ascii=False),
                        dados_gerados.get("desc", ""),
                        json.dumps(dados_gerados.get("mnemonicos", []), ensure_ascii=False),
                        json.dumps(dados_gerados.get("mapa", []), ensure_ascii=False),
                        json.dumps(dados_gerados.get("cards", []), ensure_ascii=False),
                        json.dumps(dados_gerados.get("prazos", []), ensure_ascii=False),
                        json.dumps(dados_gerados.get("pegadinhas", []), ensure_ascii=False)
                    ))
                    item_id = cursor.fetchone()["id"]

        return item_id
    finally:
        conn.close()


# ============================================================
# USUÁRIOS
# ============================================================

def cadastrar_usuario(username, senha):
    u_clean = username.strip().lower()
    autorizado = 1 if u_clean == ADMIN_EMAIL else 0

    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO usuarios (username, senha, autorizado, criado_em)
                    VALUES (%s, %s, %s, %s);
                """, (
                    u_clean,
                    hash_password(senha),
                    autorizado,
                    datetime.now(timezone.utc).isoformat()
                ))
        mensagem = (
            "Utilizador criado e autorizado!"
            if autorizado
            else "Cadastro realizado! Aguarde a liberação do administrador."
        )
        return True, mensagem
    except psycopg2.errors.UniqueViolation:
        return False, "Nome de utilizador ou e-mail já existe!"
    finally:
        conn.close()


def alterar_status_autorizacao(user_id, status):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE usuarios SET autorizado = %s WHERE id = %s;
                """, (int(status), user_id))
    finally:
        conn.close()


def listar_usuarios():
    conn = db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, autorizado, criado_em
                FROM usuarios
                ORDER BY id;
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def autenticar_usuario(username, senha):
    conn = db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, senha, autorizado, criado_em
                FROM usuarios
                WHERE username = %s AND senha = %s;
            """, (
                username.strip().lower(),
                hash_password(senha)
            ))
            return cursor.fetchone()
    finally:
        conn.close()


# ============================================================
# LOGIN
# ============================================================

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["user_id"] = None
    st.session_state["username"] = None

if not st.session_state["logged_in"]:
    st.markdown("""
        <div style="text-align:center; padding:20px 0;">
            <h1 style="color:#0f172a; margin-bottom:5px;">🛡️ PPPE TÁTICO</h1>
            <p style="color:#64748b; font-size:15px;">
                Plataforma de Preparação de Alto Rendimento • Inteligência Artificial
            </p>
        </div>
    """, unsafe_allow_html=True)

    tab_login, tab_cadastro = st.tabs([
        "🔑 Entrar no Sistema",
        "📝 Criar Nova Conta"
    ])

    with tab_login:
        u = st.text_input("Utilizador / E-mail", key="login_user")
        p = st.text_input("Palavra-passe", type="password", key="login_pass")

        if st.button("Entrar", type="primary", use_container_width=True):
            try:
                user = autenticar_usuario(u, p)
                if user:
                    if int(user["autorizado"] or 0) == 1:
                        st.session_state["logged_in"] = True
                        st.session_state["user_id"] = user["id"]
                        st.session_state["username"] = user["username"]
                        st.success(f"Bem-vindo, {user['username']}!")
                        st.rerun()
                    else:
                        st.warning("⚠️ A sua conta aguarda aprovação do administrador.")
                else:
                    st.error("Utilizador ou palavra-passe incorretos.")
            except Exception as erro:
                mostrar_erro_banco(erro)

    with tab_cadastro:
        new_u = st.text_input("Escolha seu E-mail / Utilizador", key="cad_user")
        new_p = st.text_input(
            "Escolha uma Palavra-passe segura",
            type="password",
            key="cad_pass"
        )

        if st.button("Cadastrar Conta", use_container_width=True):
            if new_u and new_p:
                try:
                    ok, msg = cadastrar_usuario(new_u, new_p)
                    st.success(msg) if ok else st.error(msg)
                except Exception as erro:
                    mostrar_erro_banco(erro)
            else:
                st.warning("Preencha todos os campos para prosseguir.")
    st.stop()


USER_ID = st.session_state["user_id"]
USERNAME = st.session_state["username"]
is_admin_user = bool(
    USERNAME and USERNAME.strip().lower() == ADMIN_EMAIL
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown(f"""
        <div style="background:#0f172a; padding:12px 15px; border-radius:8px;
                    color:white; margin-bottom:15px;">
            <span style="font-size:11px; color:#94a3b8; text-transform:uppercase;
                         display:block;">Utilizador Ativo</span>
            <span style="font-weight:bold; font-size:14px; word-break:break-all;">
                {USERNAME}
            </span>
        </div>
    """, unsafe_allow_html=True)

    if is_admin_user:
        st.subheader("🛡 Painel Administrativo")
        with st.expander("👥 Gerir Utilizadores", expanded=True):
            try:
                usuarios_cadastrados = listar_usuarios()
                st.write(f"**Total de utilizadores:** {len(usuarios_cadastrados)}")

                for user_item in usuarios_cadastrados:
                    st.markdown(f"**{user_item['username']}**")
                    is_this_admin = (
                        user_item["username"].strip().lower() == ADMIN_EMAIL
                    )

                    if is_this_admin:
                        st.caption("👑 Admin Principal")
                    else:
                        status_atual = bool(user_item["autorizado"])
                        novo_status = st.toggle(
                            "Autorizado",
                            value=status_atual,
                            key=f"aut_side_{user_item['id']}"
                        )
                        if novo_status != status_atual:
                            alterar_status_autorizacao(
                                user_item["id"],
                                1 if novo_status else 0
                            )
                            st.toast(
                                f"Status de {user_item['username']} atualizado!"
                            )
                            st.rerun()
                    st.divider()
            except Exception as erro:
                mostrar_erro_banco(erro)

    if st.button("🚪 Terminar Sessão / Logout", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = None
        st.rerun()

    st.divider()
    st.caption("Os registros não são excluídos automaticamente.")


# ============================================================
# GEMINI
# ============================================================

@st.cache_resource
def get_gemini_client():
    if not API_KEY_ENV or genai is None:
        return None
    try:
        return genai.Client(api_key=API_KEY_ENV)
    except Exception:
        logger.exception("Não foi possível inicializar o cliente Gemini.")
        return None


client = get_gemini_client()

try:
    banco = carregar_banco_estudo()
except Exception as erro:
    mostrar_erro_banco(erro)
    st.stop()

if (
    "item_ativo_id" not in st.session_state
    or not any(i["id"] == st.session_state["item_ativo_id"] for i in banco)
):
    if banco:
        st.session_state["item_ativo_id"] = banco[0]["id"]


# ============================================================
# CABEÇALHO E NAVEGAÇÃO
# ============================================================

st.markdown("""
<div style="background:#020617; padding:15px 25px; border-radius:12px;
            color:white; display:flex; justify-content:space-between;
            align-items:center; margin-bottom:25px;">
    <div style="display:flex; align-items:center; gap:12px;">
        <div style="background:#fbbf24; color:#020617; width:36px; height:36px;
                    display:flex; align-items:center; justify-content:center;
                    border-radius:8px; font-weight:900;">🛡</div>
        <div>
            <span style="font-weight:900; font-size:16px; letter-spacing:0.05em;">
                PPPE TÁTICO
                <span style="background:#fbbf24; color:#020617; font-size:9px;
                             padding:2px 6px; border-radius:4px;">
                    AI STUDIO METHOD
                </span>
            </span>
            <span style="display:block; font-size:10px; color:#94a3b8;
                         text-transform:uppercase;">
                Polícia Penal • Retenção Jurídica Ativa
            </span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

aba_principal = st.radio(
    "Navegação Principal",
    [
        "📚 Revisão & Painel Geral",
        "⚡ Área de Estudo (4 Pilares)",
        "📄 Cadastrar / Gerenciar com IA"
    ],
    horizontal=True,
    label_visibility="collapsed"
)

st.divider()


# ============================================================
# ABA 1 - REVISÃO E PAINEL GERAL
# ============================================================

if aba_principal == "📚 Revisão & Painel Geral":
    st.markdown("### 🗂 Central de Doutrina, Súmulas e Questões")

    banco = carregar_banco_estudo()

    if not banco:
        st.warning("Nenhum assunto cadastrado.")
    else:
        disciplinas_disponiveis = sorted({
            item["disciplina"] for item in banco
        })

        col_f1, col_f2 = st.columns([2, 2])

        with col_f1:
            disc_selecionada = st.selectbox(
                "1. Filtrar Disciplina",
                disciplinas_disponiveis
            )

        assuntos_filtrados = [
            item for item in banco
            if item["disciplina"] == disc_selecionada
        ]

        with col_f2:
            assunto_escolhido_nome = st.selectbox(
                "2. Filtrar Assunto / Resumo",
                [i["assunto"] for i in assuntos_filtrados]
            )

        item_ativo = next(
            (
                i for i in assuntos_filtrados
                if i["assunto"] == assunto_escolhido_nome
            ),
            assuntos_filtrados[0]
        )

        st.markdown(f"""
        <div style="background:#0f172a; color:white; padding:25px;
                    border-radius:16px; border:1px solid #1e293b; margin-top:15px;">
            <h2 style="margin:10px 0 5px 0; font-size:22px;">
                {item_ativo['assunto']}
            </h2>
            <p style="color:#94a3b8; font-size:13px; margin-bottom:15px;">
                {item_ativo['desc']}
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.write("")
        if st.button(
            "⚡ Ir para Área de Estudo com este Assunto",
            type="primary",
            use_container_width=True
        ):
            st.session_state["item_ativo_id"] = item_ativo["id"]
            st.rerun()

        st.caption(
            "A exclusão de assuntos está desabilitada nesta versão para "
            "evitar remoções acidentais. Os registros permanecem no banco."
        )


# ============================================================
# ABA 2 - ÁREA DE ESTUDO
# ============================================================

elif aba_principal == "⚡ Área de Estudo (4 Pilares)":
    banco = carregar_banco_estudo()

    if not banco:
        st.warning("Cadastre uma matéria primeiro.")
    else:
        item_id_atual = st.session_state.get(
            "item_ativo_id",
            banco[0]["id"]
        )
        item_estudo = next(
            (i for i in banco if i["id"] == item_id_atual),
            banco[0]
        )

        st.markdown(f"""
        <div style="background:white; padding:15px 20px; border-radius:12px;
                    border:1px solid #e2e8f0;">
            <span style="font-size:11px; font-weight:bold; color:#64748b;
                         text-transform:uppercase;">
                {item_estudo['disciplina']}
            </span>
            <h3 style="margin:2px 0 0 0; color:#0f172a;">
                {item_estudo['assunto']}
            </h3>
        </div>
        """, unsafe_allow_html=True)

        st.write("")
        pilar_escolhido = st.radio(
            "Selecione o Pilar de Estudo",
            [
                "💡 MNEMÔNICOS",
                "🗺 MAPA MENTAL",
                "🗂️ SLIDES E CARTÕES",
                "⏱️ PRAZOS & TABELAS",
                "⚠️ PEGADINHAS"
            ],
            horizontal=True
        )

        st.divider()

        if pilar_escolhido == "💡 MNEMÔNICOS":
            for m in item_estudo.get("mnemonicos", []):
                st.markdown(
                    f"**{m.get('termo', '')}**: {m.get('significado', '')}"
                )

        elif pilar_escolhido == "🗺 MAPA MENTAL":
            for bloco in item_estudo.get("mapa", []):
                with st.expander(
                    f"🔹 {bloco.get('titulo', 'Conteúdo')}",
                    expanded=True
                ):
                    for item in bloco.get("itens", []):
                        st.markdown(f"- {item}", unsafe_allow_html=True)

        elif pilar_escolhido == "🗂️ SLIDES E CARTÕES":
            cards = item_estudo.get("cards", [])
            if cards:
                if "card_idx" not in st.session_state:
                    st.session_state["card_idx"] = 0

                if st.session_state["card_idx"] >= len(cards):
                    st.session_state["card_idx"] = 0

                c_idx = st.session_state["card_idx"]
                st.info(cards[c_idx].get("p", ""))

                if st.button("Revelar Resposta"):
                    st.success(cards[c_idx].get("r", ""))

                col_ant, col_prox = st.columns(2)
                if col_ant.button("⬅️ Anterior", use_container_width=True):
                    st.session_state["card_idx"] = max(0, c_idx - 1)
                    st.rerun()

                if col_prox.button("Próximo ➡️", use_container_width=True):
                    st.session_state["card_idx"] = (
                        (c_idx + 1) % len(cards)
                    )
                    st.rerun()
            else:
                st.info("Nenhum cartão cadastrado para este assunto.")

        elif pilar_escolhido == "⏱️ PRAZOS & TABELAS":
            for p in item_estudo.get("prazos", []):
                titulo = p.get("titulo", p.get("sit", "Regra"))
                st.markdown(f"**{titulo}**")
                if p.get("campo1_valor") or p.get("campo2_valor"):
                    st.write(
                        f"{p.get('campo1_valor', '')} | "
                        f"{p.get('campo2_valor', '')}"
                    )
                else:
                    for chave, valor in p.items():
                        if chave not in ("titulo", "sit") and valor:
                            st.write(f"**{chave}:** {valor}")

        elif pilar_escolhido == "⚠️ PEGADINHAS":
            pegadinhas = item_estudo.get("pegadinhas", [])
            if not pegadinhas:
                st.info("Nenhuma pegadinha cadastrada.")
            for idx, q in enumerate(pegadinhas):
                st.markdown(
                    f"**Q{idx + 1}:** {q.get('enunciado', '')}"
                )
                st.caption(
                    f"Gabarito: {q.get('gabarito', '')} — "
                    f"{q.get('explicacao', '')}"
                )


# ============================================================
# ABA 3 - CADASTRAR / GERENCIAR
# ============================================================

elif aba_principal == "📄 Cadastrar / Gerenciar com IA":
    st.markdown("### 📄 Sincronização e Criação com IA")

    form_disc = st.text_input(
        "Disciplina",
        placeholder="Ex: Direito Processual Penal"
    )
    form_assunto = st.text_input(
        "Assunto",
        placeholder="Ex: Prisão Preventiva"
    )
    form_modulo = st.text_input(
        "Módulo",
        value="Módulo Operacional"
    )
    bancas_selecionadas = st.multiselect(
        "Bancas",
        ["CEBRASPE", "FGV", "VUNESP"],
        default=["CEBRASPE"]
    )

    uploaded_image = st.file_uploader(
        "Enviar imagem (opcional)",
        type=["png", "jpg", "jpeg"]
    )
    form_texto = st.text_area(
        "Texto base (opcional):",
        height=100
    )

    st.caption(
        "Ao salvar um assunto já existente, os campos antigos serão "
        "preservados quando não houver novos dados para substituí-los."
    )

    if st.button(
        "⚡ Salvar e Sincronizar na Nuvem",
        type="primary",
        use_container_width=True
    ):
        if not form_disc.strip() or not form_assunto.strip():
            st.error("Preencha a disciplina e o assunto.")
        else:
            dados_gerados = {
                "desc": f"Estudo verticalizado de {form_assunto}.",
                "mnemonicos": [
                    {
                        "termo": "LEI",
                        "significado": "Observância legal."
                    }
                ],
                "mapa": [
                    {
                        "titulo": "Conceito",
                        "itens": [f"Estudo de {form_assunto}."]
                    }
                ],
                "cards": [
                    {
                        "p": f"O que é {form_assunto}?",
                        "r": "Conforme legislação."
                    }
                ],
                "prazos": [
                    {
                        "titulo": "Prazo Geral",
                        "campo1_label": "Regra",
                        "campo1_valor": "Conforme lei"
                    }
                ],
                "pegadinhas": [
                    {
                        "enunciado": (
                            f"A respeito de {form_assunto}, a regra é absoluta."
                        ),
                        "opcoes": ["CERTO", "ERRO"],
                        "gabarito": "ERRO",
                        "explicacao": "Incorreto."
                    }
                ]
            }

            # A imagem/texto são enviados ao Gemini somente se houver chave.
            # A resposta não substitui automaticamente dados já cadastrados.
            if client and (uploaded_image or form_texto.strip()):
                try:
                    conteudos = [
                        "Analise o material e produza um resumo jurídico "
                        "objetivo em português. Não invente dispositivos."
                    ]

                    if form_texto.strip():
                        conteudos.append(form_texto.strip())

                    if uploaded_image:
                        conteudos.append(
                            types.Part.from_bytes(
                                data=uploaded_image.getvalue(),
                                mime_type=uploaded_image.type
                            )
                        )

                    resposta = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=conteudos
                    )

                    if resposta and getattr(resposta, "text", None):
                        dados_gerados["desc"] = resposta.text.strip()

                except Exception as erro_gemini:
                    st.warning(
                        "Não foi possível processar o material com Gemini. "
                        "O cadastro seguirá com os dados básicos. "
                        f"Detalhe: {erro_gemini}"
                    )

            try:
                item_id = salvar_ou_atualizar_assunto(
                    form_disc,
                    form_assunto,
                    form_modulo,
                    bancas_selecionadas,
                    dados_gerados
                )
                st.session_state["item_ativo_id"] = item_id
                st.success(
                    "🎉 Informações gravadas no PostgreSQL/Supabase. "
                    "Uma cópia anterior também foi preservada quando houve atualização."
                )
                st.rerun()
            except Exception as erro:
                st.error("Não foi possível salvar o conteúdo.")
                st.warning(str(erro))


# ============================================================
# RODAPÉ / STATUS
# ============================================================

st.divider()
st.caption(
    "PPPE TÁTICO • Banco PostgreSQL/Supabase • "
    "Sem exclusão automática de usuários ou conteúdos."
)
