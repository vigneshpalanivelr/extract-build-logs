[{
    "ci_system": "Jenkins",
    "environment_type": "air-gapped",

    "description": "A comprehensive air-gapped CI environment hosting multiple product builds (docker/python/golang/cpp etc) in a unified ecosystem. Source code resides in GitLab (git.internal.com). Two Jenkins masters distribute workload: jenkinsnew.internal.com handles direct-attached-storage builds (NFS-free, optimized for speed), and jenkins.internal.com handles NFS-dependent builds. Scripted Groovy pipelines with Python automation manage CI workflows. Final artifacts published to internal Artifactory and FTP.",

    "infrastructure": {
        "masters": [
            {
                "name": "jenkinsnew.internal.com",
                "purpose": "Direct-attached-storage builds (no NFS dependency)"
            },
            {
                "name": "jenkins.internal.com",
                "purpose": "NFS-dependent builds"
            }
        ],
        "runners": {
            "os_variants": ["centos-7", "debian-9", "debian-11"],
            "executors_per_runner": 8,
            "resource_constraints": "none",
            "monitoring": "IT monitoring in place"
        },
        "storage": {
            "nfs": {
                "mount_point": "/net",
                "capacity_range": "12T-30T",
                "cleanup_frequency": "daily",
                "cleanup_type": "periodic automated"
            }
        }
    },

    "pipeline_configuration": {
        "pipeline_type": "scripted",
        "language": "Groovy",
        "automation_scripts": "Python",
        "source_control": "git",
        "log_storage": "Jenkins master",
        "log_format_for_llm": "pre-formatted chunks",
        "typical_build_duration": "5-45 minutes",
        "job_characteristics": "Variable stages and dependencies per job - LLM receives only failure log chunks and does not need job-level details"
    },

    "key_tools": {
        "build_tools": ["make", "mvn", "docker", "golang", "cpp"],
        "scripting": ["python", "node"],
        "code_quality_analysis": ["pylint", "flake8", "yamllint", "shellcheck", "cppcheck"],
        "build_utilities": ["gpg", "nfs"]
    },

    "external_dependencies": {
        "source_control": {
            "system": "gitlab",
            "url": "git.internal.com"
        },
        "artifact_repositories": [
            "jfrog artifactory (primary for all package managers)",
            "internal ftp"
        ],
        "security_scanning": "fossa",
        "issue_tracking": "jira",
        "package_managers": "All configured via Artifactory only (air-gapped)",
        "new_package_workflow": "Manual review and approval process required"
    },

    "credentials_and_access": {
        "credential_store": "Jenkins native credentials store",
        "permission_issues": "none known",
        "gpg_management": "GPG keys managed via Jenkins credentials store"
    },

    "constraints": [
        "No internet access (air-gapped network)",
        "All tools installed directly on runners (not containerized)",
        "Package availability limited to manually-approved Artifactory packages",
        "NFS mount point is /net with capacity-dependent constraints"
    ],

    "failure_investigation_approach": {
        "recovery_strategy": "Revert problematic commits in git (groovy/python CI scripts)",
        "failure_log_input": "Pre-formatted failure log chunks provided to LLM",
        "common_failure_patterns": "Documented separately in LLM memory",
        "root_cause_candidates": "Refer to common_issues list below"
    },

    "common_issues": [
        "NFS mount issues (connectivity, timeouts, capacity)",
        "Missing or outdated packages in Artifactory",
        "Tool version incompatibilities",
        "Build timeout (typically >45 minutes indicates issue)",
        "Artifact publish failures to FTP/Artifactory"
    ]
},
{
  "ci_system": "GitLab CI",
  "environment_type": "air-gapped",
  "description": "An air-gapped GitLab CI environment for multiple product builds in shared gitlab runner environment. Source code and pipelines run on GitLab Enterprise Edition (git.internal.com). Runners are deployed as VM/bare-metal system services and execute jobs via the Docker executor, pulling images only from an internal registry. Builds run on local disk (no NFS, no shared mounts). Build artifacts are retained as GitLab job artifacts and also published to internal Artifactory and internal FTP. Secrets are managed via GitLab CI variables; GPG keys (for signing where required) are maintained on the server side.",
  "infrastructure": {
    "gitlab_instance": {
      "name": "prod",
      "url": "https://git.internal.com/",
      "edition": "GitLab Enterprise Edition",
      "version_band": "latest (per admin-managed upgrades)"
    },
    "runners": {
      "runner_scope": ["shared"],
      "deployment_model": "VM/bare-metal system service (non-autoscaled)",
      "os_variants": ["debian-11", "debian-12"],
      "executors": ["docker", "shell"],
      "concurrency": {
        "per_host": "One job per host"
      },
      "resource_constraints": "No constraints for resources (max: 16GB)"
    },
    "storage": {
      "workspace": {
        "type": "local disk only",
        "notes": "No NFS dependency and no shared mount points like /net"
      },
      "cache_backend": {
        "used": false
      }
    }
  },
  "pipeline_configuration": {
    "pipeline_definition": ".gitlab-ci.yml (no central dynamic includes/templates)",
    "languages": ["yaml", "bash (implicit)", "docker (executor-based)"],
    "source_control": "git",
    "log_storage": "GitLab job logs",
    "log_format_for_llm": "pre-formatted failure log chunks",
    "typical_pipeline_duration": "few minutes",
    "job_characteristics": "Job stages and dependencies vary per project; builds run inside Docker executor environments using internal base images",
    "llm_context_scope": "LLM receives failure log chunks; job-level details optional unless needed for triage"
  },
  "key_tools": {
    "build_tools": ["make", "docker", "maven", "gradle", "npm", "yarn", "pip", "golang"],
    "scripting": ["python", "sh", "bash"],
    "code_quality_analysis": ["pylint", "flake8", "yamllint", "shellcheck", "isort", "eslint"],
    "build_utilities": ["gpg", "tar", "gzip", "zip"]
  },
  "external_dependencies": {
    "source_control": {
      "system": "gitlab",
      "url": "https://git.internal.com/"
    },
    "artifact_repositories": [
      "GitLab job artifacts (expiry enabled)",
      "jfrog artifactory (internal, primary package repository)",
      "internal ftp",
      "internal docker registry (for runner images)"
    ],
    "security_scanning": "fossa (if enabled per project)",
    "issue_tracking": "jira",
    "package_managers": "All configured via internal repositories only (air-gapped); internal apt/yum mirrors available",
    "new_package_workflow": "Manual review and approval process required"
  },
  "credentials_and_access": {
    "secret_management": "GitLab CI variables (masked/protected as applicable)",
    "permission_issues": "none known",
    "gpg_management": "GPG keys stored on the server side; signing performed where required"
  },
  "constraints": [
    "No internet egress from runners (air-gapped)",
    "Docker executor uses images pulled only from internal registry",
    "Build workspaces use local disk only (no NFS, no shared mounts)",
    "Package availability limited to manually-approved internal repositories (Artifactory + internal mirrors)",
    "No GitLab cache in use"
  ],
  "failure_investigation_approach": {
    "recovery_strategy": "Revert problematic commits in repository CI definitions (.gitlab-ci.yml) or build scripts; pin/rollback internal base images if needed",
    "failure_log_input": "Failure log chunks (recommended: pre-formatted excerpts from GitLab job logs)",
    "common_failure_patterns": "Documented separately in LLM memory",
    "root_cause_candidates": "Refer to common_issues list below"
  },
  "common_issues": [
    "Shared runner availability issues (runner offline/busy, scheduling delays)",
    "Internal registry image pull/auth failures (docker executor)",
    "Docker daemon/startup issues on runner hosts",
    "Missing or outdated packages in Artifactory / internal apt/yum mirrors",
    "Tool/version incompatibilities inside base images",
    "Artifact publish failures to Artifactory/FTP",
    "Job timeout (unusual if pipelines are typically a few minutes)",
    "Permissions/UID-GID mismatch inside containers affecting workspace writes"
  ]
}]
