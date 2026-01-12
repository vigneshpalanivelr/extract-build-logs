# Plan: Extract Jenkins Pipeline Trigger User Information

## Current State Analysis

### GitLab Implementation (Working Reference)
**Location:** `src/pipeline_extractor.py` + `src/api_poster.py`

**How GitLab Gets User Info:**
1. User information comes directly in webhook payload: `webhook_payload.get("user", {})`
2. Extracted in `format_payload()` at lines 119-130:
   ```python
   user_info = pipeline_info.get('user', {})
   triggered_by = user_info.get('username') or user_info.get('name')
   if triggered_by:
       triggered_by = f"{triggered_by}@sandvine.com"
   if not triggered_by:
       triggered_by = pipeline_info.get('source', 'unknown')
   ```

### Jenkins Implementation (Current)
**Location:** `src/webhook_listener.py` + `src/api_poster.py`

**What We Have:**
1. **Parameter extraction** (webhook_listener.py:932-940):
   - Already extracts ALL pipeline parameters from Jenkins build metadata
   - Stores in `build_info['parameters']`

2. **Payload transformation** (api_poster.py:222-281):
   - Currently hardcodes `"triggered_by": "jenkins"`
   - Has access to all parameters via `jenkins_payload.get('parameters', {})`

**Pipeline Variables Available:**

**Pre-Merge Pipeline:**
- `gitlabSourceNamespace` - GitLab namespace/group
- `gitlabSourceRepoName` - Repository name
- `gitlabSourceRepoSshUrl` - SSH URL
- `gitlabSourceBranch` - Source branch
- `gitlabMergeRequestLastCommit` - Commit SHA
- `gitlabMergeRequestId` - Internal MR ID
- `gitlabMergeRequestIid` - Project-specific MR IID (use this!)

**Build Pipeline:**
- `gitlabSourceBranch` - Branch name
- `sourceNamespace` - Namespace/group
- `gitlabSourceRepoName` - Repository name

---

## Proposed Solution

### Architecture Overview
```
Jenkins Build Parameters
    ↓
webhook_listener.py (already extracts parameters)
    ↓
api_poster.py → format_jenkins_payload()
    ↓
NEW: Determine pipeline type (pre-merge vs build)
    ↓
NEW: Call GitLab API to get user info
    ↓
Format triggered_by field (username@sandvine.com)
```

### Implementation Strategy

#### Step 1: Add GitLab API Client to api_poster.py

**Why:** Need to make GitLab API calls to fetch user information

**Implementation:**
```python
class ApiPoster:
    def __init__(self, config: Config):
        self.config = config
        # Existing code...

        # Add GitLab API session for user lookups
        self.gitlab_session = None
        if config.gitlab_url and config.gitlab_token:
            self.gitlab_session = requests.Session()
            self.gitlab_session.headers.update({
                'PRIVATE-TOKEN': config.gitlab_token,
                'Content-Type': 'application/json'
            })
            self.gitlab_base_url = f"{config.gitlab_url}/api/v4"
```

#### Step 2: Add Helper Method to Get Project ID

**Why:** GitLab API requires project ID, but we have namespace + repo name

**Implementation:**
```python
def _get_gitlab_project_id(self, namespace: str, repo_name: str) -> Optional[int]:
    """
    Get GitLab project ID from namespace and repo name.

    Args:
        namespace: GitLab namespace/group (e.g., "sandvine-platform")
        repo_name: Repository name (e.g., "ci_build")

    Returns:
        Project ID or None if not found

    API: GET /api/v4/projects/:namespace%2F:repo_name
    """
    if not self.gitlab_session:
        return None

    try:
        project_path = f"{namespace}/{repo_name}"
        encoded_path = requests.utils.quote(project_path, safe='')
        url = f"{self.gitlab_base_url}/projects/{encoded_path}"

        logger.debug("Fetching GitLab project ID for: %s", project_path)
        response = self.gitlab_session.get(url, timeout=10)
        response.raise_for_status()

        project_data = response.json()
        project_id = project_data.get('id')
        logger.debug("Found project ID %d for %s", project_id, project_path)
        return project_id

    except Exception as e:
        logger.warning("Failed to fetch GitLab project ID for %s/%s: %s",
                      namespace, repo_name, e)
        return None
```

#### Step 3: Add Method to Get User from Merge Request

**Why:** Pre-merge pipelines need MR author information

**Implementation:**
```python
def _get_user_from_merge_request(self, project_id: int, mr_iid: int) -> Optional[str]:
    """
    Get username from GitLab merge request.

    Args:
        project_id: GitLab project ID
        mr_iid: Merge request IID (project-specific)

    Returns:
        Username or None if not found

    API: GET /api/v4/projects/:id/merge_requests/:merge_request_iid
    """
    if not self.gitlab_session:
        return None

    try:
        url = f"{self.gitlab_base_url}/projects/{project_id}/merge_requests/{mr_iid}"

        logger.debug("Fetching MR !%d from project %d", mr_iid, project_id)
        response = self.gitlab_session.get(url, timeout=10)
        response.raise_for_status()

        mr_data = response.json()
        author = mr_data.get('author', {})
        username = author.get('username')

        if username:
            logger.info("Found MR author: %s for MR !%d", username, mr_iid)
            return username

        return None

    except Exception as e:
        logger.warning("Failed to fetch MR !%d from project %d: %s",
                      mr_iid, project_id, e)
        return None
```

#### Step 4: Add Method to Get User from Commit

**Why:** Build pipelines need commit author information

**Implementation:**
```python
def _get_user_from_commit(self, project_id: int, commit_sha: str) -> Optional[str]:
    """
    Get username from GitLab commit.

    Args:
        project_id: GitLab project ID
        commit_sha: Commit SHA

    Returns:
        Username or None if not found

    API: GET /api/v4/projects/:id/repository/commits/:sha
    """
    if not self.gitlab_session:
        return None

    try:
        url = f"{self.gitlab_base_url}/projects/{project_id}/repository/commits/{commit_sha}"

        logger.debug("Fetching commit %s from project %d", commit_sha[:8], project_id)
        response = self.gitlab_session.get(url, timeout=10)
        response.raise_for_status()

        commit_data = response.json()

        # GitLab returns author_name and author_email, but not username directly
        # We can try to extract username from email if it matches pattern
        author_email = commit_data.get('author_email', '')

        # Try to extract username from email (e.g., "john.doe@sandvine.com" -> "john.doe")
        if '@' in author_email:
            username = author_email.split('@')[0]
            logger.info("Extracted username '%s' from commit %s", username, commit_sha[:8])
            return username

        # Fallback: use author_name
        author_name = commit_data.get('author_name')
        if author_name:
            logger.info("Using author name '%s' for commit %s", author_name, commit_sha[:8])
            return author_name

        return None

    except Exception as e:
        logger.warning("Failed to fetch commit %s from project %d: %s",
                      commit_sha[:8], project_id, e)
        return None
```

#### Step 5: Add Method to Get User from Branch

**Why:** Build pipelines without commit SHA need branch's latest commit

**Implementation:**
```python
def _get_user_from_branch(self, project_id: int, branch_name: str) -> Optional[str]:
    """
    Get username from latest commit on GitLab branch.

    Args:
        project_id: GitLab project ID
        branch_name: Branch name

    Returns:
        Username or None if not found

    API: GET /api/v4/projects/:id/repository/branches/:branch
    """
    if not self.gitlab_session:
        return None

    try:
        url = f"{self.gitlab_base_url}/projects/{project_id}/repository/branches/{branch_name}"

        logger.debug("Fetching branch '%s' from project %d", branch_name, project_id)
        response = self.gitlab_session.get(url, timeout=10)
        response.raise_for_status()

        branch_data = response.json()
        commit_data = branch_data.get('commit', {})
        commit_sha = commit_data.get('id')

        if commit_sha:
            # Get user from the latest commit
            return self._get_user_from_commit(project_id, commit_sha)

        return None

    except Exception as e:
        logger.warning("Failed to fetch branch '%s' from project %d: %s",
                      branch_name, project_id, e)
        return None
```

#### Step 6: Update format_jenkins_payload() to Extract User

**Why:** Main integration point - determine user based on available parameters

**Implementation:**
```python
def format_jenkins_payload(self, jenkins_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Transform Jenkins payload to match GitLab API format."""

    # ... existing code for job_name, build_number, parameters ...

    # Extract repo, branch, commit from pipeline parameters
    repo = parameters.get('gitlabSourceRepoName', job_name)
    branch = parameters.get('gitlabSourceBranch', 'unknown')
    commit = parameters.get('gitlabMergeRequestLastCommit', 'unknown')

    # NEW: Determine triggered_by from GitLab API
    triggered_by = self._determine_jenkins_triggered_by(parameters)

    # ... rest of existing code ...

    payload = {
        "source": "jenkins",
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "job_name": job_name,
        "pipeline_id": str(build_number),
        "triggered_by": triggered_by,  # Now contains actual username
        "failed_steps": failed_steps
    }

    return payload


def _determine_jenkins_triggered_by(self, parameters: Dict[str, Any]) -> str:
    """
    Determine who triggered the Jenkins pipeline by querying GitLab API.

    Strategy:
    1. Check if it's a pre-merge pipeline (has gitlabMergeRequestIid)
       → Get user from merge request
    2. Check if it's a build pipeline with commit SHA
       → Get user from commit
    3. Check if it's a build pipeline with branch only
       → Get user from branch's latest commit
    4. Fallback to "jenkins" if GitLab API unavailable

    Args:
        parameters: Jenkins pipeline parameters

    Returns:
        Username formatted as "username@sandvine.com" or "jenkins"
    """
    namespace = parameters.get('gitlabSourceNamespace') or parameters.get('sourceNamespace')
    repo_name = parameters.get('gitlabSourceRepoName')

    if not namespace or not repo_name:
        logger.warning("Missing namespace or repo name in Jenkins parameters, cannot determine user")
        return "jenkins"

    # Get GitLab project ID
    project_id = self._get_gitlab_project_id(namespace, repo_name)
    if not project_id:
        logger.warning("Could not find GitLab project ID, falling back to 'jenkins'")
        return "jenkins"

    username = None

    # Strategy 1: Pre-merge pipeline (has MR IID)
    mr_iid = parameters.get('gitlabMergeRequestIid')
    if mr_iid:
        try:
            mr_iid_int = int(mr_iid)
            username = self._get_user_from_merge_request(project_id, mr_iid_int)
            if username:
                logger.info("Determined Jenkins pipeline triggered by MR author: %s", username)
        except (ValueError, TypeError) as e:
            logger.warning("Invalid MR IID '%s': %s", mr_iid, e)

    # Strategy 2: Build pipeline with commit SHA
    if not username:
        commit_sha = parameters.get('gitlabMergeRequestLastCommit')
        if commit_sha and commit_sha != 'unknown':
            username = self._get_user_from_commit(project_id, commit_sha)
            if username:
                logger.info("Determined Jenkins pipeline triggered by commit author: %s", username)

    # Strategy 3: Build pipeline with branch only
    if not username:
        branch = parameters.get('gitlabSourceBranch')
        if branch and branch != 'unknown':
            username = self._get_user_from_branch(project_id, branch)
            if username:
                logger.info("Determined Jenkins pipeline triggered by branch's last committer: %s", username)

    # Format username
    if username:
        return f"{username}@sandvine.com"

    # Fallback
    logger.warning("Could not determine Jenkins pipeline trigger user, using 'jenkins'")
    return "jenkins"
```

---

## Testing Strategy

### Test Cases

#### Test 1: Pre-Merge Pipeline
**Parameters:**
```python
{
    'gitlabSourceNamespace': 'sandvine-platform',
    'gitlabSourceRepoName': 'ci_build',
    'gitlabMergeRequestIid': '123',
    'gitlabSourceBranch': 'feature/test',
    'gitlabMergeRequestLastCommit': 'abc123def456'
}
```
**Expected:** `triggered_by = "john.doe@sandvine.com"` (MR author)

#### Test 2: Build Pipeline with Commit
**Parameters:**
```python
{
    'sourceNamespace': 'sandvine-platform',
    'gitlabSourceRepoName': 'ci_build',
    'gitlabSourceBranch': 'main',
    'gitlabMergeRequestLastCommit': 'abc123def456'
}
```
**Expected:** `triggered_by = "jane.smith@sandvine.com"` (commit author)

#### Test 3: Build Pipeline Branch Only
**Parameters:**
```python
{
    'sourceNamespace': 'sandvine-platform',
    'gitlabSourceRepoName': 'ci_build',
    'gitlabSourceBranch': 'develop'
}
```
**Expected:** `triggered_by = "bob.jones@sandvine.com"` (latest commit on branch)

#### Test 4: Missing GitLab Credentials
**Parameters:** (any)
**Expected:** `triggered_by = "jenkins"` (fallback)

#### Test 5: GitLab API Failure
**Parameters:** (any with 404/500 from GitLab)
**Expected:** `triggered_by = "jenkins"` (fallback)

---

## Error Handling & Edge Cases

### 1. GitLab API Unavailable
- **Scenario:** GitLab server down or unreachable
- **Handling:** Catch exceptions, log warning, fallback to "jenkins"
- **Impact:** Builds continue, just without user attribution

### 2. Invalid Parameters
- **Scenario:** Missing namespace, repo, or malformed IIDs
- **Handling:** Validate parameters, log warning, fallback to "jenkins"
- **Impact:** Graceful degradation

### 3. User Not Found
- **Scenario:** Commit by deleted user, external contributor
- **Handling:** Return None from helper methods, fallback to "jenkins"
- **Impact:** Attribution shows "jenkins" instead of actual user

### 4. Multiple Committers
- **Scenario:** Branch has multiple commits since trigger
- **Handling:** Use latest commit author (most recent)
- **Impact:** May not be the actual trigger, but best effort

### 5. Performance Impact
- **Scenario:** GitLab API adds latency
- **Mitigation:**
  - Use 10-second timeout
  - Consider caching project IDs (namespace+repo → project_id)
  - Async/background task if latency becomes issue

---

## Configuration

### No New Config Required
All necessary configuration already exists:
- `GITLAB_URL` - for API calls
- `GITLAB_TOKEN` - for authentication
- `JENKINS_ENABLED` - feature gate

### Optional Enhancement
```bash
# Future: Enable/disable user lookup
JENKINS_LOOKUP_GITLAB_USERS=true  # default: true
```

---

## Implementation Checklist

- [ ] Add `gitlab_session` to `ApiPoster.__init__()`
- [ ] Implement `_get_gitlab_project_id()`
- [ ] Implement `_get_user_from_merge_request()`
- [ ] Implement `_get_user_from_commit()`
- [ ] Implement `_get_user_from_branch()`
- [ ] Implement `_determine_jenkins_triggered_by()`
- [ ] Update `format_jenkins_payload()` to call `_determine_jenkins_triggered_by()`
- [ ] Add unit tests for each helper method
- [ ] Add integration test with mocked GitLab API
- [ ] Test with real Jenkins builds (pre-merge and build pipelines)
- [ ] Update documentation with new behavior

---

## Benefits

1. **Consistent with GitLab**: Same `triggered_by` format for both sources
2. **Accountability**: Know who triggered Jenkins builds via GitLab integration
3. **No Manual Config**: Uses existing GitLab credentials
4. **Graceful Fallback**: Falls back to "jenkins" if lookup fails
5. **Well-Tested Pattern**: Mirrors existing GitLab implementation

---

## Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| GitLab API adds latency | 10s timeout, consider caching project IDs |
| GitLab API rate limits | Implement retry with backoff, cache results |
| Breaking existing Jenkins flow | Extensive error handling, fallback to "jenkins" |
| Wrong user attribution | Document edge cases, log debug info |

---

## Alternative Approaches Considered

### Alternative 1: Parse Jenkins Build Cause
**Pros:** No GitLab API calls
**Cons:** Jenkins doesn't store GitLab username in build cause

### Alternative 2: Store User in Jenkins Parameter
**Pros:** Simple, fast
**Cons:** Requires Jenkinsfile changes, not backwards compatible

### Alternative 3: Background Job for User Lookup
**Pros:** No latency impact
**Cons:** More complex, eventual consistency

**Chosen:** Direct GitLab API lookup (best balance)

---

## Timeline Estimate

- Step 1-2 (GitLab client + project ID): 1-2 hours
- Step 3-5 (User lookup methods): 2-3 hours
- Step 6 (Integration): 1-2 hours
- Testing: 2-3 hours
- **Total: 6-10 hours**
