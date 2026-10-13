"use client";
import {useEffect} from "react";
import {useParams,useRouter} from "next/navigation";
export default function HistoricalInvitation(){
 const params=useParams<{hash:string}>(),router=useRouter();
 useEffect(()=>{router.replace(`/access/invite#token=${encodeURIComponent(params.hash)}`);},[params.hash,router]);
 return <main className="mx-auto max-w-md px-4 py-10"><h1 className="page-title">Beneficiary invitation</h1><p>Opening invitation…</p></main>;
}
