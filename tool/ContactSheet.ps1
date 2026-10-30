# Contact Sheet - a small window for the clip pipeline: status, thumbnails, upload and Drive archive.
# Start it with "Contact Sheet.bat". Windows PowerShell 5.1 + WinForms, no installs. Keep this file ASCII only.
# Look matches TechTools: obsidian background, crimson accent.
# It never edits manifest.csv. It starts clip_pipeline.py in its own console and always asks first.
# Uploads stay UNLISTED (the pipeline hard-codes that). Archive only copies and checks MD5, never deletes.
# There is deliberately no publish button: making a video public is only possible by typing PUBLISH in the pipeline.
param([switch]$SelfTest)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class DwmDark { [DllImport("dwmapi.dll")] public static extern int DwmSetWindowAttribute(IntPtr h, int a, ref int v, int s); }
'@
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System; using System.Drawing; using System.Runtime.InteropServices;
public static class ShellThumb {                         // Windows' own thumbnails (the ones Explorer shows), no extra software needed
    [StructLayout(LayoutKind.Sequential)] struct SIZE { public int cx, cy; }
    [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItemImageFactory { [PreserveSig] int GetImage(SIZE size, int flags, out IntPtr hbm); }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid, [MarshalAs(UnmanagedType.Interface)] out IShellItemImageFactory f);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr h);
    public static Bitmap Get(string path, int w, int h) {
        Guid iid = new Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"); IShellItemImageFactory f;
        SHCreateItemFromParsingName(path, IntPtr.Zero, ref iid, out f);
        SIZE s; s.cx = w; s.cy = h; IntPtr hb;
        if (f.GetImage(s, 0, out hb) != 0 || hb == IntPtr.Zero) return null;
        try { using (Bitmap b = Image.FromHbitmap(hb)) { return new Bitmap(b); } } finally { DeleteObject(hb); }
    }
}
'@

$script:Here = $PSScriptRoot
$script:Manifest = Join-Path $script:Here 'manifest.csv'
$script:Pipeline = Join-Path $script:Here 'clip_pipeline.py'

function C($hex) { [System.Drawing.ColorTranslator]::FromHtml($hex) }
$script:Obsidian = C '#050506'; $script:Panel = C '#0D0D10'; $script:Edge = C '#2A0A12'
$script:Crimson = C '#8C0F26'; $script:CrimsonHi = C '#C4162F'; $script:Text = C '#E6E1E2'; $script:Dim = C '#8A7F82'
$script:Amber = C '#E0A458'; $script:Good = C '#7FD18B'
$script:Mono = New-Object System.Drawing.Font('Consolas', 10)
$script:Sans = New-Object System.Drawing.Font('Segoe UI', 9.5)
$script:Tip = New-Object System.Windows.Forms.ToolTip; $script:Tip.InitialDelay = 300; $script:Tip.AutoPopDelay = 12000

# ---- data ------------------------------------------------------------------------------------------------
function Read-Clips {
    for ($i = 0; $i -lt 5; $i++) {                        # the pipeline swaps the file in; retry if caught mid-swap
        try { return @(Import-Csv -LiteralPath $script:Manifest -Encoding UTF8) } catch { Start-Sleep -Milliseconds 200 }
    }
    return @()
}
function Get-ClipPath($row) {
    foreach ($d in 'uploaded', 'new') { $p = Join-Path (Join-Path $script:Here $d) $row.filename; if (Test-Path -LiteralPath $p) { return $p } }
    return $null
}
function Get-Python { if (Get-Command py -ErrorAction SilentlyContinue) { 'py -3 -B' } else { 'python -B' } }
function Test-PipelineRunning {
    $procs = Get-CimInstance Win32_Process -Filter "Name='py.exe' OR Name='python.exe'" | Where-Object { $_.CommandLine }
    return [bool]($procs | Where-Object { $_.CommandLine -match 'clip_pipeline\.py\s+(run|upload|archive)' })
}
function Invoke-Capture($arguments) {                     # run the pipeline, wait, return all its text (used for the safe previews)
    $exe = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
    $a = if ($exe -eq 'py') { '-3 -B' } else { '-B' }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe; $psi.Arguments = "$a `"$script:Pipeline`" $arguments"; $psi.WorkingDirectory = $script:Here
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.RedirectStandardInput = $true
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
    $p = [System.Diagnostics.Process]::Start($psi); $p.StandardInput.Close()
    $err = $p.StandardError.ReadToEndAsync(); $out = $p.StandardOutput.ReadToEnd(); $p.WaitForExit()
    return ($out + $err.Result).Trim()
}

# ---- window ----------------------------------------------------------------------------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Contact Sheet'; $form.Size = New-Object System.Drawing.Size(980, 700); $form.MinimumSize = New-Object System.Drawing.Size(760, 520)
$form.StartPosition = 'CenterScreen'; $form.BackColor = $script:Obsidian; $form.ForeColor = $script:Text; $form.Font = $script:Sans
$form.Add_HandleCreated({ $v = 1; [void][DwmDark]::DwmSetWindowAttribute($form.Handle, 20, [ref]$v, 4) })

function New-Button($text, $x, $w, $tip, $onClick) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text; $b.Location = New-Object System.Drawing.Point($x, 10); $b.Size = New-Object System.Drawing.Size($w, 32)
    $b.FlatStyle = 'Flat'; $b.BackColor = $script:Panel; $b.ForeColor = $script:Text; $b.Font = $script:Sans
    $b.FlatAppearance.BorderColor = $script:Crimson; $b.FlatAppearance.MouseOverBackColor = $script:Crimson
    $b.Add_Click($onClick); $script:Tip.SetToolTip($b, $tip); return $b
}

$bar = New-Object System.Windows.Forms.Panel; $bar.Dock = 'Top'; $bar.Height = 52; $bar.BackColor = $script:Obsidian
$script:summary = New-Object System.Windows.Forms.Label
$script:summary.Dock = 'Top'; $script:summary.Height = 26; $script:summary.ForeColor = $script:Dim; $script:summary.Padding = New-Object System.Windows.Forms.Padding(12, 4, 0, 0)

$script:list = New-Object System.Windows.Forms.ListView
$script:list.Dock = 'Fill'; $script:list.View = 'LargeIcon'; $script:list.BackColor = $script:Obsidian; $script:list.ForeColor = $script:Text
$script:list.BorderStyle = 'None'; $script:list.MultiSelect = $false
$script:imgs = New-Object System.Windows.Forms.ImageList; $script:imgs.ImageSize = New-Object System.Drawing.Size(160, 90); $script:imgs.ColorDepth = 'Depth32Bit'
$script:list.LargeImageList = $script:imgs

$script:out = New-Object System.Windows.Forms.TextBox
$script:out.Multiline = $true; $script:out.ReadOnly = $true; $script:out.ScrollBars = 'Both'; $script:out.WordWrap = $false; $script:out.Font = $script:Mono
$script:out.BackColor = $script:Panel; $script:out.ForeColor = $script:Text; $script:out.BorderStyle = 'FixedSingle'; $script:out.Dock = 'Bottom'; $script:out.Height = 150

$script:thumbQueue = New-Object System.Collections.Queue
$script:thumbTimer = New-Object System.Windows.Forms.Timer; $script:thumbTimer.Interval = 60
$script:thumbTimer.Add_Tick({                              # a few thumbnails per tick keeps the window responsive
    for ($n = 0; $n -lt 2 -and $script:thumbQueue.Count -gt 0; $n++) {
        $job = $script:thumbQueue.Dequeue()
        try { $bmp = [ShellThumb]::Get($job.Path, 160, 90); if ($bmp) { $job.Item.ImageIndex = $script:imgs.Images.Add($bmp, [System.Drawing.Color]::Transparent) } } catch { }
    }
    if ($script:thumbQueue.Count -eq 0) { $script:thumbTimer.Stop() }
})

function Refresh-List {
    $rows = Read-Clips
    $script:list.BeginUpdate(); $script:list.Items.Clear(); $script:imgs.Images.Clear(); $script:thumbQueue.Clear()
    $blank = New-Object System.Drawing.Bitmap(160, 90); $g = [System.Drawing.Graphics]::FromImage($blank); $g.Clear($script:Panel); $g.Dispose()
    [void]$script:imgs.Images.Add($blank)
    $up = 0; $arch = 0; $wait = 0; $fail = 0
    foreach ($r in ($rows | Where-Object { $_.status -in 'uploaded', 'fetched', 'failed' } | Sort-Object filename -Descending)) {
        $label = switch ($r.status) {
            'uploaded' { if ($r.archived_at) { $up++; $arch++; 'on YouTube, archived' } else { $up++; 'on YouTube, NOT archived' } }
            'fetched'  { $wait++; 'waiting to upload' }
            default    { $fail++; 'failed' }
        }
        $short = $r.filename -replace '\.mp4$', ''
        $it = New-Object System.Windows.Forms.ListViewItem("$short`n$label", 0)
        $it.ForeColor = switch ($r.status) { 'failed' { $script:CrimsonHi } 'fetched' { $script:Dim } default { if ($r.archived_at) { $script:Good } else { $script:Amber } } }
        $it.ToolTipText = "$($r.filename)  $label"
        [void]$script:list.Items.Add($it)
        $p = Get-ClipPath $r
        if ($p) { $script:thumbQueue.Enqueue([pscustomobject]@{ Item = $it; Path = $p }) }
    }
    $script:list.EndUpdate()
    $script:summary.Text = "On YouTube (unlisted): $up    Archived to Drive: $arch    Waiting to archive: $($up - $arch)    Waiting to upload: $wait    Failed: $fail"
    if ($script:thumbQueue.Count -gt 0) { $script:thumbTimer.Start() }
    return [pscustomobject]@{ Uploaded = $up; Archived = $arch; Waiting = $wait; Failed = $fail }
}

function Show-Out($text) { $script:out.Text = ($text -split "`r?`n") -join "`r`n" }
function Start-Console($command) {                         # long jobs run in their own console so progress stays visible
    Start-Process cmd.exe -ArgumentList '/k', $command -WorkingDirectory $script:Here
}
function Confirm-Run($title, $detail, $command) {
    if (Test-PipelineRunning) { [void][System.Windows.Forms.MessageBox]::Show('The pipeline is already running (an upload or archive). Wait for it to finish first.', $title, 'OK', 'Information'); return }
    $ans = [System.Windows.Forms.MessageBox]::Show($detail, $title, 'OKCancel', 'Question', 'Button2')
    if ($ans -eq 'OK') { Start-Console $command }
}

$bar.Controls.Add((New-Button 'Refresh' 12 80 'Re-read manifest.csv and reload the thumbnails. Read-only.' { [void](Refresh-List) }))
$bar.Controls.Add((New-Button 'Preview upload' 100 120 'Shows which clips would be uploaded (as UNLISTED). Uploads nothing.' {
    Show-Out (Invoke-Capture 'upload --dry-run --yes') }))
$bar.Controls.Add((New-Button 'Upload new clips' 228 130 'Uploads the clips in the new folder as UNLISTED, in its own window. Asks first.' {
    $py = Get-Python
    Confirm-Run 'Upload new clips' "Upload the clips in the 'new' folder to YouTube as UNLISTED?`n`nUse 'Preview upload' first to see the list.`nNothing is made public." "$py clip_pipeline.py upload --yes" }))
$bar.Controls.Add((New-Button 'Preview archive' 366 120 'Shows which clips would be copied to Google Drive. Copies nothing, needs no sign-in.' {
    Show-Out (Invoke-Capture 'archive --dry-run --yes') }))
$bar.Controls.Add((New-Button 'Archive to Drive' 494 130 'Copies waiting clips to Google Drive and checks each by MD5. Copies only: nothing is deleted or moved. Asks first.' {
    $py = Get-Python
    Confirm-Run 'Archive to Drive' "Copy the waiting clips to Google Drive and check each copy (MD5)?`n`nThis only copies. Nothing is deleted or moved.`nResumes automatically if the connection drops." "$py clip_pipeline.py archive --yes" }))
$bar.Controls.Add((New-Button 'Phone page' 632 100 'Starts the home-network page for your phone (random token, LAN only, asks before anything runs). Opens in its own window.' {
    $py = Get-Python; Start-Console "$py clip_web.py" }))
$bar.Controls.Add((New-Button 'Open log' 740 90 'Opens pipeline.log.' {
    $l = Join-Path $script:Here 'pipeline.log'; if (Test-Path $l) { Start-Process notepad.exe $l } }))

$form.Controls.Add($script:list); $form.Controls.Add($script:out); $form.Controls.Add($script:summary); $form.Controls.Add($bar)
$script:list.BringToFront()

if ($SelfTest) {
    $r = Refresh-List
    "uploaded=$($r.Uploaded) archived=$($r.Archived) waiting=$($r.Waiting) failed=$($r.Failed) items=$($script:list.Items.Count)"
    $first = $script:thumbQueue.Peek()
    if ($first) { $b = [ShellThumb]::Get($first.Path, 160, 90); "first thumbnail: " + $(if ($b) { "$($b.Width)x$($b.Height) ok" } else { 'none' }) }
    "pipeline running now: $(Test-PipelineRunning)"
    "preview archive (first lines):"; (Invoke-Capture "archive --dry-run --yes") -split "`n" | Select-Object -First 4
    return
}
$form.Add_Shown({ [void](Refresh-List) })
[void]$form.ShowDialog()
