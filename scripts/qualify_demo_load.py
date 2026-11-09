"""Exercise the disposable constrained Compose API without printing credentials."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx

BASE = "http://127.0.0.1:18865"
PASSWORD = "DemoPassword123!Long"
TOKEN = "qualify-only-operations-token-000000000000"


def request(method: str, path: str, **kwargs: object) -> tuple[httpx.Response, int]:
    started = time.perf_counter()
    response = httpx.request(method, BASE + path, timeout=90, **kwargs)
    return response, round((time.perf_counter() - started) * 1000)


def login() -> tuple[httpx.Response, int]:
    return request(
        "POST", "/auth/login",
        json={"email": "owner@example.com", "password": PASSWORD},
    )


def register() -> tuple[httpx.Response, int]:
    return request(
        "POST", "/auth/register",
        json={
            "email": f"qualify-{uuid4().hex[:12]}@example.com",
            "password": "RegisterPass123!Long",
            "invite_code": "test-invite-code-123",
        },
    )


def main() -> None:
    initial = {
        path: request("GET", path)[0].status_code
        for path in ("/health", "/readyz", "/scheduler-health")
    }
    baseline_response, _ = request(
        "GET", "/operations/recovery",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    baseline_accepted = baseline_response.json()["job_counts"]["ACCEPTED"]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(login) for _ in range(4)]
        futures.append(pool.submit(register))
        time.sleep(0.5)
        during_load, health_ms = request("GET", "/health")
        results = [future.result() for future in futures]

    logins = results[:4]
    registration = results[4]
    with httpx.Client(base_url=BASE, timeout=30) as owner:
        owner.cookies.update(logins[0][0].cookies)
        email = f"recipient-{uuid4().hex[:12]}@example.com"
        added = owner.post("/beneficiaries", json={"name": "Fixture", "email": email})
        invited = (
            owner.post(f"/beneficiaries/{added.json()['id']}/invite")
            if added.status_code == 201 else None
        )

    counts = {}
    scheduler = 0
    for _ in range(120):
        response, _ = request(
            "GET", "/operations/recovery",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        if response.status_code in (200, 503):
            counts = response.json()["job_counts"]
            if counts.get("ACCEPTED", 0) >= baseline_accepted + 2:
                break
        time.sleep(0.25)
    scheduler = request("GET", "/scheduler-health")[0].status_code
    result = {
        "initial_health": initial,
        "concurrent_login_statuses": [item[0].status_code for item in logins],
        "concurrent_login_ms": [item[1] for item in logins],
        "registration_status": registration[0].status_code,
        "registration_ms": registration[1],
        "health_during_load_status": during_load.status_code,
        "health_during_load_ms": health_ms,
        "beneficiary_add_status": added.status_code,
        "invitation_status": invited.status_code if invited else None,
        "job_counts": counts,
        "new_accepted_jobs": counts.get("ACCEPTED", 0) - baseline_accepted,
        "scheduler_health_after_load": scheduler,
    }
    print(json.dumps(result, indent=2))
    assert all(code == 200 for code in initial.values()), result
    assert all(item[0].status_code == 200 for item in logins), result
    assert registration[0].status_code == 201, result
    assert during_load.status_code == 200, result
    assert added.status_code == 201 and invited and invited.status_code == 200, result
    assert counts.get("ACCEPTED", 0) >= baseline_accepted + 2 and scheduler == 200, result


if __name__ == "__main__":
    main()
