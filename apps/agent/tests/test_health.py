import pytest


@pytest.mark.asyncio
async def test_root_health(client):
    """Verify root health check endpoint (covers: AC-1)."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "agent-engine"


@pytest.mark.asyncio
async def test_api_v1_health(client):
    """Verify API v1 health check endpoint with version info (covers: AC-1)."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "agent-engine"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_cors_headers(client):
    """Verify CORS preflight handling for web console origin (covers: AC-1)."""
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )
