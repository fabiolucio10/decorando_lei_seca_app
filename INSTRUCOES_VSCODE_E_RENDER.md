# 🚀 Guia de Execução no VSCode e Deploy no Render

Este projeto é o **Decorando Lei Seca**, contendo:
1. **Aplicação Python / Streamlit (`app.py`)**: com fragmentação inteligente de artigos extensos (todos os incisos em algarismos romanos até LXXIX+), nexo lógico de bancas (Cebraspe/OAB) com o caput, ausência de código HTML exposto nos cartões, e exemplos objetivos da vida real gerados por IA ou motor jurídico integrado.
2. **Aplicação Web / React (`src/` e `server.ts`)**: interface SPA moderna com simulador, dashboards e resolvedor de questões.

---

## 💻 1. Como rodar no seu VSCode (Passo a Passo)

### Pré-requisitos
- Ter o **Python 3.10 ou superior** instalado.
- Ter o **VSCode** com a extensão Python instalada.

### Passo 1: Abrir a pasta no VSCode
1. Abra o VSCode.
2. Vá em `File` > `Open Folder...` (ou `Arquivo` > `Abrir Pasta...`).
3. Selecione a pasta do projeto.

### Passo 2: Criar e ativar o ambiente virtual (Recomendado)
Abra o Terminal no VSCode (`Ctrl + '` ou `Terminal` > `Novo Terminal`):

**No Windows (PowerShell):**
```bash
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(Se o PowerShell bloquear scripts, use no prompt: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` ou use o Git Bash).*

**No Linux ou Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Passo 3: Instalar as dependências
Com o ambiente ativado, execute:
```bash
pip install -r requirements.txt
```

### Passo 4: Rodar o aplicativo Streamlit
Execute o comando:
```bash
streamlit run app.py
```
O Streamlit abrirá automaticamente no seu navegador no endereço `http://localhost:8501`.

---

## ☁️ 2. Como subir e rodar no Render (Render.com)

O Render é gratuito e excelente para hospedar sua aplicação.

### Método Rápido (Render Blueprint - Automático)
O repositório já conta com o arquivo `render.yaml`.
1. Suba seu projeto para o seu GitHub (veja a seção 3 abaixo).
2. Acesse [render.com](https://render.com) e conecte sua conta do GitHub.
3. No painel do Render, clique em **Blueprints** > **New Blueprint Instance**.
4. Selecione o seu repositório. O Render detectará automaticamente o arquivo `render.yaml` e configurará tudo sozinho!

---

### Método Manual (Web Service)
Se preferir criar manualmente:
1. No painel do Render, clique em **New +** e escolha **Web Service**.
2. Conecte o repositório do seu GitHub.
3. Preencha as configurações:
   - **Name**: `decorando-lei-seca`
   - **Language**: `Python`
   - **Branch**: `main` (ou a branch principal)
   - **Region**: `Oregon (US West)` ou a mais próxima.
   - **Build Command**:
     ```bash
     pip install -r requirements.txt
     ```
   - **Start Command**:
     ```bash
     streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true
     ```
4. **Variáveis de Ambiente (Environment Variables)**:
   - Adicione `PYTHON_VERSION`: `3.11.9`
   - *(Opcional)* Adicione `GEMINI_API_KEY`: sua chave de API do Google AI Studio para IA ativa.
5. Clique em **Create Web Service**.
6. Aguarde o build (2 a 3 minutos). O Render gerará uma URL pública (ex: `https://decorando-lei-seca.onrender.com`).

---

## 🐙 3. Como subir seus arquivos do VSCode para o GitHub

Se ainda não enviou os arquivos para o seu repositório:
1. No terminal do VSCode na pasta do projeto:
```bash
git init
git add .
git commit -m "Versao atualizada Decorando Lei Seca com correcao de HTML e deploy no Render"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main --force
```

---

## 🛠️ 4. O que foi corrigido nesta versão

1. **Fim do Código HTML após responder**:
   - No Streamlit, blocos de texto HTML indentados com 4 espaços eram interpretados pelo parser de Markdown como blocos `<pre><code>`.
   - Implementado o tratador `render_html_limpo(...)` que remove qualquer recuo indevido e preserva a renderização visual nativa.
   - Adicionado limpador automático no banco SQLite para tratar questões criadas em versões anteriores.

2. **Cores Mais Nítidas, Vivas e Alto Contraste**:
   - Status verde esmeralda para acertos (`#16a34a`) e vermelho rubi para erros (`#dc2626`).
   - Dispositivo Literal com borda azul e texto em `#0f172a` (preto ardósia ultra-nítido, sem tons apagados).
   - Exemplo Prático com 4 cartões internos em destaque: Situação Concreta (azul), Aplicação Prática (verde), Objetivo da Regra (roxo) e Bizu de Memorização em gradiente dourado.

3. **Arquivos de Deploy prontos para o Render**:
   - `requirements.txt` com todas as dependências requeridas.
   - `Procfile` para inicialização automática em plataformas cloud.
   - `render.yaml` pronto para deploy via Blueprint.
   - Porta dinâmica configurada para a variável `$PORT` do ambiente.
