"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {useVault} from "../../../lib/store/vault-context";
import {assertEpoch,currentEpoch,isUnlocked,subscribe,materialRevision, reshare} from "../../../lib/crypto-session";
import {finalizeCeremony, postRecoveryCeremony} from "../../../lib/client";
import {sessionChanged} from "../../../lib/api/transport";
import {CopyButton} from "../../../components/ui";

export default function ResharePage() {
  const {unlocked}=useVault();
  const [k,setK]=useState(2),[n,setN]=useState(3);
  const [shares,setShares]=useState<string[]>([]),[stored,setStored]=useState<boolean[]>([]);
  const [id,setId]=useState<number|null>(null),[message,setMessage]=useState(""),[busy,setBusy]=useState(false);
  useEffect(()=>subscribe(()=>{if(!isUnlocked()){setShares([]);setStored([]);setId(null);}}),[]);
  async function generate() {
    const before=currentEpoch();
    setBusy(true); setMessage("");
    try {
      const result=reshare(k,n);
      const draft=await postRecoveryCeremony({expected_revision:materialRevision(),recovery_threshold:k,recovery_total:n,recovery_generation:result.generation});
      assertEpoch(before);
      setShares(result.shares);setStored(result.shares.map(()=>false));setId(draft.ceremony_id??null);
    } catch(e) {setMessage(e instanceof Error?e.message:"Cannot create draft");}
    finally {setBusy(false);}
  }
  async function finish() {
    if(!id)return;setBusy(true);
    try {await finalizeCeremony(id,stored.map((ok,i)=>ok?i+1:0).filter(Boolean));setShares([]);setStored([]);sessionChanged();setMessage("Recovery set finalized. Reassign beneficiaries to the new distribution on People.");}
    catch(e){setMessage(e instanceof Error?e.message:"Finalization failed");}
    finally{setBusy(false);}
  }
  return <main className="mx-auto max-w-2xl px-4 py-8"><h1 className="page-title">Create a new recovery distribution</h1>
    <p className="supporting mt-4">This preserves your vault key and messages. Old quorums still know that key; resharing cannot revoke their access. If interrupted, restart with fresh shares and discard the abandoned set.</p>
    {!unlocked?<Link className="btn-primary mt-4" href="/vault">Unlock the vault first</Link>:<>
      {!shares.length && <div className="surface-lg mt-4"><label className="label">Required shares<input className="input" type="number" min={1} max={n} value={k} onChange={e=>setK(Number(e.target.value))}/></label><label className="label mt-3">Total shares<input className="input" type="number" min={k} max={10} value={n} onChange={e=>setN(Number(e.target.value))}/></label><button className="btn-primary mt-4" disabled={busy || k<1 || k>n || n>10} onClick={generate}>Generate fresh shares</button></div>}
      {shares.map((share,i)=><div key={i} className="surface-lg mt-4"><h2>Share {i+1}</h2><code className="block break-all text-xs mt-3">{share}</code><CopyButton text={share}/><label className="label mt-3"><input type="checkbox" checked={stored[i]} onChange={e=>setStored(stored.map((old,j)=>i===j?e.target.checked:old))}/> Stored separately and safely</label></div>)}
      {!!shares.length&&<button className="btn-primary mt-4" disabled={busy||!stored.every(Boolean)} onClick={finish}>Finalize distribution</button>}</>}
    <p className="mt-4" role="status">{message}</p>
  </main>;
}
