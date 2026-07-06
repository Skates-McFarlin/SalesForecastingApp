# One-Click Automation Script for Backend Setup
# This script automates the setup and installation of the backend application

Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force

# Function to check if a command exists - improved version
function Test-CommandExists {
    param ($command)
    try {
        # First try to use Get-Command
        $exists = Get-Command $command -ErrorAction SilentlyContinue

        if ($null -ne $exists) {
            return $true
        }
        
        # If the command is mysql, check for service or executable specifically
        if ($command -eq "mysql") {
            # Check if MySQL service exists
#            $service = Get-Service -Name "MySQL*" -ErrorAction SilentlyContinue
#            if ($null -ne $service) {
#                return $true
#            }
            
            # Check common MySQL installation paths
            $mysqlPaths = @(
                "C:\Program Files\MySQL\MySQL Server*\bin\mysql.exe",
                "C:\Program Files (x86)\MySQL\MySQL Server*\bin\mysql.exe",
                "C:\xampp\mysql\bin\mysql.exe"
            )
            
            foreach ($path in $mysqlPaths) {
                if (Test-Path -Path $path) {
                    return $true
                }
            }
        }
        
        return $false
    } catch {
        return $false
    }
}

# Function to handle errors
function Handle-Error {
    param (
        [string]$step,
        [string]$message
    )
    Write-Host "Error during $step`: $message" -ForegroundColor Red
    Write-Host "Please check the logs and try again." -ForegroundColor Red
    exit 1
}

# Function to download file with progress bar
function Download-FileWithProgress {
    param (
        [string]$Url,
        [string]$OutFile,
        [switch]$NoProgress = $false,
        [int]$MaxRetries = 3,
        [int]$TimeoutSec = 120
    )
    
    try {
        # Create directory if it doesn't exist
        $outDir = Split-Path -Path $OutFile -Parent
        if (-not (Test-Path -Path $outDir)) {
            New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        }
        
        # Get file size if we're showing progress
        $totalLength = 0
        if (-not $NoProgress) {
            try {
                $request = [System.Net.HttpWebRequest]::Create($Url)
                $request.Method = "HEAD"
                $request.Timeout = 10000  # 10 seconds timeout for HEAD request
                $request.UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                $response = $request.GetResponse()
                $totalLength = [System.Convert]::ToInt64($response.Headers.Get("Content-Length"))
                $response.Close()
                
                Write-Host "Downloading file... (Size: $([math]::Round($totalLength / 1MB, 2)) MB)"
            } catch {
                Write-Host "Could not determine file size. Continuing download..." -ForegroundColor Yellow
            }
        }
        
        # Attempt download with retries
        $retryCount = 0
        $success = $false
        
        while (-not $success -and $retryCount -lt $MaxRetries) {
            try {
                if (Test-CommandExists 'Start-BitsTransfer') {
                    # Use BITS transfer when available (fastest method)
                    if ($NoProgress) {
                        Start-BitsTransfer -Source $Url -Destination $OutFile -Priority High -ErrorAction Stop
                    } else {
                        Start-BitsTransfer -Source $Url -Destination $OutFile -DisplayName "Downloading file" -Priority High -ErrorAction Stop
                    }
                } else {
                    # Fall back to WebClient if BITS is not available
                    # Suppress default progress bar which slows downloads significantly
                    $originalProgress = $ProgressPreference
                    $ProgressPreference = 'SilentlyContinue'
                    
                    if ($NoProgress) {
                        # Use straight WebClient for maximum speed with no progress
                        $webClient = New-Object System.Net.WebClient
                        $webClient.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                        
                        # Configure proxy if needed
                        $webClient.Proxy = [System.Net.WebRequest]::DefaultWebProxy
                        $webClient.Proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials
                        
                        # Set timeout
                        $webClient.Timeout = $TimeoutSec * 1000
                        
                        # Download file
                        $webClient.DownloadFile($Url, $OutFile)
                    } else {
                        # Custom progress with spinner
                        Write-Host "Download In Progress: " -NoNewline
                        $progressChars = @('/', '-', '\', '|')
                        $currentCharIndex = 0
                        
                        # Create WebClient with event handlers for progress
                        $webClient = New-Object System.Net.WebClient
                        $webClient.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                        
                        # Configure proxy if needed
                        $webClient.Proxy = [System.Net.WebRequest]::DefaultWebProxy
                        $webClient.Proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials
                        
                        # Download with custom progress reporting
                        if ($totalLength -gt 0) {
                            # We know the file size, so we can show percentage
                            $webClient.DownloadFileCompleted += {
                                Write-Host "`rDownload completed!                           " -ForegroundColor Green
                            }
                            
                            $receivedBytes = 0
                            $webClient.DownloadProgressChanged += {
                                param($sender, $e)
                                $receivedBytes = $e.BytesReceived
                                $percent = [math]::Round(($receivedBytes / $totalLength) * 100, 0)
                                $downloaded = [math]::Round($receivedBytes / 1MB, 2)
                                $total = [math]::Round($totalLength / 1MB, 2)
                                Write-Host "`rDownload Progress: $percent% ($downloaded MB of $total MB)" -NoNewline
                            }
                            
                            # Start async download
                            $webClient.DownloadFileAsync((New-Object System.Uri($Url)), $OutFile)
                            
                            # Wait for download to complete
                            while ($webClient.IsBusy) {
                                Start-Sleep -Milliseconds 100
                            }
                        } else {
                            # We don't know the file size, so use spinner
                            $downloadStartTime = Get-Date
                            
                            # Start async download
                            $webClient.DownloadFileAsync((New-Object System.Uri($Url)), $OutFile)
                            
                            # Show spinner while downloading
                            while ($webClient.IsBusy) {
                                $spinChar = $progressChars[$currentCharIndex]
                                $elapsedTime = (Get-Date) - $downloadStartTime
                                $elapsedSec = [math]::Round($elapsedTime.TotalSeconds, 0)
                                
                                Write-Host "`rDownload In Progress: $spinChar (Elapsed: $elapsedSec sec)" -NoNewline
                                $currentCharIndex = ($currentCharIndex + 1) % $progressChars.Length
                                Start-Sleep -Milliseconds 200
                            }
                            
                            Write-Host "`rDownload completed!                           " -ForegroundColor Green
                        }
                    }
                    
                    # Restore original progress preference
                    $ProgressPreference = $originalProgress
                }
                
                $success = $true
            } catch {
                $retryCount++
                if ($retryCount -ge $MaxRetries) {
                    Write-Host "Error downloading file after $MaxRetries attempts: $($_.Exception.Message)" -ForegroundColor Red
                    return $false
                } else {
                    $waitTime = [math]::Pow(2, $retryCount)  # Exponential backoff: 2, 4, 8 seconds
                    Write-Host "Download attempt $retryCount failed. Retrying in $waitTime seconds..." -ForegroundColor Yellow
                    Start-Sleep -Seconds $waitTime
                }
            }
        }
        
        # Verify download was successful by checking file exists and is not empty
        if (Test-Path $OutFile) {
            $fileInfo = Get-Item $OutFile
            if ($fileInfo.Length -eq 0) {
                Write-Host "Warning: Downloaded file is empty!" -ForegroundColor Yellow
                return $false
            } else {
                Write-Host "Download successful! File saved to: $OutFile" -ForegroundColor Green
                return $true
            }
        } else {
            Write-Host "Error: Download completed but file was not created!" -ForegroundColor Red
            return $false
        }
    } catch {
        Write-Host "Error downloading file: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# Function to run a process with progress display
function Start-ProcessWithProgress {
    param (
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$ActivityName,
        [switch]$Wait = $true
    )
    
    Write-Host "Starting $ActivityName..." -ForegroundColor Yellow
    
    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -NoNewWindow:$Wait
    
    if ($Wait) {
        $spinner = @('|', '/', '-', '\')
        $spinnerIndex = 0
        $counter = 0
        
        while (!$process.HasExited) {
            $spinChar = $spinner[$spinnerIndex]
            Write-Host "`r$ActivityName in progress $spinChar" -NoNewline
            
            $spinnerIndex = ($spinnerIndex + 1) % 4
            $counter++
            
            # Add a dot every 10 cycles to show it's still working
            if ($counter % 10 -eq 0) {
                Write-Host "." -NoNewline
            }
            
            Start-Sleep -Milliseconds 200
        }
        
        Write-Host "`r$ActivityName completed                              " -ForegroundColor Green
    }
    
    return $process
}

# Print banner
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "      Backend Application One-Click Setup Script     " -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# Check if script is running with proper execution policy
Write-Host "Checking execution policy..." -ForegroundColor Yellow
try {
    $currentPolicy = Get-ExecutionPolicy
    Write-Host "Current execution policy: $currentPolicy" -ForegroundColor Yellow
    
    if ($currentPolicy -eq "Restricted") {
        Write-Host "WARNING: Your current execution policy is set to 'Restricted', which prevents script execution." -ForegroundColor Red
        Write-Host "You may need to temporarily change your execution policy to run this script." -ForegroundColor Yellow
        Write-Host "To do this, you can run the following command in an administrator PowerShell:" -ForegroundColor Yellow
        Write-Host "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process" -ForegroundColor Yellow
        Write-Host "This will change the policy for the current PowerShell session only." -ForegroundColor Yellow
        
        $response = Read-Host "Would you like to temporarily change the execution policy for this session? (Y/N)"
        if ($response -eq "Y" -or $response -eq "y") {
            try {
                Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force
                Write-Host "Execution policy temporarily changed to RemoteSigned for this session." -ForegroundColor Green
            } catch {
                Write-Host "Failed to change execution policy. Please run PowerShell as Administrator." -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host "Execution policy not changed. Script may not run correctly." -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "Unable to determine execution policy. Continuing anyway..." -ForegroundColor Yellow
}

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "This script needs to be run as Administrator. Please restart with elevated privileges." -ForegroundColor Red
    exit 1
}

# Step 1: Install Python 3.11.0
Write-Host "Step 1: Installing Python 3.11.0..." -ForegroundColor Green
try {
    if (-not (Test-CommandExists python)) {
        # Create temporary directory for downloads
        $tempDir = [System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid().ToString()
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
        
        # Download Python installer - changed to 3.11.0 for better library compatibility
        $pythonUrl = "https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe"
        $pythonInstaller = "$tempDir\python-3.11.0-amd64.exe"
        
        Write-Host "Downloading Python 3.11.0..." -ForegroundColor Yellow
        $downloadSuccess = Download-FileWithProgress -Url $pythonUrl -OutFile $pythonInstaller
        
        if ($downloadSuccess) {
            # Install Python silently with pip and add to PATH
            Write-Host "Installing Python 3.11.0..." -ForegroundColor Yellow
            Start-ProcessWithProgress -FilePath $pythonInstaller -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0" -ActivityName "Python Installation"
            
            # Clean up
            Remove-Item -Path $tempDir -Recurse -Force
            
            # Refresh environment variables
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        } else {
            Handle-Error "Python Download" "Failed to download Python installer"
        }
    } else {
        $pythonVersion = python --version
        Write-Host "Python already installed: $pythonVersion" -ForegroundColor Yellow
    }

    # Check if Python is installed correctly
    $pythonVersion = & python --version
    if ($pythonVersion) {
        Write-Host "Successfully verified Python: $pythonVersion" -ForegroundColor Green
    } else {
        Write-Host "Error: Python installation failed or not found. Please check the installation logs." -ForegroundColor Red
        exit 1
    }
} catch {
    Handle-Error "Python Installation" $_.Exception.Message
}

# Step 2: Install/Upgrade PIP
Write-Host "Step 2: Installing/Upgrading PIP to 25.0.1..." -ForegroundColor Green
try {
    # Ensure correct array format for arguments
    $pipArguments = @("-m", "pip", "install", "--upgrade", "pip==25.0.1")
    $pipProcess = Start-ProcessWithProgress -FilePath "python" -ArgumentList $pipArguments -ActivityName "PIP Upgrade"
    Write-Host "PIP upgraded to version 25.0.1" -ForegroundColor Yellow
} catch {
    Handle-Error "PIP Installation" $.Exception.Message
}

# Step 3: Create and activate virtual environment
Write-Host "Step 3: Setting up virtual environment..." -ForegroundColor Green
try {
    if (-not (Test-Path "venv")) {
        $venvSuccess = Start-ProcessWithProgress -FilePath "python" -ArgumentList "-m", "venv", "venv" -ActivityName "Virtual Environment Creation"
        if (-not $venvSuccess) {
            Handle-Error "Virtual Environment Creation" "Failed to create virtual environment"
        }
    } else {
        Write-Host "Virtual environment already exists" -ForegroundColor Yellow
    }
    
    # Activate virtual environment
    Write-Host "Activating virtual environment..." -ForegroundColor Yellow
    if (Test-Path "venv\Scripts\Activate.ps1") {
        . .\venv\Scripts\Activate.ps1
        Write-Host "Virtual environment activated" -ForegroundColor Green
    } else {
        Handle-Error "Virtual Environment Activation" "Activation script not found"
    }
} catch {
    Handle-Error "Virtual Environment Setup" $_.Exception.Message
}

# Step 4: Install MySQL Server (with check for existing installer)
Write-Host "Step 4: Installing MySQL Server..." -ForegroundColor Green
try {
    if (-not (Test-CommandExists mysql)) {
        # Check if MySQL Installer for Windows is already present on the system
        $mysqlInstallerPaths = @(
            "${env:ProgramFiles(x86)}\MySQL\MySQL Installer for Windows\MySQLInstaller.exe",
            "${env:ProgramFiles}\MySQL\MySQL Installer for Windows\MySQLInstaller.exe",
            "${env:LOCALAPPDATA}\Programs\MySQL\MySQL Installer for Windows\MySQLInstaller.exe"
        )
        
        $installerExists = $false
        $installerPath = ""
        
        foreach ($path in $mysqlInstallerPaths) {
            if (Test-Path $path) {
                $installerExists = $true
                $installerPath = $path
                break
            }
        }
        
        if ($installerExists) {
            # MySQL Installer for Windows already exists, use it directly
            Write-Host "MySQL Installer for Windows found at: $installerPath" -ForegroundColor Yellow
            Write-Host "Launching existing MySQL Installer for Windows..." -ForegroundColor Yellow
        } else {
            # Create temporary directory for downloads
            $tempDir = [System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid().ToString()
            New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
            
            # Define multiple potential download URLs
            $downloadUrls = @(
                "https://cdn.mysql.com/Downloads/MySQLInstaller/mysql-installer-community-8.0.41.0.msi",
                "https://cdn.mysql.com/archives/mysql-installer/mysql-installer-community-8.0.41.0.msi",
                "https://archive.org/download/mysql-installer-community-8.0.41.0/mysql-installer-community-8.0.41.0.msi",
                "https://downloads.mysql.com/archives/get/p/25/file/mysql-installer-community-8.0.41.0.msi"
            )
            
            $mysqlInstaller = "$tempDir\mysql-installer-community.msi"
            $downloadSuccess = $false
            
            foreach ($url in $downloadUrls) {
                Write-Host "Attempting to download MySQL from: $url" -ForegroundColor Yellow
                try {
                    $downloadSuccess = Download-FileWithProgress -Url $url -OutFile $mysqlInstaller
                    
                    # Verify the file was downloaded and is a valid MSI
                    if (Test-Path $mysqlInstaller) {
                        $fileInfo = Get-Item $mysqlInstaller
                        if ($fileInfo.Length -gt 1MB) {
                            $downloadSuccess = $true
                            Write-Host "Successfully downloaded MySQL installer" -ForegroundColor Green
                            break
                        }
                    }
                } catch {
                    Write-Host "Failed to download from $url`: $($_.Exception.Message)" -ForegroundColor Yellow
                    # Continue to the next URL
                }
            }
            
            if (-not $downloadSuccess) {
                Write-Host "All download attempts failed. Would you like to:" -ForegroundColor Yellow
                Write-Host "1. Try the Chocolatey installation method instead" -ForegroundColor Cyan
                Write-Host "2. Exit and download the installer manually from https://dev.mysql.com/downloads/installer/" -ForegroundColor Cyan
                
                $choice = Read-Host "Enter your choice (1 or 2)"
                
                if ($choice -eq "1") {
                    # Install using Chocolatey
                    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
                        Write-Host "Installing Chocolatey..." -ForegroundColor Yellow
                        Set-ExecutionPolicy Bypass -Scope Process -Force
                        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
                        
                        $chocoInstallScript = "$tempDir\choco-install.ps1"
                        Download-FileWithProgress -Url "https://chocolatey.org/install.ps1" -OutFile $chocoInstallScript
                        
                        Start-ProcessWithProgress -FilePath "powershell" -ArgumentList "-File", $chocoInstallScript -ActivityName "Chocolatey Installation"
                        
                        # Refresh environment to use choco
                        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
                    }
                    
                    Write-Host "Installing MySQL via Chocolatey..." -ForegroundColor Yellow
                    Start-ProcessWithProgress -FilePath "choco" -ArgumentList "install", "mysql", "-y" -ActivityName "MySQL Installation via Chocolatey"
                    
                    Write-Host "MySQL installed successfully via Chocolatey" -ForegroundColor Green
                    # Do not return, continue with the script
                } else {
                    throw "Download failed. Please download the installer manually and try again."
                }
            } else {
                # Launch the MSI installer
                Write-Host "Launching MySQL Installer..." -ForegroundColor Yellow
                Start-Process -FilePath "msiexec.exe" -ArgumentList "/i", $mysqlInstaller -Wait
                
                # After installation, the installer should be available in Program Files
                $installerExists = $false
                foreach ($path in $mysqlInstallerPaths) {
                    if (Test-Path $path) {
                        $installerExists = $true
                        $installerPath = $path
                        break
                    }
                }
            }
        }
        
        # Interactive MySQL Installation process using the installer
        if ($installerExists) {
            Write-Host "MySQL Installer will now launch." -ForegroundColor Yellow
            Write-Host "Please follow these steps in the installer:" -ForegroundColor Yellow
            Write-Host "1. Select 'Developer Default' or 'Server only' installation type" -ForegroundColor Yellow
            Write-Host "2. Choose MySQL Server 8.0.x in the Available Products" -ForegroundColor Yellow
            Write-Host "3. Complete the installation wizard (including configuration)" -ForegroundColor Yellow
            Write-Host "4. Make sure to remember the root password you set during configuration" -ForegroundColor Yellow
            
            # Launch MySQL Installer directly
            Start-Process -FilePath $installerPath -Wait
            
            # Prompt user to confirm completion
            Read-Host "Press Enter when MySQL installation is complete"
        }
    } else {
        Write-Host "MySQL already installed. Skipping installation." -ForegroundColor Yellow
    }
    
    # Ensure MySQL service is running
    $mysqlService = Get-Service -Name "MySQL*" -ErrorAction SilentlyContinue
    if ($mysqlService -and $mysqlService.Status -ne "Running") {
        Write-Host "Starting MySQL service..." -ForegroundColor Yellow
        Start-Service -Name $mysqlService.Name
        Start-Sleep -Seconds 5  # Give it time to start
    }

    # Add MySQL to PATH if not already there
    $mysqlPaths = @(
        "C:\Program Files\MySQL\MySQL Server 8.0\bin",
        "C:\Program Files\MySQL\MySQL Server*\bin",
        "C:\xampp\mysql\bin"
    )

    $pathAdded = $false
    foreach ($mysqlPath in $mysqlPaths) {
        $resolvedPaths = Resolve-Path -Path $mysqlPath -ErrorAction SilentlyContinue
        if ($resolvedPaths) {
            $resolvedPath = $resolvedPaths[0].Path
            if ($env:Path -notlike "*$resolvedPath*") {
                $env:Path += ";$resolvedPath"
                $pathAdded = $true
                Write-Host "Added MySQL to PATH: $resolvedPath" -ForegroundColor Green
                break
            }
        }
    }

    if ($pathAdded) {
        # Update system PATH for future sessions
        [Environment]::SetEnvironmentVariable("Path", $env:Path, [EnvironmentVariableTarget]::User)
    }
    
    # Ask user to input the root password they set
    Write-Host "Please enter the root password you set during MySQL configuration:" -ForegroundColor Yellow
    $rootPassword = Read-Host -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($rootPassword)
    $rootPasswordPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
    
    # Test the MySQL connection to verify installation
    Write-Host "Testing MySQL connection..." -ForegroundColor Yellow
    $testQuery = "SELECT VERSION();"
    $testCmd = "mysql -u root -p`"$rootPasswordPlain`" -e `"$testQuery`" --silent"
    
    try {
        $testResult = Invoke-Expression $testCmd
        if ($testResult) {
            Write-Host "MySQL connection successful. MySQL Server is properly installed." -ForegroundColor Green
        } else {
            Write-Host "MySQL connection failed. Installation might be incomplete." -ForegroundColor Red
        }
    } catch {
        Write-Host "Could not connect to MySQL. Please ensure the service is running." -ForegroundColor Yellow
        Write-Host "You may need to start it manually via Services.msc" -ForegroundColor Yellow
    }
    
    # Clean up temp directory if it was created
    if (![string]::IsNullOrEmpty($tempDir) -and (Test-Path -Path $tempDir -ErrorAction SilentlyContinue)) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    
    # Refresh environment variables
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    
    Write-Host "MySQL Server installation process completed" -ForegroundColor Green
} catch {
    Handle-Error "MySQL Installation" $_.Exception.Message
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Step 5: Prompt for project root directory
Write-Host "Step 5: Setting up project directory..." -ForegroundColor Green
$projectRoot = Read-Host "Enter the path to your backend project root folder (or press Enter to use current directory)"

if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    $projectRoot = $scriptDir
}

# Navigate to project root
try {
    Set-Location -Path $projectRoot
    Write-Host "Changed to project directory: $projectRoot" -ForegroundColor Yellow
} catch {
    Handle-Error "Project Directory Navigation" $_.Exception.Message
    exit 1
}

# Step 6: Install Python dependencies
Write-Host "Step 6: Installing Python dependencies..." -ForegroundColor Green
try {
    if (Test-Path "requirements.txt") {
        Start-ProcessWithProgress -FilePath "python" -ArgumentList "-m", "pip", "install", "-r", "requirements.txt" -ActivityName "Dependencies Installation"
        Write-Host "Dependencies installed successfully" -ForegroundColor Yellow
    } else {
        Handle-Error "Dependencies Installation" "requirements.txt file not found in $projectRoot"
        exit 1
    }
} catch {
    Handle-Error "Dependencies Installation" $_.Exception.Message
    exit 1
}

# Step 8: Setup .env file
Write-Host "Step 8: Setting up .env file..." -ForegroundColor Green
try {
    # Prompt for database credentials
    $dbName = Read-Host "Enter database name"
    $dbUser = Read-Host "Enter database username"
    $dbPassword = Read-Host "Enter database password" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($dbPassword)
    $dbPasswordPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
    
    # Create .env file
    $envContent = @"
DB_NAME=$dbName
DB_USER=$dbUser
DB_PASSWORD=$dbPasswordPlain
DB_HOST=localhost
DB_PORT=3306
"@
    
    $envContent | Out-File -FilePath ".env" -Encoding ASCII
    Write-Host ".env file created successfully" -ForegroundColor Yellow
} catch {
    Handle-Error "ENV File Setup" $_.Exception.Message
}

# Step 9: Create database and run migrations
Write-Host "Step 9: Setting up database schema..." -ForegroundColor Green
try {
    # Create database if it doesn't exist
    $createDbScript = "CREATE DATABASE IF NOT EXISTS $dbName;"
    
    $mysqlCmd = "mysql -u `"$dbUser`" -p`"$dbPasswordPlain`" -e `"$createDbScript`""
    Start-ProcessWithProgress -FilePath "cmd.exe" -ArgumentList "/c", $mysqlCmd -ActivityName "Database Creation"
    
    Write-Host "Database created/verified" -ForegroundColor Yellow
    
    # Run Flask migrations
    Write-Host "Initializing database..." -ForegroundColor Yellow
    Start-ProcessWithProgress -FilePath "python" -ArgumentList "-m", "flask", "db", "init" -ActivityName "Flask DB Initialization"
    
    Write-Host "Creating initial migration..." -ForegroundColor Yellow
    Start-ProcessWithProgress -FilePath "python" -ArgumentList "-m", "flask", "db", "migrate", "-m", """Initial migration""" -ActivityName "Flask DB Migration"
    
    Write-Host "Applying migrations..." -ForegroundColor Yellow
    Start-ProcessWithProgress -FilePath "python" -ArgumentList "-m", "flask", "db", "upgrade" -ActivityName "Flask DB Upgrade"
    
    Write-Host "Database schema created successfully" -ForegroundColor Yellow
} catch {
    Handle-Error "Database Setup" $_.Exception.Message
}

# Step 10: Start the backend server
Write-Host "Step 9: Starting the backend server..." -ForegroundColor Green
try {
    Write-Host "Starting server with python run.py" -ForegroundColor Yellow
    Start-Process -FilePath "python" -ArgumentList "run.py" -NoNewWindow
    Write-Host "Backend server started successfully" -ForegroundColor Green
} catch {
    Handle-Error "Server Startup" $_.Exception.Message
}

# Print success message
Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Host "     Backend Application Setup Completed Successfully" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
Write-Host "The backend server is now running." -ForegroundColor Green
Write-Host "You can now open the Sales Forecasting App.exe to:" -ForegroundColor Green
Write-Host "1. Upload a CSV file containing sales data" -ForegroundColor Green
Write-Host "2. Generate a forecast using the integrated ML and LLM models" -ForegroundColor Green
Write-Host "3. View the predicted sales trends for different time frames" -ForegroundColor Green
Write-Host ""