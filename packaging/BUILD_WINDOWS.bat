@echo off
rem Build SortZen on a Windows PC: program folder in dist\SortZen and, if Inno Setup 6 is
rem installed, the installer in dist\. Run from the repository folder.
python -m pip install -r requirements-dev.txt || goto :error
python -m unittest discover -s tests -t . || goto :error
python packaging\make_icon.py || goto :error
pyinstaller packaging\sortzen.spec --noconfirm || goto :error
for /f %%v in ('python -c "import sys; sys.path.insert(0, 'src'); import sortzen; print(sortzen.__version__)"') do set VERSION=%%v
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=%VERSION% packaging\sortzen.iss
echo Done. See the dist folder.
goto :eof
:error
echo Build failed.
exit /b 1
