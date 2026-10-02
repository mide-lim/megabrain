import { test, expect, type Page, type TestInfo } from "@playwright/test";

async function capture(page: Page, info: TestInfo, name: string) {
  await page.evaluate(() => document.fonts.ready);
  await expect(page.locator("body")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow, "page must fit viewport").toBe(false);
  const path = info.outputPath(name + ".png");
  await page.screenshot({ path, fullPage: true, animations: "disabled" });
  await info.attach(name, { path, contentType: "image/png" });
}
test.beforeEach(async ({ request }) => {
  await request.post("/__preview/control", { data: {} });
});
test("anonymous access stays on login", async ({ page }, info) => {
  await page.goto("/development");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("link", { name: "Entrar com Google" })).toBeVisible();
  await capture(page, info, "login");
});
test("owner navigates inbox library categories and development", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/auth/login");
  await expect(page).toHaveURL(/\/inbox$/);
  await expect(page.getByRole("heading", { name: "Inbox", exact: true })).toBeVisible();
  await capture(page, info, "inbox");
  await page.getByRole("link", { name: "Biblioteca", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Biblioteca de Reels" })).toBeVisible();
  await expect(page.getByRole("link", { name: /RFID na prática/ })).toBeVisible();
  await capture(page, info, "library");
  await page.getByRole("link", { name: /RFID na prática/ }).click();
  await expect(page.getByText("Exemplo fictício: conectar um leitor RFID ao projeto.")).toBeVisible();
  await capture(page, info, "reel-detail");
  await page.getByRole("link", { name: "Categorias", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Categorias", exact: true })).toBeVisible();
  await capture(page, info, "categories");
  await page.getByRole("link", { name: "Desenvolvimento", exact: true }).click();
  await expect(page.getByText("Paperclip online", { exact: true })).toBeVisible();
  await capture(page, info, "development");
  expect(errors).toEqual([]);
});
test("search and empty result are visible", async ({ page }, info) => {
  await page.goto("/auth/login");
  await page.goto("/library");
  await page.getByRole("searchbox", { name: /Buscar por criador/ }).fill("no-matching-preview");
  await page.getByRole("button", { name: "Buscar", exact: true }).click();
  await expect(page.getByText(/Nenhum Reel encontrado/)).toBeVisible();
  await capture(page, info, "library-empty");
});
test("transcription action reconciles queued state", async ({ page }, info) => {
  await page.goto("/auth/login");
  await page.goto("/reels/43");
  await page.getByRole("button", { name: "Transcrever", exact: true }).click();
  await expect(page.getByText("Na fila para transcrição.", { exact: true })).toBeVisible();
  await capture(page, info, "transcription-queued");
});
test("backend unavailable has its own library state", async ({ page, request }, info) => {
  await page.goto("/auth/login");
  await request.post("/__preview/control", { data: { unavailable: true, paperclip: false } });
  await page.goto("/library");
  await expect(page.getByText("Biblioteca temporariamente indisponível")).toBeVisible();
  await capture(page, info, "library-unavailable");
  await page.goto("/development");
  await expect(page.getByText("Indisponível", { exact: true })).toBeVisible();
  await capture(page, info, "paperclip-unavailable");
});

test("development status and launch action preserve the page in both states", async ({ page, request }, info) => {
  await page.goto("/auth/login");
  await page.goto("/development");
  await expect(page.getByRole("status")).toHaveText("Paperclip online");
  await expect(page.getByRole("button", { name: "Abrir Paperclip" })).toBeVisible();
  await capture(page, info, "development-online");
  await request.post("/__preview/control", { data: { paperclip: false } });
  await page.reload();
  await expect(page.getByRole("status")).toHaveText("Indisponível");
  await expect(page.getByRole("button", { name: "Abrir Paperclip" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Desenvolvimento", exact: true })).toBeVisible();
  await capture(page, info, "development-offline");
});
