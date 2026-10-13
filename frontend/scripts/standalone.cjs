// Exercise exactly the standalone layout shipped by the Docker image.
const fs = require("node:fs");
const path = require("node:path");
const {spawn} = require("node:child_process");
const root = path.resolve(__dirname, "..");
const directory = path.join(root, ".next", "standalone");
fs.cpSync(path.join(root, ".next", "static"), path.join(directory, ".next", "static"), {recursive:true});
if(fs.existsSync(path.join(root,"public"))) fs.cpSync(path.join(root,"public"),path.join(directory,"public"),{recursive:true});
const server=spawn(process.execPath,[path.join(directory,"server.js")],{cwd:directory,stdio:"inherit",env:{...process.env,HOSTNAME:"127.0.0.1",PORT:process.env.PORT||"3000"}});
for(const signal of ["SIGINT","SIGTERM"]) process.on(signal,()=>server.kill(signal));
server.on("exit",code=>process.exit(code??1));
