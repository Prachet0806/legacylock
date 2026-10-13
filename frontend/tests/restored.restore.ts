import {test,expect} from "@playwright/test";
import {readFileSync} from "node:fs";
import {execFileSync} from "node:child_process";
import path from "node:path";

test("restored held deployment supports owner decryption and fresh beneficiary sign-in with original synthetic quorum",async({page,browser})=>{
  test.setTimeout(90000);
  if(!process.env.E2E_RESTORE_FIXTURE_PATH || !process.env.RESTORE_PYTHON)throw new Error("Explicit isolated restore fixture and Python runtime required");
  const fixture=JSON.parse(readFileSync(process.env.E2E_RESTORE_FIXTURE_PATH,"utf8"));
  await page.goto("/");
  await page.getByLabel("Email").fill(fixture.owner_email);
  await page.getByLabel("Password",{exact:true}).fill("DevPassword123456");
  await page.getByRole("button",{name:"Sign in",exact:true}).click();
  await expect(page).toHaveURL(/\/home$/);
  await page.goto("/vault");
  await page.getByRole("button",{name:"Unlock vault",exact:true}).click();
  await page.getByLabel("Vault passphrase").fill("E2E-Vault-Passphrase-12345");
  await page.getByRole("button",{name:"Unlock",exact:true}).click();
  const first=page.locator("li",{hasText:fixture.labels[0]});
  // Owner viewer selectors match the accessible card action.
  await first.getByRole("button",{name:/open/i}).click();
  await page.getByRole("button",{name:"Reveal secret",exact:true}).click();
  await expect(page.getByText(fixture.bodies[0],{exact:true})).toBeVisible();
  const context=await browser.newContext();
  const ben=await context.newPage();
  await ben.goto("/access/login");
  await ben.getByLabel("Email").fill(fixture.beneficiary_email);
  const requested=ben.waitForResponse(response=>new URL(response.url()).pathname==="/api/access/login/request");
  await ben.getByRole("button",{name:"Email a sign-in link",exact:true}).click();
  expect((await requested).ok()).toBe(true);
  // Read the synthetic test mailbox from the HELD restored database. The
  // raw credential stays in process memory and is never printed or saved.
  const code="import sys; from db import SessionLocal; from models import DeliveryJob,Beneficiary,BusinessEvent; from services.outbox import unprotect; db=SessionLocal(); row=db.query(DeliveryJob).join(BusinessEvent).join(Beneficiary,DeliveryJob.beneficiary_id==Beneficiary.id).filter(Beneficiary.email==sys.argv[1],BusinessEvent.kind=='beneficiary_login',DeliveryJob.payload.isnot(None)).order_by(DeliveryJob.created_at.desc()).first(); print(unprotect(row)['body'].split('http://localhost:3000',1)[1].split()[0]); db.close()";
  const link=execFileSync(process.env.RESTORE_PYTHON,["-c",code,fixture.beneficiary_email],{cwd:path.resolve("../backend"),encoding:"utf8"}).trim();
  await ben.goto(link);
  await ben.getByRole("button",{name:/confirm.*sign-in/i}).click();
  await ben.getByRole("link",{name:"Continue to recovery",exact:true}).click();
  await expect(ben).toHaveURL(/\/recovery$/);
  await ben.getByRole("button",{name:"Continue",exact:true}).click();
  await ben.getByLabel("Share 1").fill(fixture.shares[0]);
  await ben.getByLabel("Share 2").fill(fixture.shares[1]);
  await ben.getByRole("button",{name:"Reconstruct",exact:true}).click();
  await ben.locator("li",{hasText:fixture.labels[0]}).getByRole("button",{name:"Decrypt",exact:true}).click();
  await expect(ben.getByText(fixture.bodies[0],{exact:true})).toBeVisible();
  expect(new URL(ben.url()).hash).toBe("");
  await context.close();
});
