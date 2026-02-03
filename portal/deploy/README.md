# Deployment Guide

This directory contains deployment configurations for the Publisher Performance Portal.

## Files

| File | Description |
|------|-------------|
| `benchmark-daily.service` | Systemd service for the daily batch job |
| `benchmark-daily.timer` | Systemd timer that triggers the service at 6 AM UTC |
| `install.sh` | Automated installation script |

## Quick Start

### Automated Installation (Recommended)

```bash
# As root or with sudo
sudo ./install.sh
```

This will:
1. Create a `benchmark` system user
2. Set up the application directory at `/opt/integration-benchmarking`
3. Create a PostgreSQL database
4. Install Python dependencies
5. Run database migrations
6. Install and enable the systemd timer

### Manual Installation

1. **Create system user:**
   ```bash
   sudo useradd --system --no-create-home benchmark
   ```

2. **Create application directory:**
   ```bash
   sudo mkdir -p /opt/integration-benchmarking
   sudo chown benchmark:benchmark /opt/integration-benchmarking
   ```

3. **Copy application files and create venv:**
   ```bash
   sudo -u benchmark python3 -m venv /opt/integration-benchmarking/venv
   sudo -u benchmark /opt/integration-benchmarking/venv/bin/pip install -r requirements.txt
   ```

4. **Create PostgreSQL database:**
   ```bash
   sudo -u postgres createuser benchmark
   sudo -u postgres createdb -O benchmark benchmark
   ```

5. **Create `.env` file:**
   ```bash
   cp portal/.env.example portal/.env
   # Edit portal/.env with your credentials
   ```

6. **Run migrations:**
   ```bash
   cd /opt/integration-benchmarking
   alembic -c portal/alembic.ini upgrade head
   ```

7. **Install systemd files:**
   ```bash
   sudo cp portal/deploy/benchmark-daily.service /etc/systemd/system/
   sudo cp portal/deploy/benchmark-daily.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable benchmark-daily.timer
   sudo systemctl start benchmark-daily.timer
   ```

## Operations

### Check Timer Status

```bash
# View timer status
systemctl status benchmark-daily.timer

# List all timers
systemctl list-timers --all | grep benchmark
```

### Run Manually

```bash
# Run the batch job now
sudo systemctl start benchmark-daily.service

# Or run directly
sudo -u benchmark /opt/integration-benchmarking/venv/bin/python \
    -m portal.batch.daily_benchmark_runner

# Dry run (no database writes)
sudo -u benchmark /opt/integration-benchmarking/venv/bin/python \
    -m portal.batch.daily_benchmark_runner --dry-run

# Run for a specific date
sudo -u benchmark /opt/integration-benchmarking/venv/bin/python \
    -m portal.batch.daily_benchmark_runner --date 2025-01-25

# Run for a specific publisher
sudo -u benchmark /opt/integration-benchmarking/venv/bin/python \
    -m portal.batch.daily_benchmark_runner --publisher-id 55
```

### View Logs

```bash
# Follow logs in real-time
journalctl -u benchmark-daily.service -f

# View last run
journalctl -u benchmark-daily.service --since "6 hours ago"

# View all logs
journalctl -u benchmark-daily.service
```

### Troubleshooting

**Timer not firing:**
```bash
# Check if timer is enabled
systemctl is-enabled benchmark-daily.timer

# Check timer details
systemctl show benchmark-daily.timer
```

**Service failing:**
```bash
# Check service status
systemctl status benchmark-daily.service

# View detailed error
journalctl -u benchmark-daily.service -n 50 --no-pager
```

**Database connection issues:**
```bash
# Test database connection
sudo -u benchmark psql -h localhost -U benchmark -d benchmark -c "SELECT 1"

# Check .env file
cat /opt/integration-benchmarking/portal/.env
```

## Schedule

The timer is configured to run at **6:00 AM UTC daily**.

This timing ensures:
- Benchmark data (Datascope) for T-1 is available
- Results are ready before business hours in most timezones
- Plenty of time for the batch to complete before the next market day

To change the schedule, edit `benchmark-daily.timer`:
```ini
[Timer]
OnCalendar=*-*-* 06:00:00 UTC
```

Common alternatives:
- `OnCalendar=*-*-* 00:00:00 UTC` - Midnight UTC
- `OnCalendar=Mon..Fri *-*-* 06:00:00 UTC` - Weekdays only
- `OnCalendar=*-*-* 06,18:00:00 UTC` - Twice daily (6 AM and 6 PM)

After editing, reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart benchmark-daily.timer
```
