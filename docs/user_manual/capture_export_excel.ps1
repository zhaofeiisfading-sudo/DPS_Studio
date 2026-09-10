$ErrorActionPreference = 'Stop'

$csvPath = (Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'export_example_manual') -Filter '*_ch1_auto.csv' -File | Select-Object -First 1).FullName
$pngPath = Join-Path $PSScriptRoot 'screenshots/11_export_files.png'

$excel = New-Object -ComObject Excel.Application
$workbook = $null
$chartObject = $null
try {
    $excel.DisplayAlerts = $false
    $workbook = $excel.Workbooks.Open($csvPath, 0, $true, 2, $null, $null, $true, 2, ',', $false, $false, 1, $false, $false, 0)
    $worksheet = $workbook.Worksheets.Item(1)
    $usedRange = $worksheet.UsedRange
    $chartObject = $worksheet.ChartObjects().Add(20, 20, 1100, 600)
    $chart = $chartObject.Chart
    $chart.ChartType = 73
    $chart.SetSourceData($usedRange)
    $chart.HasTitle = $true
    $chart.ChartTitle.Text = 'PDV Studio export: display velocity'
    $chart.Axes(1).HasTitle = $true
    $chart.Axes(1).AxisTitle.Text = 'time_from_event_s'
    $chart.Axes(2).HasTitle = $true
    $chart.Axes(2).AxisTitle.Text = 'display_velocity_m_s'
    $chart.Export($pngPath, 'PNG', $true)
}
finally {
    if ($chartObject -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($chartObject) }
    if ($workbook -ne $null) { $workbook.Close($false) }
    $excel.Quit()
    if ($workbook -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) }
    if ($excel -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
}
