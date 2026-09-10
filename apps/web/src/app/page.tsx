import { redirect } from "next/navigation";

import { requireOwnerSession } from "../lib/auth/session";

export default async function HomePage() {
  await requireOwnerSession();
  redirect("/inbox");
}
