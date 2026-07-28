<#
    Diagnostica Bluetooth: dispositivi accoppiati, servizi esposti e porte COM
    create dai profili SPP (utili se la X6 e' Bluetooth "classico" e non BLE).
        powershell -ExecutionPolicy Bypass -File tools\bt_diagnose.ps1
#>

Write-Host "=== Adattatori Bluetooth ===" -ForegroundColor Cyan
Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -like "USB\*" -or $_.InstanceId -like "PCI\*" } |
    Format-Table Status, FriendlyName -AutoSize

Write-Host "=== Dispositivi Bluetooth accoppiati (BR/EDR + LE) ===" -ForegroundColor Cyan
Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -like "BTHENUM\DEV_*" -or $_.InstanceId -like "BTHLE\DEV_*" } |
    Format-Table Status, FriendlyName, InstanceId -AutoSize -Wrap

Write-Host "=== Servizi Bluetooth esposti (cerca 'Porta seriale' / SPP 1101) ===" -ForegroundColor Cyan
Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -like "BTHENUM\{*" } |
    Format-Table Status, FriendlyName -AutoSize

Write-Host "=== Porte COM (una porta 'Bluetooth' = SPP disponibile) ===" -ForegroundColor Cyan
Get-PnpDevice -Class Ports -ErrorAction SilentlyContinue |
    Format-Table Status, FriendlyName, InstanceId -AutoSize -Wrap

Write-Host "=== Stampanti installate ===" -ForegroundColor Cyan
Get-Printer | Format-Table Name, DriverName, PortName, PrinterStatus -AutoSize

Write-Host "Se vedi una porta COM 'Collegamento standard su porta seriale Bluetooth'," -ForegroundColor Yellow
Write-Host "annota il numero COMx: puoi usare transport 'serial' in config.json." -ForegroundColor Yellow
