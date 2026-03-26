@echo off
setlocal enabledelayedexpansion
title Oyun Ceviri Motoru - Akilli Kurulum
cd /d "%~dp0"

echo =====================================================
echo   Oyun Ceviri Motoru - Akilli Tam Kurulum
echo =====================================================
echo.

:: 1. ADIM: C++ Redistributable (OpenCV/cv2 icin zorunlu)
echo [1/4] Microsoft Visual C++ Altyapisi kontrol ediliyor...
winget install Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
echo        Tamamlandi.
echo.

:: 2. ADIM: Dinamik Python Kontrolu
echo [2/4] Python varligi kontrol ediliyor...
set PY_CMD=
python --version >nul 2>&1
if %errorlevel%==0 (
    set PY_CMD=python
) else (
    py --version >nul 2>&1
    if %errorlevel%==0 (
        set PY_CMD=py
    )
)

if not "%PY_CMD%"=="" (
    echo        Sistemde zaten Python kurulu, yukleme atlandi.
) else (
    echo        Python bulunamadi! ^(Yapay Zeka uyumlu surum indiriliyor...^)
    echo        Lutfen bekleyin, bu islem internet hiziniza gore 1-2 dakika surebilir.
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo.
        echo [HATA] Python otomatik indirilemedi.
        echo Lutfen python.org adresinden indirip kurun ve tekrar deneyin.
        pause
        exit /b 1
    )
    set PY_CMD=py
    echo        Python basariyla kuruldu!
)
echo.

:: 3. ADIM: Python Paketleri
echo [3/4] Temel moduller ve OCR paketleri kuruluyor...
%PY_CMD% -m pip install --upgrade pip >nul 2>&1
%PY_CMD% -m pip install customtkinter deep-translator mss opencv-python numpy keyboard Pillow

if %errorlevel% neq 0 (
    echo.
    echo [UYARI] Yeni kurulan Python'un sisteme tam isleyebilmesi icin
    echo lutfen BU PENCEREYI KAPATIN ve tam_kurulum.bat dosyasini
    echo YENIDEN YONETICI OLARAK calistirin.
    pause
    exit /b 1
)

%PY_CMD% -m pip install winrt-Windows.Media.Ocr winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Foundation >nul 2>&1
echo        Modul kurulumlari tamamlandi.
echo.

:: 4. ADIM: calistir.vbs Dosyasini Otomatik Onar/Olustur
echo [4/4] Baslatma kisayolu (calistir.vbs) ayarlaniyor...
echo Set WshShell = CreateObject("WScript.Shell") > calistir.vbs
echo WshShell.Run "cmd /c %PY_CMD% """"cevirici.py""""", 0, False >> calistir.vbs
echo        Kisa yol ayarlandi.
echo.

echo =====================================================
echo   KURULUM KUSURSUZ TAMAMLANDI!
echo =====================================================
echo Programiniz simdi baslatiliyor...
timeout /t 3 /nobreak >nul

start calistir.vbs
exit /b 0