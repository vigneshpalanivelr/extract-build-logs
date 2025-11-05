# Deployment Options Explained

## Question 1: Why docker-compose.yml when we have manage_container.py?

You have **TWO deployment options** - pick the one that fits your needs:

### Option A: `manage_container.py` (Simple, Single Container)

**What it does:**
- Manages ONLY the log extractor container
- You provide your own PostgreSQL (or use SQLite fallback)
- Uses simple Docker commands under the hood
- No docker-compose needed

**Best for:**
- ✓ When you already have PostgreSQL running
- ✓ When you want systemd service management
- ✓ Simple single-container deployment
- ✓ Production servers with existing infrastructure

**Usage:**
```bash
./manage_container.py build
./manage_container.py start
./manage_container.py stop
./manage_container.py status
./manage_container.py logs
```

**Database:**
- Connects to your existing PostgreSQL (set DATABASE_URL in .env)
- OR falls back to SQLite (logs/monitoring.db)

---

### Option B: `docker-compose.yml` (Complete Stack)

**What it does:**
- Manages PostgreSQL + Log Extractor together
- Creates network, volumes, health checks automatically
- PostgreSQL is started and managed by docker-compose
- All-in-one solution

**Best for:**
- ✓ Quick setup / testing
- ✓ When you DON'T have PostgreSQL
- ✓ Consistent dev/prod environments
- ✓ Multiple related services

**Usage:**
```bash
docker-compose up -d        # Start both services
docker-compose down         # Stop both services
docker-compose logs -f      # View logs
docker-compose ps           # Check status
```

**Database:**
- PostgreSQL container is included and automatically configured
- No manual PostgreSQL setup needed

---

## Comparison

| Feature | manage_container.py | docker-compose.yml |
|---------|--------------------|--------------------|
| **PostgreSQL** | You provide (or SQLite) | Included automatically |
| **Commands** | `./manage_container.py` | `docker-compose` |
| **Systemd** | ✓ Supported | Manual setup needed |
| **Simplicity** | Simple single container | Complete stack |
| **Production** | Recommended | Also works |
| **Database backup** | Your responsibility | Your responsibility |

---

## Which Should You Use?

### Use `manage_container.py` if:
- You have existing PostgreSQL server
- You want systemd service (auto-start on boot)
- You're deploying to production servers
- You want fine-grained control

**Current setup (you're using this):**
```bash
# Your current workflow:
./manage_container.py build
sudo systemctl start gitlab-log-extractor
sudo systemctl status gitlab-log-extractor
```

### Use `docker-compose.yml` if:
- You want everything in one command
- You're testing/developing locally
- You DON'T have PostgreSQL
- You want Docker to manage everything

**Alternative workflow:**
```bash
# Complete stack in one command:
docker-compose up -d
docker-compose logs -f log-extractor
```

---

## Can You Use Both?

**NO - they conflict!** Both try to create container named `bfa-gitlab-pipeline-extractor`.

Pick one approach:
- **Option A**: Use `manage_container.py` + systemd (production)
- **Option B**: Use `docker-compose.yml` (development/testing)

---

## Question 2: Where does monitoring data come from if PostgreSQL is not started?

### Automatic SQLite Fallback

The system has **built-in fallback** logic:

```python
# In src/monitoring.py:79-104
def __init__(self, db_path: str = "./logs/monitoring.db"):
    self.db_url = os.getenv('DATABASE_URL')

    if self.db_url and HAS_POSTGRES:
        self.db_type = 'postgresql'
        logger.info("Using PostgreSQL database")
    else:
        self.db_type = 'sqlite'
        logger.info(f"Using SQLite database: {db_path}")
```

### How It Works

**Scenario 1: PostgreSQL is running**
```bash
# In .env:
DATABASE_URL=postgresql://user:pass@localhost:5432/pipeline_logs

# Result:
✓ Uses PostgreSQL for monitoring
✓ monitor.get_summary() queries PostgreSQL
✓ All monitoring data stored in PostgreSQL
```

**Scenario 2: PostgreSQL NOT running (your current situation)**
```bash
# In .env:
DATABASE_URL=  # Not set or PostgreSQL not reachable

# Result:
✓ Automatically falls back to SQLite
✓ Uses file: ./logs/monitoring.db
✓ monitor.get_summary() queries SQLite
✓ All monitoring data stored in SQLite file
```

### Check Which Database You're Using

```bash
# Check logs on startup:
grep "Using.*database" logs/application.log

# You'll see ONE of:
# "Using PostgreSQL database: localhost:5432/pipeline_logs"
# OR
# "Using SQLite database: ./logs/monitoring.db"
```

### Where Your Monitoring Data Is

**If NOT using PostgreSQL:**
```bash
# All monitoring data is in SQLite file:
ls -lh logs/monitoring.db

# You can query it directly:
sqlite3 logs/monitoring.db "SELECT COUNT(*) FROM requests;"
sqlite3 logs/monitoring.db "SELECT * FROM requests LIMIT 5;"
```

**If using PostgreSQL:**
```bash
# Data is in PostgreSQL database
psql -h localhost -U logextractor -d pipeline_logs -c "SELECT COUNT(*) FROM requests;"
```

### Summary

**Your current situation:**
- ✓ Using `manage_container.py` (Option A)
- ✓ NOT using docker-compose
- ✓ Using SQLite fallback (logs/monitoring.db)
- ✓ Monitoring data comes from SQLite file
- ✓ `./manage_container.py monitor` reads from SQLite

**To switch to PostgreSQL:**

**Option 1: Start your own PostgreSQL**
```bash
# Install PostgreSQL
sudo apt install postgresql

# Create database
sudo -u postgres psql -c "CREATE DATABASE pipeline_logs;"
sudo -u postgres psql -c "CREATE USER logextractor WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE pipeline_logs TO logextractor;"

# Update .env
echo "DATABASE_URL=postgresql://logextractor:your_password@localhost:5432/pipeline_logs" >> .env

# Restart
sudo systemctl restart gitlab-log-extractor

# Check logs
tail -f logs/application.log | grep "Using.*database"
# Should say: "Using PostgreSQL database"
```

**Option 2: Use docker-compose (includes PostgreSQL)**
```bash
# Stop current setup
sudo systemctl stop gitlab-log-extractor
./manage_container.py remove

# Start with docker-compose
docker-compose up -d

# PostgreSQL is now running and connected automatically
```

---

## Recommendation for Production

**Current setup is fine!** You're using:
- ✓ `manage_container.py` for management
- ✓ Systemd for auto-start
- ✓ SQLite for monitoring (lightweight, no extra dependencies)

**When to add PostgreSQL:**
- If you expect high webhook traffic (>100 requests/min)
- If you want better query performance for monitoring
- If you want to run SQL analytics on monitoring data

**For most use cases, SQLite is sufficient!**
