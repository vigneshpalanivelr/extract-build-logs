# Migration Guide: Bash to Python

Guide for migrating from `manage-container.sh` (bash) to `manage-container.py` (Python)

## Overview

**What Changed:**
- `manage-container.sh` → `manage-container.py`
- Bash script → Python with argparse
- `show_config.py` → Merged into `manage-container.py`

**Why the Migration:**
- ✅ **Better maintainability** - Python is easier to read and maintain
- ✅ **Comprehensive testing** - Full unit test coverage
- ✅ **Better error handling** - Clear error messages and exit codes
- ✅ **Rich output** - Beautiful terminal output with colors and tables
- ✅ **Native Docker API** - Using docker Python SDK instead of subprocess
- ✅ **Cross-platform** - Works on Windows/Mac/Linux without bash
- ✅ **Type safety** - Type hints for better IDE support

---

## Quick Migration

### Before (Bash)
```bash
./manage-container.sh build
./manage-container.sh start
./manage-container.sh status
./manage-container.sh logs
./manage-container.sh help
```

### After (Python)
```bash
./manage-container.py build
./manage-container.py start
./manage-container.py status
./manage-container.py logs
./manage-container.py --help
```

**Note:** `help` → `--help` (argparse standard)

---

## Command Comparison

| Operation | Bash Script | Python Script | Notes |
|-----------|-------------|---------------|-------|
| **Build image** | `./manage-container.sh build` | `./manage-container.py build` | ✅ Same |
| **Start container** | `./manage-container.sh start` | `./manage-container.py start` | ✅ Same |
| **Stop container** | `./manage-container.sh stop` | `./manage-container.py stop` | ✅ Same |
| **Restart** | `./manage-container.sh restart` | `./manage-container.py restart` | ✅ Same |
| **View logs** | `./manage-container.sh logs` | `./manage-container.py logs` | ✅ Same |
| **View logs (no follow)** | N/A | `./manage-container.py logs --no-follow` | ✨ New option |
| **Status** | `./manage-container.sh status` | `./manage-container.py status` | ✅ Same |
| **Shell** | `./manage-container.sh shell` | `./manage-container.py shell` | ✅ Same |
| **Remove** | `./manage-container.sh remove` | `./manage-container.py remove` | ✅ Same |
| **Remove (force)** | N/A (prompt required) | `./manage-container.py remove --force` | ✨ New option |
| **Cleanup** | `./manage-container.sh cleanup` | `./manage-container.py cleanup` | ✅ Same |
| **Cleanup (force)** | N/A (prompt required) | `./manage-container.py cleanup --force` | ✨ New option |
| **Monitor** | `./manage-container.sh monitor` | `./manage-container.py monitor` | ✅ Same |
| **Monitor (options)** | `./manage-container.sh monitor --hours 24` | `./manage-container.py monitor --hours 24` | ✅ Same |
| **Export** | `./manage-container.sh export` | `./manage-container.py export` | ✅ Same |
| **Export (filename)** | `./manage-container.sh export data.csv` | `./manage-container.py export data.csv` | ✅ Same |
| **Test webhook** | `./manage-container.sh test` | `./manage-container.py test` | ✅ Same |
| **View config** | `show_config.py` | `./manage-container.py config` | ✨ Merged |
| **Validate config** | N/A | `./manage-container.py config --validate-only` | ✨ New |
| **Help** | `./manage-container.sh help` | `./manage-container.py --help` | ⚠️ Changed |
| **Version** | N/A | `./manage-container.py --version` | ✨ New |
| **Auto-confirm** | N/A | `./manage-container.py start --yes` | ✨ New |

---

## New Features

### 1. Configuration Display and Validation

**Before:** Separate `show_config.py` script

**After:** Integrated into `manage-container.py`

```bash
# Display configuration
./manage-container.py config

# Validate only (no display)
./manage-container.py config --validate-only

# Quiet mode (minimal output)
./manage-container.py config --quiet
```

### 2. Force Flags

Skip confirmation prompts:

```bash
# Remove without confirmation
./manage-container.py remove --force

# Cleanup without confirmation
./manage-container.py cleanup --force
```

### 3. Auto-Confirm Start

Skip the configuration confirmation:

```bash
# Start without confirmation prompt
./manage-container.py start --yes

# Useful for automation/CI
./manage-container.py start -y
```

### 4. No-Follow Logs

View logs without following:

```bash
# Show logs without following
./manage-container.py logs --no-follow

# Still follows by default
./manage-container.py logs
```

### 5. Better Help

Comprehensive help with examples:

```bash
# Main help
./manage-container.py --help

# Command-specific help
./manage-container.py start --help
./manage-container.py config --help
```

---

## Breaking Changes

### 1. Help Command

**Before:**
```bash
./manage-container.sh help
```

**After:**
```bash
./manage-container.py --help
./manage-container.py -h
```

### 2. show_config.py Removed

**Before:**
```bash
python show_config.py
python show_config.py --yes
```

**After:**
```bash
./manage-container.py config
./manage-container.py config --quiet
```

### 3. Confirmation Behavior

**Before:** Some commands always prompted

**After:** Use `--force` or `--yes` to skip prompts

```bash
# Old: Always prompted
./manage-container.sh remove

# New: Can skip prompt
./manage-container.py remove --force
```

---

## Updated Scripts & Aliases

### Shell Aliases

Update your `.bashrc`, `.zshrc`, or `.bash_aliases`:

```bash
# Before
alias dstart='./manage-container.sh start'
alias dstop='./manage-container.sh stop'
alias dstatus='./manage-container.sh status'
alias dlogs='./manage-container.sh logs'

# After
alias dstart='./manage-container.py start'
alias dstop='./manage-container.py stop'
alias dstatus='./manage-container.py status'
alias dlogs='./manage-container.py logs'

# New aliases
alias dconfig='./manage-container.py config'
alias dquick='./manage-container.py start --yes'  # Quick start without prompts
```

### CI/CD Scripts

Update your CI/CD pipelines:

**GitHub Actions:**
```yaml
# Before
- name: Start container
  run: ./manage-container.sh start

# After
- name: Start container
  run: ./manage-container.py start --yes
```

**GitLab CI:**
```yaml
# Before
script:
  - ./manage-container.sh build
  - ./manage-container.sh start

# After
script:
  - ./manage-container.py build
  - ./manage-container.py start --yes
```

### Cron Jobs

Update cron jobs:

```bash
# Before
0 2 * * * /path/to/extract-build-logs/manage-container.sh restart

# After
0 2 * * * /path/to/extract-build-logs/manage-container.py restart
```

### systemd Services

Update systemd service files:

```ini
# Before
ExecStart=/path/to/extract-build-logs/manage-container.sh start

# After
ExecStart=/path/to/extract-build-logs/manage-container.py start --yes
```

---

## Dependencies

The Python script requires additional packages:

```bash
# Install new dependencies
pip install -r requirements.txt

# New packages added:
# - docker>=7.0.0 (Docker Python SDK)
# - rich>=13.0.0 (Terminal output)
```

**Note:** These are only required to run the management script, not the main application.

---

## Troubleshooting

### Issue 1: "Python not found"

```bash
# Check Python version
python3 --version

# Use python3 explicitly if needed
python3 manage-container.py --help

# Or make it executable and use shebang
chmod +x manage-container.py
./manage-container.py --help
```

### Issue 2: "Module not found"

```bash
# Install dependencies
pip install -r requirements.txt

# Or use pip3
pip3 install -r requirements.txt

# Verify installation
pip list | grep -E "docker|rich"
```

### Issue 3: "Permission denied"

```bash
# Make script executable
chmod +x manage-container.py

# Verify permissions
ls -la manage-container.py
# Should show: -rwxr-xr-x
```

### Issue 4: "Old script still running"

```bash
# No conflict - both can coexist temporarily
# But use Python script going forward

# Remove old script when ready
rm manage-container.sh
```

---

## Rollback Plan

If you need to rollback:

```bash
# Old bash script is still available in git history
git log --all --full-history -- manage-container.sh

# Checkout old version
git checkout <commit-hash> -- manage-container.sh

# Or restore from backup
cp manage-container.sh.backup manage-container.sh
```

**Note:** The Python version is recommended. Rollback only if critical issues arise.

---

## Testing the Migration

### 1. Test Basic Commands

```bash
# Test help
./manage-container.py --help

# Test config display
./manage-container.py config

# Test status (safe, read-only)
./manage-container.py status
```

### 2. Test with Dry Run

```bash
# Config validation (no changes)
./manage-container.py config --validate-only

# Status check (read-only)
./manage-container.py status
```

### 3. Test Full Workflow

```bash
# 1. Build
./manage-container.py build

# 2. Start
./manage-container.py start --yes

# 3. Verify
./manage-container.py status

# 4. Test webhook
./manage-container.py test

# 5. View logs
./manage-container.py logs --no-follow | tail -20

# 6. Monitor
./manage-container.py monitor

# 7. Stop
./manage-container.py stop
```

---

## Side-by-Side Comparison

Both scripts can coexist temporarily:

```bash
# Old bash script
./manage-container.sh status

# New Python script
./manage-container.py status

# Compare outputs
```

**Recommendation:** Switch to Python script after testing.

---

## Deprecation Timeline

1. **Current:** Both scripts available
2. **Week 1:** Test Python script thoroughly
3. **Week 2:** Switch to Python script for production
4. **Week 3:** Remove bash script and show_config.py

```bash
# When ready to remove old files
rm manage-container.sh
rm show_config.py
rm tests/test_show_config.py
```

---

## Benefits Summary

| Feature | Bash | Python |
|---------|------|--------|
| Maintainability | ⚠️ Moderate | ✅ Excellent |
| Testing | ❌ Limited | ✅ Comprehensive |
| Error Handling | ⚠️ Basic | ✅ Detailed |
| Output | ⚠️ Plain | ✅ Rich/Colored |
| Cross-platform | ⚠️ Bash required | ✅ Python only |
| IDE Support | ⚠️ Limited | ✅ Excellent |
| Type Safety | ❌ None | ✅ Type hints |
| Documentation | ⚠️ Comments | ✅ Docstrings |
| Debugging | ⚠️ Difficult | ✅ Easy |

---

## Getting Help

**Questions?** Check:
- [TESTING.md](TESTING.md) - Testing guide
- [OPERATIONS.md](OPERATIONS.md) - Operations guide
- [README.md](README.md) - Setup instructions

**Issues?** Report at: `https://github.com/your-org/extract-build-logs/issues`

---

## Feedback

We'd love your feedback on the migration:
- What works well?
- What could be improved?
- Any missing features?

Please share your experience!
