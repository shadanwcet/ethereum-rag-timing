@echo off
setlocal
echo ========================================================
echo Publishing to https://github.com/shadanwcet/ethereum-rag-timing
echo ========================================================
echo.

set GIT_EXE=D:\Git\cmd\git.exe
%GIT_EXE% -C "D:\PeerJ" config http.sslCAInfo "D:/Git/mingw64/etc/ssl/certs/ca-bundle.crt"

echo Option 1: Press ENTER to push using standard GitHub login prompt
echo Option 2: Paste your GitHub Personal Access Token (PAT) below
echo.
set /p TOKEN="Enter GitHub Token (or press ENTER to use prompt): "

if "%TOKEN%"=="" (
    echo.
    echo Pushing with standard authentication...
    %GIT_EXE% -C "D:\PeerJ" push -u origin main
) else (
    echo.
    echo Pushing with provided token...
    %GIT_EXE% -C "D:\PeerJ" push -u https://%TOKEN%@github.com/shadanwcet/ethereum-rag-timing.git main
)

echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo SUCCESS: Repository published to GitHub!
    echo Visit: https://github.com/shadanwcet/ethereum-rag-timing
    echo ========================================================
) else (
    echo.
    echo PUSH FAILED. Check credentials or token permissions (must have 'repo' scope).
)
echo.
pause
