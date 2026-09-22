# ─────────────────────────────────────────────────────────────────────────────
# File: infra/terraform/gcp/workload_identity.tf
# Purpose: Workload Identity Federation for GitHub Actions — keyless GCP auth.
#          Allows GitHub Actions to impersonate the CI service account without
#          storing long-lived JSON keys in GitHub Secrets.
# Language: HCL (Terraform)
# Connects to: github.com (OIDC token issuer), environment-scoped deploy identities
# Inputs:  GitHub owner and repository names plus their immutable IDs
# Outputs: wif_provider_name (via outputs.tf)
# ─────────────────────────────────────────────────────────────────────────────

variable "github_owner" {
  description = "GitHub repository owner name."
  type        = string
  default     = "yyqfrank420"
}

variable "github_repo_name" {
  description = "GitHub repository name."
  type        = string
  default     = "ai-engineering-learning-agent"
}

variable "github_owner_id" {
  description = "Immutable GitHub repository-owner ID used in OIDC subject claims."
  type        = string
  default     = "208153095"
}

variable "github_repo_id" {
  description = "Immutable GitHub repository ID used in OIDC subject claims."
  type        = string
  default     = "1200397882"
}

locals {
  github_repo                = "${var.github_owner}/${var.github_repo_name}"
  github_oidc_subject_prefix = "repo:${var.github_owner}@${var.github_owner_id}/${var.github_repo_name}@${var.github_repo_id}"
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "WIF pool for GitHub Actions CI/CD"

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  oidc {
    # GitHub's OIDC issuer — tokens are issued at workflow runtime, not stored anywhere.
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  # Map GitHub OIDC claims to Google IAM attributes.
  # `attribute.repository` is used below to scope access to one specific repo.
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  # Hard-scope: only OIDC tokens from this exact repo can use this provider.
  # Prevents other repos (including forks) from impersonating the CI SA.
  attribute_condition = "assertion.repository == '${local.github_repo}'"
}

# GitHub includes immutable owner and repository IDs after a repository rename,
# followed by the protected Environment. Binding exact subjects prevents a
# staging-eval job from ever impersonating production.
resource "google_service_account_iam_member" "staging_ci_wif_binding" {
  service_account_id = google_service_account.github_actions_staging.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject/${local.github_oidc_subject_prefix}:environment:staging-eval"
}

resource "google_service_account_iam_member" "production_ci_wif_binding" {
  service_account_id = google_service_account.github_actions_production.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject/${local.github_oidc_subject_prefix}:environment:production"
}

resource "google_service_account_iam_member" "legacy_ci_wif_binding" {
  count              = var.retain_legacy_ci_access ? 1 : 0
  service_account_id = google_service_account.ci.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${local.github_repo}"
}
