# Database Maintenance & Backup Guide

This guide covers database maintenance, backup, and restore procedures for both PostgreSQL and SQLite.

## Quick Start

For common database operations, use the **`manage_database.sh` script** which simplifies most tasks:

```bash
# PostgreSQL Container Management
./scripts/manage_database.sh start-postgres     # Start PostgreSQL
./scripts/manage_database.sh stop-postgres      # Stop PostgreSQL
./scripts/manage_database.sh status-postgres    # Check status

# Database Operations
./scripts/manage_database.sh backup daily       # Create backup
./scripts/manage_database.sh restore <file>     # Restore from backup
./scripts/manage_database.sh check              # Health check
./scripts/manage_database.sh list               # List backups
```

**The rest of this document** provides detailed SQL commands and advanced operations for power users who need direct database access.

## Debug Commands

Useful commands for debugging PostgreSQL issues:

```bash
# Check if PostgreSQL container is running
docker ps | grep pipeline-logs-postgres

# View PostgreSQL logs
docker logs pipeline-logs-postgres
docker logs -f pipeline-logs-postgres --tail 100

# Check PostgreSQL status and stats
./scripts/manage_database.sh status-postgres

# Connect to PostgreSQL interactively
docker exec -it pipeline-logs-postgres psql -U logextractor -d pipeline_logs

# Check PostgreSQL version
docker exec pipeline-logs-postgres psql -U logextractor -c "SELECT version();"

# Check active connections
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c \
  "SELECT pid, usename, application_name, client_addr, state, query FROM pg_stat_activity;"

# Check database size
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c \
  "SELECT pg_size_pretty(pg_database_size('pipeline_logs'));"

# Check table sizes
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c \
  "SELECT tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
   FROM pg_tables WHERE schemaname='public' ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"

# Check for long-running queries
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c \
  "SELECT pid, now() - query_start AS duration, query FROM pg_stat_activity
   WHERE state = 'active' AND now() - query_start > interval '5 seconds';"

# Check PostgreSQL configuration
docker exec pipeline-logs-postgres psql -U logextractor -c "SHOW ALL;"

# Restart PostgreSQL container
docker restart pipeline-logs-postgres

# View PostgreSQL container resource usage
docker stats pipeline-logs-postgres --no-stream

# Inspect PostgreSQL container configuration
docker inspect pipeline-logs-postgres

# Check PostgreSQL port binding
docker port pipeline-logs-postgres
```

## Table of Contents
- [PostgreSQL Maintenance](#postgresql-maintenance)
- [SQLite Maintenance](#sqlite-maintenance)
- [Backup Strategies](#backup-strategies)
- [Restore Procedures](#restore-procedures)
- [Migration Between Databases](#migration-between-databases)
- [Automated Backup Scripts](#automated-backup-scripts)
- [Monitoring & Health Checks](#monitoring--health-checks)

---

## PostgreSQL Maintenance

### Daily Tasks

#### 1. Backup Database

**Manual Backup:**
```bash
# Using docker-compose
docker exec pipeline-logs-postgres pg_dump -U logextractor pipeline_logs > backup_$(date +%Y%m%d).sql

# Or if using external PostgreSQL
pg_dump -U logextractor -h localhost pipeline_logs > backup_$(date +%Y%m%d).sql
```

**Compressed Backup (recommended for large databases):**
```bash
docker exec pipeline-logs-postgres pg_dump -U logextractor pipeline_logs | gzip > backup_$(date +%Y%m%d).sql.gz
```

**Custom Format (faster restore, parallel support):**
```bash
docker exec pipeline-logs-postgres pg_dump -U logextractor -F c pipeline_logs > backup_$(date +%Y%m%d).dump
```

#### 2. Check Database Size

```bash
# Via docker-compose
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
SELECT
    pg_size_pretty(pg_database_size('pipeline_logs')) as total_size,
    pg_size_pretty(pg_total_relation_size('requests')) as requests_table_size;
"

# Expected output:
#  total_size | requests_table_size
# ------------+--------------------
#  15 MB      | 12 MB
```

#### 3. Monitor Table Growth

```bash
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
SELECT
    COUNT(*) as total_requests,
    COUNT(*) FILTER (WHERE timestamp > NOW() - INTERVAL '24 hours') as last_24h,
    COUNT(*) FILTER (WHERE timestamp > NOW() - INTERVAL '7 days') as last_7d
FROM requests;
"
```

### Weekly Tasks

#### 1. VACUUM Database (Reclaim Space)

```bash
# Analyze and vacuum (non-blocking)
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "VACUUM ANALYZE requests;"

# Full vacuum (requires table lock - do during low traffic)
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "VACUUM FULL requests;"
```

**What VACUUM does:**
- Reclaims space from deleted rows
- Updates statistics for query planner
- Prevents transaction ID wraparound

#### 2. Reindex Tables (Improve Query Performance)

```bash
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "REINDEX TABLE requests;"
```

**When to reindex:**
- Query performance degrades over time
- After bulk deletes
- Index bloat detected

#### 3. Check for Bloat

```bash
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
    n_dead_tup as dead_tuples
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
"
```

### Monthly Tasks

#### 1. Archive Old Data

**Move old requests to archive table:**
```sql
-- Create archive table (one time)
CREATE TABLE IF NOT EXISTS requests_archive (LIKE requests INCLUDING ALL);

-- Move data older than 90 days
BEGIN;
INSERT INTO requests_archive
SELECT * FROM requests WHERE timestamp < NOW() - INTERVAL '90 days';

DELETE FROM requests WHERE timestamp < NOW() - INTERVAL '90 days';
COMMIT;

-- Cleanup
VACUUM ANALYZE requests;
```

**Or export to CSV and delete:**
```bash
# Export old data
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
COPY (SELECT * FROM requests WHERE timestamp < NOW() - INTERVAL '90 days')
TO STDOUT WITH CSV HEADER
" > archive_$(date +%Y%m%d).csv

# Delete old data
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
DELETE FROM requests WHERE timestamp < NOW() - INTERVAL '90 days';
VACUUM ANALYZE requests;
"
```

#### 2. Update Statistics

```bash
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "ANALYZE requests;"
```

### Automated Maintenance (PostgreSQL Auto-Vacuum)

PostgreSQL has built-in autovacuum. Check if it's working:

```bash
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
SELECT
    schemaname,
    tablename,
    last_autovacuum,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE tablename = 'requests';
"
```

**Enable/configure autovacuum** (if needed):
```bash
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
ALTER TABLE requests SET (
    autovacuum_enabled = true,
    autovacuum_vacuum_scale_factor = 0.1,
    autovacuum_analyze_scale_factor = 0.05
);
"
```

---

## SQLite Maintenance

### Daily Tasks

#### 1. Backup Database

**Simple File Copy (database must be idle):**
```bash
# Stop service first
./manage_container.py stop

# Backup
cp logs/pipeline-logs/monitoring.db logs/pipeline-logs/monitoring.db.backup_$(date +%Y%m%d)

# Restart
./manage_container.py start
```

**Online Backup (no downtime):**
```bash
# Using SQLite backup command
sqlite3 logs/pipeline-logs/monitoring.db ".backup logs/pipeline-logs/monitoring.db.backup_$(date +%Y%m%d)"
```

**Compressed Backup:**
```bash
sqlite3 logs/pipeline-logs/monitoring.db ".dump" | gzip > backup_$(date +%Y%m%d).sql.gz
```

#### 2. Check Database Size

```bash
# Database file size
du -h logs/pipeline-logs/monitoring.db*

# Expected output:
# 12M  logs/pipeline-logs/monitoring.db
# 1.2M logs/pipeline-logs/monitoring.db-shm
# 32K  logs/pipeline-logs/monitoring.db-wal

# Row count
sqlite3 logs/pipeline-logs/monitoring.db "
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
sqlite3 logs/pipeline-logs/monitoring.db "VACUUM;"

# Check size before and after
du -h logs/pipeline-logs/monitoring.db
```

**What VACUUM does:**
- Rebuilds database file
- Reclaims deleted space
- Defragments database
- Can take several minutes for large databases

#### 2. Analyze Statistics

```bash
sqlite3 logs/pipeline-logs/monitoring.db "ANALYZE;"
```

#### 3. Integrity Check

```bash
sqlite3 logs/pipeline-logs/monitoring.db "PRAGMA integrity_check;"

# Expected output: "ok"
# If errors, restore from backup immediately
```

### Monthly Tasks

#### 1. Archive Old Data

```bash
# Export old data to CSV
sqlite3 -header -csv logs/pipeline-logs/monitoring.db "
SELECT * FROM requests
WHERE timestamp < datetime('now', '-90 days')
" > archive_$(date +%Y%m%d).csv

# Delete old data
sqlite3 logs/pipeline-logs/monitoring.db "
DELETE FROM requests WHERE timestamp < datetime('now', '-90 days');
VACUUM;
"
```

#### 2. Rebuild Database (Optional - for performance)

```bash
# Export everything
sqlite3 logs/pipeline-logs/monitoring.db .dump > temp_dump.sql

# Backup old database
mv logs/pipeline-logs/monitoring.db logs/pipeline-logs/monitoring.db.old

# Rebuild from dump
sqlite3 logs/pipeline-logs/monitoring.db < temp_dump.sql

# Verify
sqlite3 logs/pipeline-logs/monitoring.db "SELECT COUNT(*) FROM requests;"

# Cleanup
rm temp_dump.sql
```

### WAL Mode Maintenance

**Check WAL status:**
```bash
sqlite3 logs/pipeline-logs/monitoring.db "PRAGMA journal_mode;"
# Should show: wal
```

**Checkpoint WAL (merge WAL into main database):**
```bash
sqlite3 logs/pipeline-logs/monitoring.db "PRAGMA wal_checkpoint(TRUNCATE);"
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

# PostgreSQL
if [ "$DATABASE_URL" ]; then
    docker exec -i pipeline-logs-postgres pg_dump -U logextractor pipeline_logs | \
        gzip > $BACKUP_DIR/postgres_$(date +%Y%m%d).sql.gz
else
    # SQLite
    sqlite3 logs/pipeline-logs/monitoring.db ".backup $BACKUP_DIR/sqlite_$(date +%Y%m%d).db"
fi

# Delete backups older than retention
find $BACKUP_DIR -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete
find $BACKUP_DIR -name "*.db" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $(date)"
```

**Schedule with cron:**
```bash
# Run daily at 2 AM
0 2 * * * /path/to/backup-daily.sh >> /var/log/backup.log 2>&1
```

### Strategy 2: Incremental Backups (PostgreSQL)

**Using WAL archiving:**

To enable WAL archiving, modify the PostgreSQL container startup command in `scripts/manage_database.sh`:

```bash
# Edit start_postgres() function in scripts/manage_database.sh
# Add custom postgres command:
docker run -d \
    --name "$POSTGRES_CONTAINER" \
    ...existing options... \
    postgres:15-alpine \
    postgres -c wal_level=replica -c archive_mode=on -c archive_command='cp %p /archive/%f'

# Also add archive volume mount:
-v ./wal_archive:/archive \
```

**Base backup + WAL files:**
```bash
# Take base backup
docker exec pipeline-logs-postgres pg_basebackup -U logextractor -D /backup/base -Fp -Xs -P

# WAL files are continuously archived to ./wal_archive/
# Can restore to any point in time
```

### Strategy 3: Cloud Backups

**Backup to S3/Cloud Storage:**

```bash
#!/bin/bash
# backup-to-s3.sh

BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql.gz"

# Create backup
docker exec -i pipeline-logs-postgres pg_dump -U logextractor pipeline_logs | gzip > /tmp/$BACKUP_FILE

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

### PostgreSQL Restore

#### 1. From SQL Dump

```bash
# Stop service
python3 manage_container.py stop

# Drop and recreate database
docker exec pipeline-logs-postgres psql -U logextractor -c "DROP DATABASE pipeline_logs;"
docker exec pipeline-logs-postgres psql -U logextractor -c "CREATE DATABASE pipeline_logs;"

# Restore
docker exec -i pipeline-logs-postgres psql -U logextractor pipeline_logs < backup_20250105.sql

# Or from gzip
gunzip -c backup_20250105.sql.gz | docker exec -i pipeline-logs-postgres psql -U logextractor pipeline_logs

# Start service
python3 manage_container.py start
```

#### 2. From Custom Format

```bash
docker exec pipeline-logs-postgres pg_restore -U logextractor -d pipeline_logs -c /backup/backup_20250105.dump
```

#### 3. Point-in-Time Recovery (if WAL archiving enabled)

```bash
# Restore base backup
docker exec pipeline-logs-postgres pg_basebackup restore...

# Specify recovery target
docker exec pipeline-logs-postgres psql -U logextractor -c "
SELECT pg_create_restore_point('before_error');
"

# Configure recovery in postgresql.conf
# restore_command = 'cp /archive/%f %p'
# recovery_target_time = '2025-01-05 14:30:00'

# Restart PostgreSQL
./scripts/manage_database.sh stop-postgres && ./scripts/manage_database.sh start-postgres
```

### SQLite Restore

#### 1. From Backup File

```bash
# Stop service
./manage_container.py stop

# Replace database
cp logs/pipeline-logs/monitoring.db.backup_20250105 logs/pipeline-logs/monitoring.db

# Remove WAL files (important!)
rm logs/pipeline-logs/monitoring.db-wal
rm logs/pipeline-logs/monitoring.db-shm

# Start service
./manage_container.py start
```

#### 2. From SQL Dump

```bash
./manage_container.py stop

# Remove old database
rm logs/pipeline-logs/monitoring.db*

# Restore from dump
gunzip -c backup_20250105.sql.gz | sqlite3 logs/pipeline-logs/monitoring.db

./manage_container.py start
```

---

## Migration Between Databases

### SQLite → PostgreSQL

```bash
# 1. Export from SQLite
sqlite3 logs/pipeline-logs/monitoring.db ".dump" > sqlite_export.sql

# 2. Convert SQLite SQL to PostgreSQL SQL
sed -i 's/AUTOINCREMENT//' sqlite_export.sql
sed -i 's/INTEGER PRIMARY KEY/SERIAL PRIMARY KEY/' sqlite_export.sql

# 3. Import to PostgreSQL
docker exec -i pipeline-logs-postgres psql -U logextractor pipeline_logs < sqlite_export.sql

# 4. Update .env
echo "DATABASE_URL=postgresql://logextractor:password@postgres:5432/pipeline_logs" >> .env

# 5. Restart
python3 manage_container.py restart
```

### PostgreSQL → SQLite

```bash
# 1. Export from PostgreSQL
docker exec pipeline-logs-postgres pg_dump -U logextractor pipeline_logs > postgres_export.sql

# 2. Stop service
python3 manage_container.py stop

# 3. Remove DATABASE_URL from .env
sed -i '/DATABASE_URL/d' .env

# 4. Import to SQLite (may need manual conversion)
# Note: PostgreSQL-specific syntax may need adjustment

# 5. Start service (will use SQLite)
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
# Pipeline Logs Backups

# Daily backup at 2 AM
0 2 * * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup daily >> /var/log/pipeline-logs-backup.log 2>&1

# Weekly backup on Sunday at 3 AM
0 3 * * 0 cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup weekly >> /var/log/pipeline-logs-backup.log 2>&1

# Monthly backup on 1st at 4 AM
0 4 1 * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh backup monthly >> /var/log/pipeline-logs-backup.log 2>&1

# Health check every hour
0 * * * * cd /path/to/extract-build-logs && ./scripts/manage_database.sh check >> /var/log/pipeline-logs-health.log 2>&1
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
Type: postgresql
Date: Thu Jan  7 10:30:00 UTC 2025
===================================

PostgreSQL Health Check
-----------------------
Database connection: ✓ OK
Requests table: ✓ OK (1234 rows)
Recent activity (last hour): ✓ 45 requests
Database size: ✓ 15 MB
Active connections: ✓ 3
Last autovacuum: ✓ 2025-01-07 09:15:23

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

### PostgreSQL

1. **Always use transactions** for bulk operations
2. **Monitor autovacuum** - ensure it's running
3. **Regular backups** - daily minimum, test restores monthly
4. **Archive old data** - keep database under 10GB for best performance
5. **Use connection pooling** if scaling (PgBouncer)
6. **Monitor slow queries** - add indexes if needed

### SQLite

1. **Always stop service** before file-based backups
2. **Use WAL mode** (enabled by default in our setup)
3. **Regular VACUUM** - weekly for active databases
4. **Keep database small** - archive data older than 90 days
5. **Integrity checks** - weekly minimum
6. **Single writer** - don't run multiple instances with same SQLite file

### Both

1. **Test restores** - backup is only good if restore works
2. **Monitor disk space** - keep 50% free for database operations
3. **Automate backups** - don't rely on manual processes
4. **Off-site backups** - copy to cloud/remote location
5. **Document procedures** - ensure team knows how to restore
6. **Monitor logs** - check backup logs daily

---

## Troubleshooting

### PostgreSQL Issues

**Problem**: "too many connections"
```bash
# Check connection limit
docker exec pipeline-logs-postgres psql -U logextractor -c "SHOW max_connections;"

# Kill idle connections
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'pipeline_logs'
AND state = 'idle'
AND state_change < now() - interval '1 hour';
"
```

**Problem**: Slow queries
```bash
# Enable slow query logging
docker exec pipeline-logs-postgres psql -U logextractor -c "
ALTER DATABASE pipeline_logs SET log_min_duration_statement = 1000;
"

# Check logs
docker logs pipeline-logs-postgres | grep "duration"
```

### SQLite Issues

**Problem**: "database is locked"
```bash
# Check for long-running processes
lsof logs/pipeline-logs/monitoring.db

# Force checkpoint WAL
sqlite3 logs/pipeline-logs/monitoring.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

**Problem**: Database corruption
```bash
# Try recovery
sqlite3 logs/pipeline-logs/monitoring.db ".recover" | sqlite3 recovered.db

# If that fails, restore from backup
```

---

## Quick Reference Commands

### PostgreSQL
```bash
# Backup
docker exec pipeline-logs-postgres pg_dump -U logextractor pipeline_logs | gzip > backup.sql.gz

# Restore
gunzip -c backup.sql.gz | docker exec -i pipeline-logs-postgres psql -U logextractor pipeline_logs

# Size
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "SELECT pg_size_pretty(pg_database_size('pipeline_logs'));"

# Vacuum
docker exec pipeline-logs-postgres psql -U logextractor -d pipeline_logs -c "VACUUM ANALYZE;"
```

### SQLite
```bash
# Backup
sqlite3 logs/pipeline-logs/monitoring.db ".backup backup.db"

# Restore
cp backup.db logs/pipeline-logs/monitoring.db

# Size
du -h logs/pipeline-logs/monitoring.db

# Vacuum
sqlite3 logs/pipeline-logs/monitoring.db "VACUUM;"
```

---

For more information, see:
- PostgreSQL Backup: https://www.postgresql.org/docs/current/backup.html
- SQLite Backup: https://www.sqlite.org/backup.html
