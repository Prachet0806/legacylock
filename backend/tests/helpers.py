"""Client journeys shared by tests; no mutation of application test transport."""


def complete_ceremony(client, *, json, headers):
    material = client.get("/vault/crypto-material", headers=headers).json()
    data = {"expected_revision": material["material_revision"], **json}
    draft = client.post("/vault/recovery-ceremony", json=data, headers=headers)
    if draft.status_code != 200:
        return draft
    done = client.post(
        f"/vault/recovery-ceremony/{draft.json()['ceremony_id']}/finalize",
        json={"stored_indexes": list(range(1, data["recovery_total"] + 1))},
        headers=headers,
    )
    if done.status_code != 200:
        return done
    return client.get("/vault/recovery-policy", headers=headers)
