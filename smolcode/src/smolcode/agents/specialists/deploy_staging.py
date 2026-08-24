from __future__ import annotations

from ._models import Specialist


# Bundled specialist: deploy-staging (decision 0008 D6).
#
# Tier: full_access (it talks to ssh/rsync/docker/kubectl/terraform).
# Tools: run + git_push. NO fs tools, NO read_file/write_file. The
#   specialist's job is to deploy, not to edit code in the workspace.
# Extra paths: declared in description; v1 does NOT enforce them in the
#   host's PathPolicy (the v1 PathPolicy is workspace-only). Users who
#   want extra paths enforced should add them to Tier.paths in their
#   local config; see docs/decisions/0008-m5-orchestrator.md.

DEPLOY_STAGING_NAME = "deploy_staging"

DEPLOY_STAGING_DESCRIPTION = (
    "Deploy the current git branch to a staging environment via "
    + "rsync/ssh/docker/kubectl/terraform. Has only the 'run' "
    + "and 'git_push' tools -- no filesystem editing. "
    + "Pass the target (e.g. 'staging-web', 'k8s/staging') "
    + "and any pre-deploy checks to run."
)


def build_deploy_staging_specialist():
    """Return the bundled deploy_staging Specialist instance."""
    return Specialist(
        name=DEPLOY_STAGING_NAME,
        tier="full_access",
        description=DEPLOY_STAGING_DESCRIPTION,
        tools=("run", "git_push"),
        extra_paths=("~/.docker/", "./infra/"),
    )


__all__ = [
    "DEPLOY_STAGING_NAME",
    "DEPLOY_STAGING_DESCRIPTION",
    "build_deploy_staging_specialist",
]
