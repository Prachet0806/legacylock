// Fail closed on audit errors and unreviewed vulnerabilities. The sole
// exception below is confined to development-only lint dependencies.
const {spawnSync}=require("node:child_process");
const {readFileSync}=require("node:fs");
const cli=process.env.npm_execpath||process.env.NPM_CLI_PATH;
const result=cli?spawnSync(process.execPath,[cli,"audit","--json"],{encoding:"utf8"}):spawnSync("npm",["audit","--json"],{encoding:"utf8",shell:process.platform==="win32"});
let report;try{report=JSON.parse(result.stdout);}catch{console.error("Dependency audit did not produce a valid report");process.exit(1);}
if(result.error || ![0,1].includes(result.status) || report.error ||
   !report.vulnerabilities || typeof report.metadata?.vulnerabilities?.total!=="number"){
 console.error("Dependency audit failed or returned an incomplete report");process.exit(1);
}
const vulnerabilities=Object.keys(report.vulnerabilities);
if(vulnerabilities.length===0 && report.metadata.vulnerabilities.total===0){
 console.log("No dependency vulnerabilities reported.");
 process.exit(0);
}
// GHSA-g3hv-75wg-m249 is a minimatch glob-pattern amplification issue.
// This tree uses the affected versions only in lint tooling. A global 11.0.1
// override breaks glob 7's matcher contract, so pinning it would hide a broken
// build tool behind a green audit. Reject every other advisory or runtime path.
let lock;try{lock=JSON.parse(readFileSync("package-lock.json","utf8"));}catch{console.error("Cannot verify development-only dependency paths");process.exit(1);}
const reviewed="https://github.com/advisories/GHSA-g3hv-75wg-m249";
function reachesReviewedRoot(name,seen=new Set()){
 if(name==="minimatch")return true;
 if(seen.has(name))return false;
 const next=new Set(seen);next.add(name);
 return report.vulnerabilities[name]?.via.some(dep=>typeof dep==="string" && reachesReviewedRoot(dep,next))===true;
}
function reviewedDevTree(name){
 const item=report.vulnerabilities[name];
 if(!item || item.severity!=="moderate" || !Array.isArray(item.nodes) || !item.nodes.length || !Array.isArray(item.via))return false;
 if(!item.nodes.every(node=>lock.packages?.[node]?.dev===true))return false;
 if(name==="minimatch")return item.via.length===1 && typeof item.via[0]==="object" && item.via[0]?.url===reviewed && item.via[0]?.severity==="moderate";
 return item.via.length>0 && item.via.every(dep=>typeof dep==="string" && report.vulnerabilities[dep]) && reachesReviewedRoot(name);
}
if(vulnerabilities.length===report.metadata.vulnerabilities.total &&
   vulnerabilities.includes("minimatch") && vulnerabilities.every(name=>reviewedDevTree(name))){
 console.warn("Allowlisted development-only advisory GHSA-g3hv-75wg-m249 remains in lint tooling; production dependencies must also pass npm audit --omit=dev.");
 process.exit(0);
}
console.error(`Dependency audit reported unreviewed vulnerabilities: ${vulnerabilities.join(", ") || report.metadata.vulnerabilities.total}`);
process.exit(1);
