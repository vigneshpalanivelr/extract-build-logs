# SQLite Database Maintenance & Backup Guide

This guide covers SQLite database maintenance, backup, and restore procedures for the monitoring database.

## Quick Start

For common database operations, use the **`manage_database.sh` script** which simplifies most tasks:

```bash
# Database Operations
./scripts/manage_database.sh backup daily       # Create backup
./scripts/manage_database.sh restore <file>     # Restore from backup
./scripts/manage_database.sh check              # Health check
./scripts/manage_database.sh list               # List backups
```

**The rest of this document** provides detailed SQL commands and advanced operations for power users who need direct database access.

## Debug Commands

Useful commands for debugging SQLite database issues:

```bash
# Check database file size
du -h logs/monitoring.db*

# Check database integrity
sqlite3 logs/monitoring.db "PRAGMA integrity_check;"

# Check database version
sqlite3 logs/monitoring.db "SELECT sqlite_version();"

# Check WAL mode status
sqlite3 logs/monitoring.db "PRAGMA journal_mode;"

# Check database configuration
sqlite3 logs/monitoring.db "PRAGMA compile_options;"

# View database schema
sqlite3 logs/monitoring.db ".schema"

# Count total records
sqlite3 logs/monitoring.db "SELECT COUNT(*) FROM requests;"

# Check recent activity
sqlite3 logs/monitoring.db "SELECT COUNT(*) FROM requests WHERE timestamp > datetime('now', '-1 hour');"
```

## Table of Contents
- [SQLite Maintenance](#sqlite-maintenance)
- [Backup Strategies](#backup-strategies)
- [Restore Procedures](#restore-procedures)
- [Automated Backup Scripts](#automated-backup-scripts)
- [Monitoring & Health Checks](#monitoring--health-checks)

---

## SQLite Maintenance

### Daily Tasks

#### 1. Backup Database

**Simple File Copy (database must be idle):**
```bash
# Stop service first
./manage_container.py stop

# Backup
cp logs/monitoring.db logs/monitoring.db.backup_$(date +%Y%m%d)

# Restart
./manage_container.py start
```

**Online Backup (no downtime):**
```bash
# Using SQLite backup command
sqlite3 logs/monitoring.db ".backup logs/monitoring.db.backup_$(date +%Y%m%d)"
```

**Compressed Backup:**
```bash
sqlite3 logs/monitoring.db ".dump" | gzip > backup_$(date +%Y%m%d).sql.gz
```

#### 2. Check Database Size

```bash
# Database file size
du -h logs/monitoring.db*

# Expected output:
# 12M  logs/monitoring.db
# 1.2M logs/monitoring.db-shm
# 32K  logs/monitoring.db-wal

# Row count
sqlite3 logs/monitoring.db "
SELECT
    COUNT(*) as total_requests,
    (SELECT COUNT(*) FROM requests WHERE timestamp > datetime('now', '-1 day')) as last_24h
FROM requests;
"
```

### Weekly Tasks

#### 1. VACUUM Database (Reclaim Space)

```bash
# Full vacuum (rewrites entire database)
sqlite3 logs/monitoring.db "VACUUM;"

# Check size before and after
du -h logs/monitoring.db
```

**What VACUUM does:**
- Rebuilds database file
- Reclaims deleted space
- Defragments database
- Can take several minutes for large databases

#### 2. Analyze Statistics

```bash
sqlite3 logs/monitoring.db "ANALYZE;"
```

#### 3. Integrity Check

```bash
sqlite3 logs/monitoring.db "PRAGMA integrity_check;"

# Expected output: "ok"
# If errors, restore from backup immediately
```

### Monthly Tasks

#### 1. Archive Old Data

```bash
# Export old data to CSV
sqlite3 -header -csv logs/monitoring.db "
SELECT * FROM requests
WHERE timestamp < datetime('now', '-90 days')
" > archive_$(date +%Y%m%d).csv

# Delete old data
sqlite3 logs/monitoring.db "
DELETE FROM requests WHERE timestamp < datetime('now', '-90 days');
VACUUM;
"
```

#### 2. Rebuild Database (Optional - for performance)

```bash
# Export everything
sqlite3 logs/monitoring.db .dump > temp_dump.sql

# Backup old database
mv logs/monitoring.db logs/monitoring.db.old

# Rebuild from dump
sqlite3 logs/monitoring.db < temp_dump.sql

# Verify
sqlite3 logs/monitoring.db "SELECT COUNT(*) FROM requests;"

# Cleanup
rm temp_dump.sql
```

### WAL Mode Maintenance

**Check WAL status:**
```bash
sqlite3 logs/monitoring.db "PRAGMA journal_mode;"
# Should show: wal
```

**Checkpoint WAL (merge WAL into main database):**
```bash
sqlite3 logs/monitoring.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

---

## Backup Strategies

### Strategy 1: Daily Backups (Recommended)

**Keep last 7 daily backups:**

```bash
#!/bin/bash
# backup-daily.sh

BACKUP_DIR="/backups/daily"
RETENTION_DAYS=7

mkdir -p $BACKUP_DIR

# SQLite backup
sqlite3 logs/monitoring.db ".backup $BACKUP_DIR/sqlite_$(date +%Y%m%d).db"

# Delete backups older than retention
find $BACKUP_DIR -name "*.db" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $(date)"
```

**Schedule with cron:**
```bash
# Run daily at 2 AM
0 2 * * * /path/to/backup-daily.sh >> /var/log/backup.log 2>&1
```

### Strategy 2: Cloud Backups

**Backup to S3/Cloud Storage:**

```bash
#!/bin/bash
# backup-to-s3.sh

BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).db"

# Create backup
sqlite3 logs/monitoring.db ".backup /tmp/$BACKUP_FILE"

# Upload to S3 (requires aws cli)
aws s3 cp /tmp/$BACKUP_FILE s3://your-bucket/pipeline-logs/

# Cleanup local
rm /tmp/$BACKUP_FILE

echo "Backup uploaded to S3: $BACKUP_FILE"
```

**Schedule:**
```bash
# Daily at 3 AM
0 3 * * * /path/to/backup-to-s3.sh
```

---

## Restore Procedures

### SQLite Restore

#### 1. From Backup File

```bash
# Stop service
./manage_container.py stop

# Replace database
cp logs/monitoring.db.backup_20250105 logs/monitoring.db

# Remove WAL files (important!)
rm logs/monitoring.db-wal
rm logs/monitoring.db-shm

# Start service
./manage_container.py start
```

#### 2. From SQL Dump

```bash
./manage_container.py stop

# Remove old database
rm logs/monitoring.db*

# Restore from dump
gunzip -c backup_20250105.sql.gz | sqlite3 logs/monitoring.db

./manage_container.py start
```

---

## Automated Backup Scripts

The project includes a database management script (`scripts/manage_database.sh`) that handles backup, restore, and health check operations for both PostgreSQL and SQLite databases.

### Using the Database Management Script

**Create backup:**
```bash
# Daily backup (keeps last 7)
./scripts/manage_database.sh backup daily

# Weekly backup (keeps last 4)
./scripts/manage_database.sh backup weekly

# Monthly backup (keeps last 6)
./scripts/manage_database.sh backup monthly
```

**Restore from backup:**
```bash
# List available backups
./scripts/manage_database.sh list

# Restore from specific backup
./scripts/manage_database.sh restore backups/daily/postgres_daily_20250107_020000.sql.gz
```

**Check database health:**
```bash
./scripts/manage_database.sh check
```

### Cron Schedule

Example cron schedule using the management script (add to `/etc/crontab` or user crontab):

```bash
# SQLite Database Backups

# Daily backup at 2 AM
0 2 * * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup daily >> /var/log/sqlite-backup.log 2>&1

# Weekly backup on Sunday at 3 AM
0 3 * * 0 cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup weekly >> /var/log/sqlite-backup.log 2>&1

# Monthly backup on 1st at 4 AM
0 4 1 * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup monthly >> /var/log/sqlite-backup.log 2>&1

# Health check every hour
0 * * * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh check >> /var/log/sqlite-health.log 2>&1
```

See `scripts/crontab.example` for more scheduling examples.

---

## Monitoring & Health Checks

### Database Health Check

The project includes a database management script that handles health checks for both PostgreSQL and SQLite databases.

**Run health check:**
```bash
./scripts/manage_database.sh check
```

**Example output:**
```
===================================
Database Health Check
Type: sqlite
Date: Thu Jan  7 10:30:00 UTC 2025
===================================

SQLite Health Check
-------------------
Database connection: ✓ OK
Requests table: ✓ OK (1234 rows)
Recent activity (last hour): ✓ 45 requests
Database size: ✓ 12 MB
Integrity check: ✓ OK
WAL mode: ✓ Enabled

===================================
✓ Health Check: PASSED
===================================
```

**Schedule health checks with cron:**
```bash
# Every hour
0 * * * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh check >> /var/log/db-health.log 2>&1
```

---

## Best Practices

### SQLite

1. **Always stop service** before file-based backups
2. **Use WAL mode** (enabled by default in our setup)
3. **Regular VACUUM** - weekly for active databases
4. **Keep database small** - archive data older than 90 days
5. **Integrity checks** - weekly minimum
6. **Single writer** - don't run multiple instances with same SQLite file

### General Practices

1. **Test restores** - backup is only good if restore works
2. **Monitor disk space** - keep 50% free for database operations
3. **Automate backups** - don't rely on manual processes
4. **Off-site backups** - copy to cloud/remote location
5. **Document procedures** - ensure team knows how to restore
6. **Monitor logs** - check backup logs daily
7. **Regular VACUUM** - keeps database file size optimized
8. **Integrity checks** - detect corruption early

---

## Troubleshooting

### SQLite Issues

**Problem**: "database is locked"
```bash
# Check for long-running processes
lsof logs/monitoring.db

# Force checkpoint WAL
sqlite3 logs/monitoring.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Check if service is still running
./manage_container.py status
```

**Problem**: Database corruption
```bash
# Try recovery
sqlite3 logs/monitoring.db ".recover" | sqlite3 recovered.db

# If that fails, restore from backup
cp logs/monitoring.db.backup_YYYYMMDD logs/monitoring.db

# Restart service
./manage_container.py restart
```

**Problem**: Slow queries
```bash
# Check database size
du -h logs/monitoring.db

# Run VACUUM to optimize
sqlite3 logs/monitoring.db "VACUUM;"

# Rebuild indexes
sqlite3 logs/monitoring.db "REINDEX;"

# Archive old data
sqlite3 logs/monitoring.db "DELETE FROM requests WHERE timestamp < datetime('now', '-90 days');"
```

---

## Quick Reference Commands

### SQLite
```bash
# Backup
sqlite3 logs/monitoring.db ".backup backup.db"

# Restore
cp backup.db logs/monitoring.db

# Size
du -h logs/monitoring.db

# Vacuum
sqlite3 logs/monitoring.db "VACUUM;"

# Integrity Check
sqlite3 logs/monitoring.db "PRAGMA integrity_check;"

# WAL Checkpoint
sqlite3 logs/monitoring.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

---

For more information, see:
- SQLite Backup: https://www.sqlite.org/backup.html
- SQLite WAL Mode: https://www.sqlite.org/wal.html
