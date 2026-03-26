' Oyun Çeviri Motoru — Sessiz Başlatıcı
' CMD penceresi açılmaz, doğrudan program başlar
' Çift tıkla çalıştır

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' Bu dosyanın bulunduğu klasörü çalışma dizini yap
dir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = dir

' Python 3.14 önce dene, yoksa 3.11, en son sistemi kullan
On Error Resume Next
shell.Run "py -3.14 cevirici.py", 0, False
If Err.Number <> 0 Then
    Err.Clear
    shell.Run "py -3.11 cevirici.py", 0, False
    If Err.Number <> 0 Then
        Err.Clear
        shell.Run "python cevirici.py", 0, False
    End If
End If
On Error GoTo 0
