import { redirect } from "next/navigation";

// Legacy /login URL retired — the login form now lives at /.
export default function LoginRedirect() {
  redirect("/");
}
