"use client";
import Link from "next/link";
import {useEffect, useState} from "react";
import {publicFetch, sessionChanged} from "../../../lib/api/transport";

export default function Invitation() {
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [credentialReady,setCredentialReady]=useState(false);
  useEffect(()=> {
    const read=()=> {
      const value=new URLSearchParams(window.location.hash.slice(1)).get("token");
      if(value) {setToken(value);setDone(false);setMessage("");}
      window.history.replaceState(null,"",window.location.pathname);
    };
    read();
    window.addEventListener("hashchange",read);
    setCredentialReady(true);
    return ()=>window.removeEventListener("hashchange",read);
  },[]);
  async function accept() {
    setBusy(true);
    try {
      sessionChanged();
      await publicFetch("/access/invitation/accept", {method:"POST",body:JSON.stringify({token})});
      sessionChanged();
      setToken(""); setDone(true); setMessage("Invitation accepted. Keep your recovery shares safe; access will wait until release.");
    } catch(e) { setMessage(e instanceof Error ? e.message : "Invalid invitation"); }
    finally { setBusy(false); }
  }
  return <main data-credential-ready={credentialReady} className="mx-auto max-w-md px-4 py-10"><h1 className="page-title">Beneficiary invitation</h1>
    <p className="supporting mt-4">Accept your invitation to enroll. Your separately distributed recovery shares stay private.</p>
    {!done && <button className="btn-primary mt-4" disabled={!token || busy} onClick={accept}>{busy?"Accepting…":"Accept invitation"}</button>}
    <p role="status" className="mt-4">{message}</p>{done && <Link className="btn-primary mt-4" href="/recovery">Continue</Link>}</main>;
}
