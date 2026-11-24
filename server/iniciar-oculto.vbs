' Inicia o servidor LocalControl junto com o Windows, sem janela de console.
' Nao precisa de administrador: e um atalho na pasta Inicializar do usuario.
Option Explicit

Dim sh, fso, aqui, bat
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

aqui = fso.GetParentFolderName(WScript.ScriptFullName)
bat = fso.BuildPath(aqui, "autostart.bat")

If Not fso.FileExists(bat) Then
    WScript.Quit 1
End If

' 0 = janela oculta, False = nao espera terminar
sh.CurrentDirectory = aqui
sh.Run """" & bat & """", 0, False
