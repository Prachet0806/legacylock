"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {getReadiness,reportDrill,type Readiness,listMessages,getMessage,ivOf} from "../../../lib/api/owner";
import {verifyRecovery,subscribe,isUnlocked} from "../../../lib/crypto-session";
import {SecurityChecklist} from "../../../components/security";

export default function SecurityCenterPage(){
 const [state,setState]=useState<Readiness|null>(null),[shares,setShares]=useState<string[]>([]),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 async function reload(){const r=await getReadiness();setState(r);setShares(Array.from({length:r.threshold},()=>""));}
 useEffect(()=>{reload().catch(e=>setError(e.message));return subscribe(()=>{if(!isUnlocked())setShares(old=>old.map(()=>""));});},[]);
 async function drill(){
   if(!state?.generation)return;setBusy(true);setError("");
   try{
     const messages=await listMessages();if(!messages.length)throw new Error("Save an encrypted sample message before running a drill.");
     const m=await getMessage(messages[0].id);
     await verifyRecovery(shares,state.threshold,state.generation,{v:m.crypto_version,algo:"AES-256-GCM",kdf:null,iv_b64:ivOf(m.crypto_metadata),wrapped_mek_b64:m.wrapped_mek,ciphertext_b64:m.ciphertext});
     await reportDrill({material_revision:state.material_revision,assignment_signature:state.assignment_signature,generation:state.generation});
     await reload();
   }catch(e){setError(e instanceof Error?e.message:"Drill failed");}
   finally{setShares(old=>old.map(()=>""));setBusy(false);}
 }
 return <main className="mx-auto max-w-2xl px-4 py-8"><Link href="/settings" className="text-sm text-muted">Back to settings</Link><h1 className="page-title mt-3">Recovery readiness</h1>
 <p className="supporting mt-3">Enrollment, share assignments, and a recovery drill are separate evidence. Mailbox access alone cannot decrypt your vault.</p>
 {error&&<p role="alert" className="mt-4 text-danger">{error}</p>}
 {!state?<p className="mt-6">Loading current evidence…</p>:<>
 <section className="surface-lg mt-6"><SecurityChecklist items={[
 {label:"Vault wrapping material saved",ok:state.initialized},
 {label:`Finalized recovery ceremony (${state.threshold}-of-${state.total})`,ok:state.ceremony_status === "READY"},
 {label:`Accepted recipients assigned to current shares: ${state.eligible_assignments}`,ok:state.quorum_assigned},
 {label:"Heartbeat armed",ok:state.armed},
 {label:"Current owner-reported recovery drill",ok:!!state.owner_reported_drill},
 ]}/>{state.ceremony_status === "LEGACY"&&<p className="mt-4 text-sm">Your existing recovery format is preserved. Create a replacement distribution to record current ceremony evidence.</p>}
 <p className="mt-4 text-sm text-muted">Recipient possession has not been independently verified. Assignment labels and owner acknowledgments do not prove safe storage.</p>
 {state.owner_reported_drill&&<p className="mt-3 text-sm">Last owner-reported drill: {new Date(state.owner_reported_drill.reported_at).toLocaleString()}</p>}
 </section>
 {state.generation&&state.ceremony_status === "READY"&&<section className="surface-lg mt-4"><h2 className="font-semibold">Run a local recovery drill</h2><p className="supporting mt-2">Enter {state.threshold} distinct current shares. This browser reconstructs the key and decrypts a sample. Only the generation, material revision, assignment signature, and report time are recorded.</p>
 {shares.map((value,i)=><label key={i} className="label mt-4">Share {i+1}<textarea className="input font-mono" autoComplete="off" value={value} onChange={e=>setShares(old=>old.map((s,j)=>j===i?e.target.value:s))}/></label>)}
 <button className="btn-primary mt-4" disabled={busy||shares.some(s=>!s.trim())} onClick={drill}>{busy?"Verifying locally…":"Verify and record drill"}</button></section>}
 </>}
 <section className="surface-lg mt-4"><h2 className="font-semibold">Encryption format</h2><p className="supporting mt-2">Messages use AES-256-GCM. Vault wrapping uses AES-KW and PBKDF2-SHA256 with 600,000 iterations for new material. Shares are split and reconstructed locally. Account passwords use Argon2id; sessions use RS256 and HttpOnly cookies.</p></section>
 </main>;
}
