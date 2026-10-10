@echo off
rem ---------------------------------------------------------------------------
rem  mcporter launcher (Windows)
rem
rem    run.bat <mod.jar ^| mod_dir ^| folder-of-mods> [options...]
rem
rem  With no arguments it runs interactively and asks for the mod path and the
rem  target Luanti game.  All extra arguments are passed straight to port.py:
rem
rem    run.bat "C:\Users\me\Downloads\MyMod.jar"
rem    run.bat "C:\Users\me\Downloads\MyMod.jar" --install
rem    run.bat "%APPDATA%\.minecraft\mods" --game voxelibre
rem ---------------------------------------------------------------------------
setlocal

set "DIR=%~dp0"

rem Prefer the Python launcher (py -3), then python on PATH.
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo mcporter: Python 3.10+ is required but was not found on your PATH. 1>&2
        echo Install it from https://www.python.org/downloads/ and try again. 1>&2
        exit /b 1
    )
)

%PY% "%DIR%port.py" %*
exit /b %errorlevel%
