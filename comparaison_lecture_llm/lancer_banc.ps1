# Lance le banc d'essai sur chaque modèle, avec une limite de 5 minutes par modèle (au-delà : « timeout », on passe au suivant).
param([string[]]$Modeles = @('qwen3-coder:latest', 'muse-glimmer:latest'),
      [string]$Pdf,
      [int]$LimiteSecondes = 300)
$ici = Split-Path -Parent $MyInvocation.MyCommand.Path
$resultats = Join-Path $ici 'resultats'
New-Item -ItemType Directory -Force -Path $resultats | Out-Null
$env:PYTHONIOENCODING = 'utf-8'
foreach ($m in $Modeles) {
    $nom = $m -replace '[:/\\]', '_'
    $json = Join-Path $resultats "$nom.json"
    if (Test-Path -LiteralPath $json) { Remove-Item -LiteralPath $json }
    $proc = Start-Process -FilePath py -ArgumentList '-3', "`"$ici\banc_lecture_llm.py`"", "`"$Pdf`"", $m, "`"$json`"" `
        -WorkingDirectory $ici -RedirectStandardOutput (Join-Path $resultats "$nom.out.txt") `
        -RedirectStandardError (Join-Path $resultats "$nom.err.txt") -PassThru -WindowStyle Hidden
    if (-not $proc.WaitForExit($LimiteSecondes * 1000)) {
        Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $proc.Id -or $_.ProcessId -eq $proc.Id } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        @{ modele = $m; timeout = $true; limite_s = $LimiteSecondes } | ConvertTo-Json | Set-Content -LiteralPath $json -Encoding utf8
        "$m : TIMEOUT ($LimiteSecondes s)"
    } else { "$m : termine" }
}
