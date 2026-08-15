"""Mint one memory-only Google workload ID token for verifier tooling."""

from google.auth import default, impersonated_credentials
from google.auth.transport.requests import Request


PROJECT = "preflight-hackathon"
ORCHESTRATOR_SERVICE_ACCOUNT = (
    "full-shelf-orchestrator-sa@preflight-hackathon.iam.gserviceaccount.com"
)
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def mint_orchestrator_workload_token(audience: str) -> str:
    """Impersonate only the deployed orchestrator identity for one exact audience."""
    source, _ = default(scopes=[CLOUD_PLATFORM_SCOPE])
    target = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=ORCHESTRATOR_SERVICE_ACCOUNT,
        target_scopes=[CLOUD_PLATFORM_SCOPE],
        lifetime=600,
    )
    token_credentials = impersonated_credentials.IDTokenCredentials(
        target,
        target_audience=audience,
        include_email=True,
    )
    token_credentials.refresh(Request())
    if not token_credentials.token:
        raise RuntimeError("WORKLOAD_ID_TOKEN_MINT_FAILED")
    return token_credentials.token
