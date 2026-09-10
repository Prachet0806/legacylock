"use client";

import { useEffect, useState } from "react";
import { addBeneficiary, listBeneficiaries, inviteBeneficiary, deleteBeneficiary, type Beneficiary } from "../../lib/client";

export default function BeneficiariesPage() {
  const [rows, setRows] = useState<Beneficiary[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [link, setLink] = useState("");

  async function refresh() {
    setRows(await listBeneficiaries());
  }
  useEffect(() => {
    refresh().catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  async function onAdd() {
    setErr("");
    try {
      await addBeneficiary({ name, email });
      setName("");
      setEmail("");
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Add failed");
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 640 }}>
      <h1>Beneficiaries (2-of-3: configure 3)</h1>
      <div style={{ display: "flex", gap: 8 }}>
        <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <button onClick={onAdd}>Add</button>
      </div>
      <ul>
        {rows.map((b) => (
          <li key={b.id}>
            {b.name} &lt;{b.email}&gt; [{b.invitation_status}]
            <button onClick={async () => {
              const r = await inviteBeneficiary(b.id);
              setLink(r.invitation_link);
            }} style={{ marginLeft: 8 }}>Invite</button>
            <button onClick={async () => {
              await deleteBeneficiary(b.id);
              await refresh();
            }} style={{ marginLeft: 8 }}>Remove</button>
          </li>
        ))}
      </ul>
      {link && <p>Invitation link (send out-of-band): <code style={{ wordBreak: "break-all" }}>{link}</code></p>}
      {err && <p style={{ color: "red" }}>{err}</p>}
    </main>
  );
}
