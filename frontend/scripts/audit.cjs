// Fail closed on audit errors and reported vulnerabilities.
const {spawnSync}=require("node:child_process");
const cli=process.env.npm_execpath||process.env.NPM_CLI_PATH;
const result=cli?spawnSync(process.execPath,[cli,"audit","--json"],{encoding:"utf8"}):spawnSync("npm",["audit","--json"],{encoding:"utf8",shell:process.platform==="win32"});
let report;try{report=JSON.parse(result.stdout);}catch{console.error("Dependency audit did not produce a valid report");process.exit(1);}
if(result.error || ![0,1].includes(result.status) || report.error ||
   !report.vulnerabilities || typeof report.metadata?.vulnerabilities?.total!=="number"){
 console.error("Dependency audit failed or returned an incomplete report");process.exit(1);
}
const vulnerabilities=Object.keys(report.vulnerabilities);
if(vulnerabilities.length || report.metadata.vulnerabilities.total!==0){
 console.error(`Dependency audit reported vulnerabilities: ${vulnerabilities.join(", ") || report.metadata.vulnerabilities.total}`);
 process.exit(1);
}
console.log("No dependency vulnerabilities reported.");
