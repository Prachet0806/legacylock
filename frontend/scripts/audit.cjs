// Fail closed except for the explicitly bounded build-tool advisory below.
const {spawnSync}=require("node:child_process");
const cli=process.env.npm_execpath||process.env.NPM_CLI_PATH;
const result=cli?spawnSync(process.execPath,[cli,"audit","--json"],{encoding:"utf8"}):spawnSync("npm",["audit","--json"],{encoding:"utf8",shell:process.platform==="win32"});
let report;try{report=JSON.parse(result.stdout);}catch{console.error("Dependency audit did not produce a valid report");process.exit(1);}
if(result.error || ![0,1].includes(result.status) || report.error ||
   !report.vulnerabilities || typeof report.metadata?.vulnerabilities?.total!=="number"){
 console.error("Dependency audit failed or returned an incomplete report");process.exit(1);
}
const allowed="GHSA-vfj7-8cjw-p6xm";
const expires=Date.parse("2026-11-11T00:00:00Z");
const unexpected=[];
for(const [name,item] of Object.entries(report.vulnerabilities||{})){
 for(const via of item.via){
  if(typeof via==="string"){
   if(!report.vulnerabilities[via]) unexpected.push(`${name}: unresolved advisory dependency ${via}`);
   continue; // direct advisory nodes below remain authoritative
  }
  if(!via.url.endsWith(allowed)||Date.now()>=expires||name!=="braces"||item.isDirect)unexpected.push(`${name}: ${via.url}`);
 }
}
if(unexpected.length){console.error(unexpected.join("\n"));process.exit(1);}
if(Object.keys(report.vulnerabilities||{}).length)console.log("Accepted temporary build-only braces advisory; expires 2026-11-11. See docs/dependency-exceptions.md.");
else console.log("No dependency vulnerabilities reported.");
