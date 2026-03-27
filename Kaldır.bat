@echo off 
title Oyun Ceviri Motoru - Kaldirma Araci
color 0C

:: Yönetici İzni Kontrolü
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo =======================================================
    echo LUTFEN YONETICI OLARAK CALISTIRIN!
    echo =======================================================
    echo Bu dosya uzerine sag tiklayip "Yonetici olarak calistir"
    echo secenegini secmeniz gerekmektedir.
    echo.
    pause
    exit
)

echo ========================================================
echo   OYUN CEVIRI MOTORU - TAMAMEN KALDIRMA ARACI
echo ========================================================
echo.
echo Bu islem asagidakileri yapacaktir:
echo 1. Programin indirdigi tum Python kutuphanelerini (OCR, Yapay Zeka vb.) siler.
echo 2. Eger sonradan kurduysaniz ~2.5 GB'lik EasyOCR ve PyTorch dosyalarini temizler.
echo 3. Program ayarlarini (settings.json) ve log dosyalarini (app_log.txt) siler.
echo.
echo NOT: Bilgisayarinizdaki Python programinin kendisi SILINMEZ,
echo sadece bu programin sisteme yukledigi eklentiler temizlenir.
echo.

choice /C EH /N /M "Her seyi silmek ve devam etmek istiyor musunuz? (E: Evet, H: Hayir): "
if errorlevel 2 goto iptal
if errorlevel 1 goto kaldir

:kaldir
echo.
echo ========================================================
echo [1/3] Standart Kutuphaneler Siliyor...
echo ========================================================
python -m pip uninstall -y customtkinter deep-translator mss numpy opencv-python keyboard google-generativeai
python -m pip uninstall -y winrt-Windows.Media.Ocr winrt-Windows.Globalization winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Foundation winrt-Windows.Foundation.Collections

echo.
echo ========================================================
echo [2/3] EasyOCR ve PyTorch (Ekran Karti Motoru) Siliniyor...
echo ========================================================
python -m pip uninstall -y easyocr torch torchvision torchaudio

echo.
echo ========================================================
echo [3/3] Ayar, Log ve Onbellek Dosyalari Temizleniyor...
echo ========================================================
if exist "settings.json" del /f /q "settings.json"
if exist "app_log.txt" del /f /q "app_log.txt"
if exist "install_log.txt" del /f /q "install_log.txt"
if exist "__pycache__" rmdir /s /q "__pycache__"

echo.
echo ========================================================
echo TERTEMIZ! Tum eklentiler ve ayarlar basariyla kaldirildi.
echo Artik bu klasoru bilgisayarinizdan silebilirsiniz.
echo ========================================================
pause
exit

:iptal
echo.
echo Kaldirma islemi iptal edildi. Hicbir dosya silinmedi.
pause
exit