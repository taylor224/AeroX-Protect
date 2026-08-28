# Opens the AeroXProtect web UI once it is actually reachable.
# Run hidden by the installer's finish page — first boot initializes the MariaDB
# datadir, so the stack can take tens of seconds before Caddy answers; opening
# the browser immediately would land on a connection-refused page.
param([int]$Port = 3000, [int]$TimeoutS = 180)

for ($i = 0; $i -lt $TimeoutS; $i++) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $Port)
        $c.Close()
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
Start-Process "http://localhost:$Port/"
