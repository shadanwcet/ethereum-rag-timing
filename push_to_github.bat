@echo off
echo ========================================================
echo Publishing repository to https://github.com/shadanwcet/ethereum-rag-timing
echo ========================================================
echo.
echo Make sure you have created the empty repository on GitHub:
echo https://github.com/new (Name: ethereum-rag-timing, Public)
echo.
pause
echo Pushing to GitHub...
"D:\Git\cmd\git.exe" -C "D:\PeerJ" push -u origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo SUCCESS: Repository published to GitHub!
    echo https://github.com/shadanwcet/ethereum-rag-timing
    echo ========================================================
) else (
    echo.
    echo PUSH FAILED. Check credentials or repository existence.
)
pause
