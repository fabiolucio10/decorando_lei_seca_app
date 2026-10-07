import os
import streamlit as st
import fitz  # PyMuPDF para leitura de PDFs
import pandas as pd
from sqlalchemy import create_engine, text

# Configuração da Página
st.set_page_config(
    page_title="Decorando Lei Seca",
    page_icon="⚖️",
    layout="wide"
)

# Conexão com o Banco de Dados (PostgreSQL / Supabase via Streamlit Secrets ou Variável de Ambiente)
DATABASE_URL = os.getenv("DATABASE_URL") or st.secrets.get("DATABASE_URL")

@st.cache_resource
def get_engine():
    if not DATABASE_URL:
        st.error("A variável de ambiente DATABASE_URL não está configurada!")
        return None
    return create_engine(DATABASE_URL)

engine = get_engine()

# Função para inicializar tabelas se não existirem
def init_db():
    if not engine:
        return
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS leis (
                id SERIAL PRIMARY KEY,
                titulo TEXT NOT NULL,
                conteudo TEXT
            );
        """))
        conn.commit()

init_db()

st.title("⚖️ Decorando Lei Seca - Estudos e Questões")
st.sidebar.header("Navegação")

menu = st.sidebar.selectbox("Escolha uma opção", ["Estudar Lei / PDF", "Cadastrar Nova Lei", "Banco de Questões"])

if menu == "Estudar Lei / PDF":
    st.subheader("📁 Leitura e Processamento de Leis (PDF)")
    
    uploaded_file = st.file_uploader("Envie o arquivo PDF da Lei", type=["pdf"])
    
    if uploaded_file is not None:
        # Salva o arquivo enviado em um diretório temporário seguro (/tmp/) para compatibilidade com o Render
        temp_dir = "/tmp"
        os.makedirs(temp_dir, exist_ok=True)
        temp_pdf_path = os.path.join(temp_dir, uploaded_file.name)
        
        with open(temp_pdf_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
            
        st.success(f"Arquivo carregado com sucesso: {uploaded_file.name}")
        
        if st.button("Processar e Ler PDF"):
            try:
                # Validação de segurança para evitar erro NoneType
                if not temp_pdf_path or not os.path.exists(temp_pdf_path):
                    st.error("Caminho do PDF inválido ou arquivo não encontrado.")
                else:
                    doc = fitz.open(temp_pdf_path)
                    texto_completo = ""
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        texto_completo += page.get_text()
                    
                    st.info(f"Total de páginas lidas: {len(doc)}")
                    st.text_area("Conteúdo Extraído do PDF", texto_completo[:2000] + "...", height=300)
                    
                    # Salvar no Banco de Dados
                    if engine:
                        with engine.connect() as conn:
                            conn.execute(
                                text("INSERT INTO leis (titulo, conteudo) VALUES (:titulo, :conteudo)"),
                                {"titulo": uploaded_file.name, "conteudo": texto_completo}
                            )
                            conn.commit()
                        st.success("Lei salva com sucesso no banco de dados PostgreSQL!")
            except Exception as e:
                st.error(f"Erro ao processar o arquivo PDF: {e}")

elif menu == "Cadastrar Nova Lei":
    st.subheader("✍️ Cadastro Manual de Lei / Artigo")
    titulo_lei = st.text_input("Título / Nome da Lei")
    conteudo_lei = st.text_area("Texto da Lei / Artigos", height=200)
    
    if st.button("Salvar Lei"):
        if titulo_lei and conteudo_lei:
            try:
                with engine.connect() as conn:
                    conn.execute(
                        text("INSERT INTO leis (titulo, conteudo) VALUES (:titulo, :conteudo)"),
                        {"titulo": titulo_lei, "conteudo": conteudo_lei}
                    )
                    conn.commit()
                st.success("Cadastrado com sucesso!")
            except Exception as e:
                st.error(f"Erro ao salvar no banco: {e}")
        else:
                    st.warning("Preencha todos os campos.")

elif menu == "Banco de Questões":
    st.subheader("📚 Leis Cadastradas no Sistema")
    try:
        if engine:
            df = pd.read_sql("SELECT id, titulo FROM leis", engine)
            if not df.empty:
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Nenhuma lei cadastrada ainda.")
    except Exception as e:
        st.error(f"Erro ao carregar dados do banco: {e}")
