# Deployment Guide - GitLab Pipeline Log Extractor

This guide explains how to deploy the containerized application on a new server after building the Docker image on a different machine.

## 📋 Prerequisites

- Docker installed on the target server
- Docker image transferred to target server (via registry or `docker save/load`)
- Access to GitLab instance with API token
- Port 8000 (or custom port) available

## 🚀 Quick Start (New Server Deployment)

### Step 1: Transfer Docker Image

**Option A: Using Docker Registry** (Recommended)
```bash
# On build server (Server A)
docker tag bfa-gitlab-pipeline-extractor your-registry/bfa-gitlab-pipeline-extractor:latest
docker push your-registry/bfa-gitlab-pipeline-extractor:latest

# On deployment server (Server B)
docker pull your-registry/bfa-gitlab-pipeline-extractor:latest
docker tag your-registry/bfa-gitlab-pipeline-extractor:latest bfa-gitlab-pipeline-extractor
```

**Option B: Using docker save/load**
```bash
# On build server (Server A)
docker save bfa-gitlab-pipeline-extractor | gzip > bfa-extractor.tar.gz
scp bfa-extractor.tar.gz user@server-b:/tmp/

# On deployment server (Server B)
gunzip -c /tmp/bfa-extractor.tar.gz | docker load
```

### Step 2: Clone/Copy Repository Files

You need the following files on the deployment server:
```bash
extract-build-logs/
├── .env.example        # Configuration template
├── manage_container.py # Container management script
└── logs/               # Will be auto-created
```

```bash
# Clone repository OR copy specific files
git clone <repository-url> extract-build-logs
cd extract-build-logs

# OR copy just the essentials
mkdir -p extract-build-logs
cd extract-build-logs
scp server-a:extract-build-logs/{.env.example,manage_container.py} .
```

### Step 3: Create .env Configuration

**CRITICAL**: The `.env` file is NOT included in the Docker image (for security).

```bash
# Create .env from template
cp .env.example .env

# Edit with your credentials
nano .env  # or vim, vi, etc.
```

**Required Settings:**
```bash
# GitLab Configuration (REQUIRED)
GITLAB_URL=https://gitlab.example.com
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Webhook Configuration (OPTIONAL)
WEBHOOK_PORT=8000
WEBHOOK_SECRET=your_webhook_secret

# BFA Configuration (OPTIONAL - for API posting)
BFA_HOST=bfa-server.example.com
BFA_SECRET_KEY=your_bfa_secret_key
```

**Set proper permissions:**
```bash
chmod 644 .env
```

### Step 4: Ensure Logs Directory Exists (Auto-handled)

The `manage_container.py` script now **automatically creates** the logs directory with proper permissions.

However, if you prefer to create it manually:
```bash
mkdir -p logs
chmod 755 logs
```

### Step 5: Start the Container

```bash
# Make script executable
chmod +x manage_container.py

# Install Python dependencies (for management script)
pip install docker rich python-dotenv

# Start container
./manage_container.py start
```

### Step 6: Verify Deployment

```bash
# Check container status
./manage_container.py status

# Check logs
./manage_container.py logs

# Test webhook endpoint
curl http://localhost:8000/health
# Expected: {"status":"healthy","service":"gitlab-log-extractor","version":"1.0.0"}
```

## 🐛 Troubleshooting Common Issues

### Issue 1: "Permission denied" when mounting .env

**Error:**
```
docker: Error response from daemon: error while creating mount source path
'/home/user/extract-build-logs/.env': mkdir /home/user/extract-build-logs/.env:
permission denied.
```

**Cause:** `.env` file doesn't exist on the new server

**Solution:**
```bash
# Create .env file (see Step 3 above)
cp .env.example .env
nano .env

# Verify it exists
ls -la .env
```

### Issue 2: "Cannot write to log directory"

**Error:**
```
ERROR: Cannot write to log directory: ./logs
```

**Cause:** Logs directory has incorrect permissions or ownership

**Solution:**
```bash
# Option 1: Let manage_container.py auto-create it
./manage_container.py start

# Option 2: Create manually with proper permissions
mkdir -p logs
chmod 755 logs
chown $USER:$USER logs
```

### Issue 3: Docker User Namespace Issues

**Error:**
```
Permission denied errors despite correct ownership
```

**Cause:** Docker daemon running with `--userns-remap`

**Solution:** The container now runs with these settings to bypass namespace issues:
```python
user='root'           # Run as root inside container
userns_mode='host'    # Bypass user namespace remapping
```

This is already configured in `manage_container.py` (lines 734-735).

### Issue 4: GitLab URL or Token Not Found

**Error:**
```
grep: .env: Permission denied
ERROR: GITLAB_URL environment variable is required
```

**Cause:** `.env` file missing or not readable

**Solution:**
```bash
# Check .env file exists and is readable
ls -la .env

# Verify contents (without exposing token)
grep "GITLAB_URL" .env

# Ensure proper permissions
chmod 644 .env
```

## 🔧 Advanced: Manual Docker Run

If you prefer not to use `manage_container.py`:

```bash
# Ensure logs directory exists
mkdir -p logs

# Run container manually
docker run -d \
  --name bfa-gitlab-pipeline-extractor \
  --user root \
  --userns=host \
  -p 8000:8000 \
  -v $(pwd)/logs:/app/logs:rw \
  -v $(pwd)/.env:/app/.env:ro \
  --restart unless-stopped \
  bfa-gitlab-pipeline-extractor
```

## 📊 Deployment Checklist

Use this checklist when deploying to a new server:

- [ ] Docker installed and running
- [ ] Docker image transferred and loaded
- [ ] Repository files copied (manage_container.py, .env.example)
- [ ] `.env` file created with proper credentials
- [ ] `.env` file has correct permissions (644)
- [ ] Logs directory created (or will be auto-created)
- [ ] Port 8000 is available (or custom port configured)
- [ ] Python dependencies installed (`pip install docker rich python-dotenv`)
- [ ] Container started successfully
- [ ] Health check endpoint responds
- [ ] GitLab webhook configured and tested

## 🔐 Security Considerations

### Protecting Secrets

**Never commit these to version control:**
- `.env` file (contains GITLAB_TOKEN, BFA_SECRET_KEY)
- `logs/` directory (contains pipeline logs)

**Verify .gitignore includes:**
```
.env
logs/
*.log
```

### File Permissions

**Recommended permissions:**
```bash
.env            → 644 (rw-r--r--) - readable by owner and group
logs/           → 755 (rwxr-xr-x) - writable by owner, readable by others
manage_container.py → 755 (rwxr-xr-x) - executable
```

### Network Security

**Firewall rules:**
```bash
# Allow only specific IPs to access webhook (GitLab server)
sudo ufw allow from <gitlab-server-ip> to any port 8000

# Or use nginx reverse proxy with SSL
```

## 🚀 Production Deployment Best Practices

### 1. Use Docker Secrets (Docker Swarm/Compose)

```yaml
# docker-compose.yml
version: '3.8'
services:
  extractor:
    image: bfa-gitlab-pipeline-extractor
    secrets:
      - gitlab_token
    environment:
      GITLAB_URL: https://gitlab.example.com
      GITLAB_TOKEN_FILE: /run/secrets/gitlab_token

secrets:
  gitlab_token:
    file: ./secrets/gitlab_token.txt
```

### 2. Use Environment Variables (Kubernetes)

```yaml
# kubernetes-deployment.yaml
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-credentials
type: Opaque
stringData:
  GITLAB_TOKEN: glpat-xxxxxxxxxxxxxxxxxxxx
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: extractor
        envFrom:
        - secretRef:
            name: gitlab-credentials
```

### 3. Monitoring and Logging

```bash
# Monitor container health
watch -n 5 'curl -s http://localhost:8000/health'

# Monitor application logs
./manage_container.py logs

# Export monitoring data
./manage_container.py export monitoring-$(date +%Y%m%d).csv
```

## 📚 Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [GitLab Webhooks](https://docs.gitlab.com/ee/user/project/integrations/webhooks.html)
- [Main README](README.md) - Full application documentation
- [Operations Guide](OPERATIONS.md) - Monitoring and troubleshooting

## 🆘 Getting Help

If you encounter issues not covered here:

1. Check application logs: `./manage_container.py logs`
2. Check container status: `./manage_container.py status`
3. Review configuration: `./manage_container.py config`
4. Create an issue in the repository with:
   - Error message
   - Steps to reproduce
   - Environment details (OS, Docker version)
   - Configuration (sanitized - no secrets!)

---

**Last Updated:** 2025-11-10
**Version:** 1.0.0
