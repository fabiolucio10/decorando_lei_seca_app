# DECORANDO LEI SECA — versão gratuita/local

## 1. Instalar Python

Use Python 3.11 ou 3.12.

## 2. Abrir a pasta no VS Code

Abra esta pasta no VS Code:

decorando_lei_seca_app

## 3. Criar ambiente virtual

No terminal do VS Code:

Windows:
```powershell
python -m venv .venv
.venv\Scripts\activate
```

## 4. Instalar dependências

```powershell
pip install -r requirements.txt
```

## 5. Executar

```powershell
streamlit run app.py
```

O navegador abrirá o aplicativo.

## 6. Como usar

1. Vá em "Minhas Leis".
2. Informe a disciplina.
3. Informe o nome da lei.
4. Envie o PDF.
5. O sistema tenta identificar os artigos.
6. Vá em "Treinar".
7. Selecione a lei.
8. Selecione artigo único ou intervalo.
9. Informe quantidade de questões.
10. Gere o treino.
11. Responda CERTO/ERRADO.
12. Consulte Dashboard e Revisão.

## 7. IA local opcional

O aplicativo funciona sem IA.

Se quiser utilizar Ollama:
- instale o Ollama;
- baixe um modelo compatível, por exemplo:
  ollama pull llama3.2:3b
- inicie o Ollama;
- no aplicativo marque "Usar IA local Ollama".

A aplicação tenta `http://localhost:11434/api/generate`.
Se a IA não estiver disponível, o gerador baseado em regras continua funcionando.

## 8. Banco

O banco é:

decorando_lei.db

Não apague esse arquivo se quiser preservar seu histórico.

## 9. Observação sobre PDFs

O parser funciona melhor com PDFs que possuem texto selecionável.
PDFs que são apenas imagens/scans podem precisar de OCR em uma próxima versão.

## 10. Próxima evolução

- autenticação;
- importação de múltiplas leis;
- classificação automática de conteúdos;
- geração de questões em maior volume;
- repetição espaçada mais sofisticada;
- simulados;
- metas diárias;
- exportação/backup;
- instalação como PWA;
- publicação gratuita.
