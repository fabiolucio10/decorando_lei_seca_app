@echo off
chcp 65001 >nul
echo ======================================================
echo    🚀 DECORANDO LEI SECA - INICIALIZADOR AUTOMÁTICO
echo ======================================================
echo.
echo Iniciando o aplicativo Streamlit no seu navegador...
echo.

python -m streamlit run app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Tentativa 2] Executando com lançador py...
    py -m streamlit run app.py
)
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Tentativa 3] Executando comando direto streamlit...
    streamlit run app.py
)

echo.
pause
