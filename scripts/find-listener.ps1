$conns = Get-NetTCPConnection -LocalPort 8123 -State Listen
Write-Host "Found $($conns.Count) listener(s)"
foreach ($c in $conns) {
    Write-Host "  conn pid=$($c.OwningProcess) state=$($c.State)"
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "    Name=$($proc.Name) Started=$($proc.CreationDate) Cmd=$($proc.CommandLine)"
    } else {
        Write-Host "    (process not found via CIM)"
    }
}
