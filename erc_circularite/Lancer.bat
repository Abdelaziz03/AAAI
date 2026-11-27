@echo off
rem Lance le dossier de bout en bout sur ce poste : diagnostic, calculs, composition des pieces, note de decision.
rem Rien n'est envoye hors du poste. Double-cliquer sur ce fichier, ou le lancer depuis une invite de commandes.
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
%PY% -m erc.diagnostic
if errorlevel 1 goto fin
%PY% -m erc.agent
:fin
echo.
echo Termine. Les resultats sont dans le dossier artefacts (en demonstration : demo\artefacts).
pause
