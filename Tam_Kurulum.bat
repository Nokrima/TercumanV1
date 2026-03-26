@echo off
setlocal enabledelayedexpansion
title Oyun Ceviri Motoru - Akilli Kurulum
cd /d "%~dp0"
chcp 65001 >nul

echo =====================================================
echo   Oyun Ceviri Motoru - Akilli Tam Kurulum
echo   Python 3.11 / 3.12 / 3.13 / 3.14 Uyumlu
echo =====================================================
echo.

:: ─────────────────────────────────────────────────────
:: ADIM 1 — Microsoft Visual C++ (OpenCV/cv2 icin zorunlu)
:: ─────────────────────────────────────────────────────
echo [1/4] Microsoft Visual C++ Altyapisi kontrol ediliyor...
winget install Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
echo        Tamamlandi.
echo.

:: ─────────────────────────────────────────────────────
:: ADIM 2 — Python tespiti / kurulumu
:: py launcher onceliklidir: yonetici kurulumunda
:: PATH guncellenmeden once bile calisir.
:: ─────────────────────────────────────────────────────
echo [2/4] Python varligi kontrol ediliyor...
set PY_CMD=

py -3.14 --version >nul 2>&1 && ( set PY_CMD=py -3.14 & goto :py_found )
py -3.13 --version >nul 2>&1 && ( set PY_CMD=py -3.13 & goto :py_found )
py -3.12 --version >nul 2>&1 && ( set PY_CMD=py -3.12 & goto :py_found )
py -3.11 --version >nul 2>&1 && ( set PY_CMD=py -3.11 & goto :py_found )
python  --version >nul 2>&1  && ( set PY_CMD=python    & goto :py_found )
py      --version >nul 2>&1  && ( set PY_CMD=py         & goto :py_found )

echo        Python bulunamadi, Python 3.13 indiriliyor...
echo        Lutfen bekleyin, internet hiziniza gore 1-2 dakika surebilir.
winget install Python.Python.3.13 --silent --accept-package-agreements --accept-source-agreements
if %errorlevel% neq 0 (
    echo.
    echo  [HATA] Python otomatik indirilemedi.
    echo  Cozum: https://www.python.org/downloads/ adresinden
    echo         Python 3.13'u indirip "Add Python to PATH" secenegi
    echo         ISARETLI olarak kurun, sonra bu dosyayi tekrar calistirin.
    pause & exit /b 1
)
set PY_CMD=py -3.13
echo        Python 3.13 basariyla kuruldu!

:py_found
echo        Kullanilacak: %PY_CMD%
%PY_CMD% --version
echo.

:: ─────────────────────────────────────────────────────
:: ADIM 3 — Paket kurulumu
::
:: BILINEN HATALAR VE COZUMLERI:
::
::   HATA 1 — ModuleNotFoundError: winrt.windows.foundation.collections
::     NEDEN : winrt-Windows.Foundation.Collections paketi eksik.
::     COZUM : Bu adim zaten ekliyor. Hala goruyorsan HATA 2'ye bak.
::
::   HATA 2 — ModuleNotFoundError: winrt.windows.media.ocr
::     NEDEN : Eski "winrt" tek paketi yenisiyle catisiyor.
::     COZUM : Asagida otomatik kaldirilıyor.
::
::   HATA 3 — TypeError: bytes-like object required, not 'list'
::     NEDEN : cevirici.py eski surum. Paket sorunu DEGIL.
::     COZUM : GitHub'dan guncel cevirici.py'yi indir.
::
::   HATA 4 — mss / cv2 / numpy eksik (producer loop baslamaz)
::     NEDEN : Temel paketler kurulmamis.
::     COZUM : Bu adim zaten kuruyor. Hata devam ederse internet baglantini kontrol et.
:: ─────────────────────────────────────────────────────
echo [3/4] Moduller kuruluyor...

:: 3.1 — pip guncelle
%PY_CMD% -m pip install --upgrade pip setuptools wheel >nul 2>&1

:: 3.2 — Temel paketler
echo        Temel paketler kuruluyor...
%PY_CMD% -m pip install ^
    customtkinter ^
    deep-translator ^
    mss ^
    opencv-python ^
    numpy ^
    keyboard ^
    Pillow

if %errorlevel% neq 0 (
    echo.
    echo  [UYARI] Yeni kurulan Python'un sisteme tam isleyebilmesi icin
    echo  bu pencereyi kapatin ve tam_kurulum.bat'i YENIDEN calistirin.
    echo  Sorun devam ederse internet baglantinizi kontrol edin.
    pause & exit /b 1
)

:: 3.3 — Eski winrt varsa kaldir (catismanin ana kaynagi)
echo        Eski winrt kontrol ediliyor...
%PY_CMD% -m pip show winrt >nul 2>&1
if %errorlevel%==0 (
    echo        Eski winrt bulundu, kaldiriliyor...
    %PY_CMD% -m pip uninstall winrt -y >nul 2>&1
)

:: 3.4 — Yeni winrt ailesi (6 paket — hepsi zorunlu)
echo        Windows OCR paketleri kuruluyor...
%PY_CMD% -m pip install ^
    winrt-Windows.Foundation ^
    winrt-Windows.Foundation.Collections ^
    winrt-Windows.Globalization ^
    winrt-Windows.Graphics.Imaging ^
    winrt-Windows.Media.Ocr ^
    winrt-Windows.Storage.Streams

if %errorlevel% neq 0 (
    echo.
    echo  [UYARI] winrt paketleri kurulamadi. Windows OCR motoru calismiyor olacak.
    echo  Uygulama EasyOCR modu ile kullanilabilir.
)

echo        Modul kurulumlari tamamlandi.
echo.

:: ─────────────────────────────────────────────────────
:: ADIM 4 — calistir.vbs onar/olustur + dogrulama
:: ─────────────────────────────────────────────────────
echo [4/4] Baslatma kisayolu ve dogrulama...

:: calistir.vbs'i aktif Python komutuyla yeniden yaz
(
    echo Set fso   = CreateObject^("Scripting.FileSystemObject"^)
    echo Set shell = CreateObject^("WScript.Shell"^)
    echo dir = fso.GetParentFolderName^(WScript.ScriptFullName^)
    echo shell.CurrentDirectory = dir
    echo shell.Run "%PY_CMD% cevirici.py", 0, False
) > calistir.vbs
echo        calistir.vbs guncellendi ^(%PY_CMD%^).
echo.

:: Dogrulama
echo        Kurulum dogrulaniyor...
%PY_CMD% -c "from winrt.windows.media.ocr import OcrEngine; print('  [OK] Windows OCR hazir')" 2>nul || (
    echo   [UYARI] Windows OCR yuklenemedi
    echo           Olasilik 1 - Foundation.Collections eksik:
    echo             %PY_CMD% -m pip install winrt-Windows.Foundation.Collections
    echo           Olasilik 2 - Eski winrt hala kurulu:
    echo             %PY_CMD% -m pip uninstall winrt -y
    echo           Olasilik 3 - cevirici.py eski surum:
    echo             GitHub'dan guncel cevirici.py'yi indir
)
%PY_CMD% -c "import cv2; print('  [OK] OpenCV', cv2.__version__)" 2>nul          || echo   [UYARI] OpenCV eksik  ^| Cozum: %PY_CMD% -m pip install opencv-python
%PY_CMD% -c "import mss; print('  [OK] mss hazir')" 2>nul                         || echo   [UYARI] mss eksik     ^| Cozum: %PY_CMD% -m pip install mss
%PY_CMD% -c "import numpy; print('  [OK] numpy', numpy.__version__)" 2>nul        || echo   [UYARI] numpy eksik   ^| Cozum: %PY_CMD% -m pip install numpy
%PY_CMD% -c "import customtkinter; print('  [OK] customtkinter hazir')" 2>nul     || echo   [UYARI] customtkinter ^| Cozum: %PY_CMD% -m pip install customtkinter
%PY_CMD% -c "from deep_translator import GoogleTranslator; print('  [OK] deep-translator hazir')" 2>nul || echo   [UYARI] deep-translator ^| Cozum: %PY_CMD% -m pip install deep-translator
%PY_CMD% -c "from PIL import Image; print('  [OK] Pillow hazir')" 2>nul           || echo   [UYARI] Pillow eksik  ^| Cozum: %PY_CMD% -m pip install Pillow
%PY_CMD% -c "import keyboard; print('  [OK] keyboard hazir')" 2>nul               || echo   [UYARI] keyboard eksik ^| Cozum: %PY_CMD% -m pip install keyboard

echo.
echo =====================================================
echo   NOT: EasyOCR ve GPU modu icin programa gir,
echo        Motor Secimi ekranindaki "Kur" butonuna bas.
echo =====================================================
echo.
echo   KURULUM TAMAMLANDI! Program baslatiliyor...
echo.
timeout /t 3 /nobreak >nul
start calistir.vbs
exit /b 0