"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { publicFetch, sessionChanged } from "../../../lib/api/transport";

export default function BeneficiaryLogin() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [credentialReady,setCredentialReady]=useState(false);
  useEffect(() => {
    const read = () => {
      const value=new URLSearchParams(window.location.hash.slice(1)).get("token");
      if(value) {setToken(value);setSignedIn(false);setMessage("");}
      window.history.replaceState(null, "", window.location.pathname);
    };
    read();
    window.addEventListener("hashchange",read);
    setCredentialReady(true);
    return ()=>window.removeEventListener("hashchange",read);
  }, []);
  async function submit() {
    setBusy(true); setMessage("");
    try {
      if (token) {
        sessionChanged();
        await publicFetch("/access/login/redeem", {method:"POST", body:JSON.stringify({token})});
        sessionChanged();
        setToken(""); setSignedIn(true); setMessage("Signed in. Vault contents remain encrypted until you enter your recovery shares.");
      } else {
        const result = await publicFetch<{message:string}>("/access/login/request", {method:"POST", body:JSON.stringify({email})});
        setMessage(result.message);
      }
    } catch (e) { setMessage(e instanceof Error ? e.message : "Sign-in failed"); }
    finally { setBusy(false); }
  }
  return <main data-credential-ready={credentialReady} className="mx-auto max-w-md px-4 py-10"><h1 className="page-title">Beneficiary sign-in</h1>
    <p className="supporting mt-3">Use the email where you accepted the invitation. You can request a new sign-in link whenever you need access.</p>
    {!signedIn && <form className="surface-lg mt-6" onSubmit={(e) => {e.preventDefault(); void submit();}}>
      {!token && <><label className="label" htmlFor="beneficiary-email">Email</label><input id="beneficiary-email" className="input" type="email" autoComplete="email" required value={email} onChange={(e)=>setEmail(e.target.value)}/></>}
      <button className="btn-primary mt-4" disabled={busy}>{busy ? "Please wait…" : token ? "Confirm sign-in" : "Email a sign-in link"}</button>
    </form>}
    <p className="mt-4" role="status">{message}</p>{signedIn && <Link className="btn-primary mt-4" href="/recovery">Continue to recovery</Link>}
  </main>;
}
