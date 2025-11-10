# Quick Start: Deploying Pre-Built Image to New Server

## 🎯 The Problem You Encountered

When shipping a Docker image from one server to another:
- ✅ Docker image contains: Application code, dependencies
- ❌ Docker image does NOT contain: `.env` file, `logs/` directory

This causes permission errors on the new server.

## ✅ Solution (3 Steps)

### 1️⃣ Create .env File
```bash
cd /home/vishal/extract-build-logs/
cp .env.example .env
nano .env  # Add your GITLAB_URL and GITLAB_TOKEN
```

### 2️⃣ Create Logs Directory
```bash
mkdir -p logs
chmod 755 logs
chown vishal:vishal logs  # Use your username
```

### 3️⃣ Start Container
```bash
./manage_container.py start
```

## 🔍 Why This Happened

### Root Cause Analysis

**Issue #1: Missing .env File**
```
Docker Mount Behavior:
  If file doesn't exist → Docker creates it as directory → Permission denied

Your daemon: --userns-remap vishal:secusers
  Container UID 0 → Host UID 100000+ (no write permission)
```

**Issue #2: Missing logs Directory**
```
Docker Volume Mount:
  If directory doesn't exist → Docker creates it with wrong ownership

Result: Container can't write logs
```

### Why It Worked on Build Server

| Server A (Build)           | Server B (Deploy)          |
|----------------------------|----------------------------|
| ✅ .env file exists        | ❌ .env file missing       |
| ✅ logs/ directory exists  | ❌ logs/ directory missing |
| ✅ Permissions correct     | ❌ No pre-existing files   |

## 🛠️ What Was Fixed

### Code Changes (manage_container.py)

**Before:**
```python
# Only created logs when starting NEW container
Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
```

**After:**
```python
# ALWAYS ensures logs directory exists with proper permissions
logs_path = Path(LOGS_DIR)
if not logs_path.exists():
    logs_path.mkdir(parents=True, exist_ok=True)
    logs_path.chmod(0o755)  # Set permissions
    console.print(f"✓ Created logs directory: {LOGS_DIR}")
```

**Benefits:**
- ✅ Auto-creates logs directory before starting container
- ✅ Sets proper permissions automatically
- ✅ Warns if directory exists but isn't writable
- ✅ Works for both new AND existing containers

### Docker Container Configuration

```python
container = client.containers.run(
    IMAGE_NAME,
    name=CONTAINER_NAME,
    detach=True,
    user='root',          # ← Runs as root inside container
    userns_mode='host',   # ← Bypasses namespace remapping
    ...
)
```

**What this does:**
- `user='root'`: Container runs as root internally
- `userns_mode='host'`: Maps container root → host root (bypasses daemon's `--userns-remap`)

## 📊 Comparison: Before vs After

| Scenario                    | Before Fix     | After Fix      |
|-----------------------------|----------------|----------------|
| Deploy to new server        | ❌ Manual setup | ✅ Auto-setup  |
| Missing logs directory      | ❌ Fails       | ✅ Auto-creates |
| Wrong permissions           | ❌ Manual fix  | ✅ Auto-corrects |
| User namespace remapping    | ❌ Issues      | ✅ Bypassed    |

## 🚀 Testing the Fix

```bash
# Test on a clean environment
cd /tmp
git clone <repo-url> test-deploy
cd test-deploy

# Create .env
cp .env.example .env
# Edit with credentials

# Start (logs directory auto-created)
./manage_container.py start
# Should see: "✓ Created logs directory: ./logs"

# Verify
./manage_container.py status
curl http://localhost:8000/health
```

## 📝 Deployment Checklist

For future deployments to new servers:

**Required Manual Steps:**
- [ ] Transfer Docker image to new server
- [ ] Copy `manage_container.py` to new server
- [ ] Copy `.env.example` to new server
- [ ] Create `.env` file with credentials
- [ ] Install Python dependencies: `pip install docker rich python-dotenv`

**Auto-handled by manage_container.py:**
- [x] Create logs directory
- [x] Set proper permissions
- [x] Configure container with namespace bypass
- [x] Mount volumes correctly

## 🔐 Security Notes

### Docker User Namespace Remapping

Your daemon runs with: `--userns-remap vishal:secusers`

**What it does:**
- Maps container UIDs to high host UIDs (100000+)
- Improves security by isolating container users
- Can cause permission issues with volume mounts

**Our solution:**
- Use `userns_mode='host'` to bypass remapping
- Only for this container (doesn't affect daemon security)
- Allows root in container = root on host (needed for log writes)

**Trade-off:**
- ⚠️ Container root has more privileges on host
- ✅ But container is isolated and trusted code
- ✅ Necessary for proper file permissions with mounted volumes

### Better Alternatives (Future)

1. **Run container as specific UID:**
   ```python
   user='1000:1000'  # Run as vishal's UID
   ```

2. **Use Docker secrets:**
   ```bash
   docker secret create gitlab_token .env
   ```

3. **Pass env vars directly (no .env mount):**
   ```python
   environment={'GITLAB_URL': 'https://...', ...}
   ```

## 📚 Full Documentation

For complete details, see:
- [DEPLOYMENT.md](DEPLOYMENT.md) - Full deployment guide
- [README.md](README.md) - Application documentation
- [OPERATIONS.md](OPERATIONS.md) - Operations and monitoring

---

**Last Updated:** 2025-11-10
**Issue Resolved:** Docker permission errors on new server deployment
