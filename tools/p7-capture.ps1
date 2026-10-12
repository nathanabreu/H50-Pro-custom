# P7: o 10/3 (clean-record) não chega. Os fragmentos IP chegam ao PC?
#
# São DOIS terminais, porque só a captura precisa de administrador (e a janela de administrador pode
# abrir com OUTRA conta do Windows, sem o seu Python nem o H50_TOKEN):
#
#  1) PowerShell COMO ADMINISTRADOR, na pasta do projeto:
#       cd C:\claude_local\xiaomi
#       powershell -ExecutionPolicy Bypass -File tools\p7-capture.ps1
#     Ele liga a captura e espera.
#  2) Terminal NORMAL (o seu, de sempre), também na pasta do projeto:
#       py tools\p7_read.py
#     Depois volte ao terminal de administrador e pressione Enter.
#
# Gera data\p7.pcapng. Feche o app H50 Console antes: ele também fala com o robô e mistura pacotes.

$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force data | Out-Null
Remove-Item data\p7.etl, data\p7.pcapng -ErrorAction SilentlyContinue

pktmon stop 2>$null | Out-Null
pktmon filter remove | Out-Null                    # sem filtro: são só alguns segundos
pktmon start --capture --comp nics --pkt-size 0 --file-name data\p7.etl
""
"CAPTURA LIGADA."
"Agora, no seu terminal NORMAL, rode:   py tools\p7_read.py"
"Quando ele terminar, volte aqui e pressione Enter."
[void](Read-Host)

pktmon stop
pktmon etl2pcap data\p7.etl --out data\p7.pcapng
"Pronto: data\p7.pcapng ($((Get-Item data\p7.pcapng).Length) bytes). Me avise que eu analiso."
