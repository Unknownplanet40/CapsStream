' ============================================================
'  CapsStream — Silent Launcher
'  Double-click this file to start CapsStream with NO console
'  window. Only the app-mode browser window appears. Closing
'  that window stops the server automatically.
'
'  For a verbose console with live logs, use start.bat instead.
' ============================================================
Option Explicit

Dim shell, fso, rootDir, pythonw, launcher

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

rootDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = rootDir & "\winpython\python\pythonw.exe"
launcher = rootDir & "\silent_launcher.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "CapsStream could not start:" & vbCrLf & _
           "pythonw.exe was not found at:" & vbCrLf & pythonw, _
           vbCritical, "CapsStream"
    WScript.Quit 1
End If

If Not fso.FileExists(launcher) Then
    MsgBox "CapsStream could not start:" & vbCrLf & _
           "silent_launcher.py was not found at:" & vbCrLf & launcher, _
           vbCritical, "CapsStream"
    WScript.Quit 1
End If

' Run hidden (0 = no window), don't wait for it to finish
shell.Run """" & pythonw & """ """ & launcher & """", 0, False
