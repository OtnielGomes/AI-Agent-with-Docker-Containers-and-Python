import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

/**
 * Browser seam for the chat page. Same-origin routes are stubbed.
 * The Python API and SMTP stay out of this suite.
 */

type DraftState = "open" | "sent" | "discarded";

type Draft = {
  id: string;
  subject: string;
  body: string;
  recipient: string;
  state: DraftState;
};

type ApiCall = {
  pathname: string;
  search: string;
  method: string;
  body: string;
};

type InboundEmail = {
  id: string;
  sender: string;
  address: string;
  subject: string;
  date: string;
  unread: boolean;
  body: string;
};

type World = {
  online: boolean;
  drafts: Draft[];
  emails: InboundEmail[];
  inboxStatus: number;
  recipients: string[];
  holdHealth: Promise<void> | null;
  calls: ApiCall[];
  chat: (route: Route) => Promise<void>;
  confirm: (route: Route) => Promise<void>;
  discard: (route: Route) => Promise<void>;
  discardOpen: (route: Route) => Promise<void>;
  markRead: (route: Route) => Promise<void>;
  reply: (route: Route) => Promise<void>;
};

const EXAMPLES = [
  "Resume meus últimos 3 e-mails.",
  "Escreva um e-mail sobre inteligência artificial aplicada a negócios.",
  "Ajude-me a escrever um e-mail para marcar uma reunião nesta semana.",
] as const;

function inbound(overrides: Partial<InboundEmail> & Pick<InboundEmail, "id">): InboundEmail {
  return {
    sender: "Maria Silva",
    address: "maria@example.com",
    subject: "Assunto",
    date: "25 set 2026",
    unread: false,
    body: "Texto do e-mail.",
    ...overrides,
  };
}

function draft(overrides: Partial<Draft> & Pick<Draft, "id">): Draft {
  return {
    subject: "Assunto",
    body: "Olá,\n\nTexto.\n\nAté mais!",
    recipient: "ana@example.com",
    state: "open",
    ...overrides,
  };
}

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function defaultChat(route: Route) {
  await fulfillJson(route, { content: "Pronto.", drafts: [] });
}

async function defaultConfirm(route: Route) {
  const id = new URL(route.request().url()).pathname.split("/")[3];
  const body = route.request().postDataJSON() as {
    subject: string;
    body: string;
    recipient: string;
  };
  await fulfillJson(route, { id, ...body, state: "sent" });
}

async function defaultDiscard(route: Route) {
  const id = new URL(route.request().url()).pathname.split("/")[3];
  await fulfillJson(route, {
    id,
    subject: "",
    body: "",
    recipient: "",
    state: "discarded",
  });
}

async function defaultDiscardOpen(route: Route) {
  await fulfillJson(route, { drafts: [] });
}

async function defaultMarkRead(route: Route) {
  await fulfillJson(route, { unread: false });
}

async function defaultReply(route: Route) {
  const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/")[3] ?? "");
  const email = world.emails.find((item) => item.id === id);
  const subject = email?.subject ? `Re: ${email.subject.replace(/^(re:\s*)+/i, "")}` : "Re:";
  await fulfillJson(route, {
    id: `reply-${id}`,
    subject,
    body: email?.sender && email.sender !== email.address
      ? `Olá, ${email.sender},\n\nResposta.\n\nAté mais!`
      : "Olá,\n\nResposta.\n\nAté mais!",
    recipient: email?.address ?? "maria@example.com",
    state: "open",
    inboundId: id,
  });
}

function createWorld(): World {
  return {
    online: true,
    drafts: [],
    emails: [],
    inboxStatus: 200,
    recipients: [],
    holdHealth: null,
    calls: [],
    chat: defaultChat,
    confirm: defaultConfirm,
    discard: defaultDiscard,
    discardOpen: defaultDiscardOpen,
    markRead: defaultMarkRead,
    reply: defaultReply,
  };
}

async function install(page: Page, world: World) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname.replace(/\/$/, "") || "/";
    const method = route.request().method();
    world.calls.push({
      pathname,
      search: url.search,
      method,
      body: route.request().postData() ?? "",
    });

    if (pathname === "/api/health" && method === "POST") {
      if (world.holdHealth) {
        await world.holdHealth;
      }
      await fulfillJson(route, { online: world.online });
      return;
    }
    if (pathname === "/api/chat" && method === "POST") {
      await world.chat(route);
      return;
    }
    if (pathname === "/api/drafts/prior-recipients" && method === "GET") {
      await fulfillJson(route, { recipients: world.recipients });
      return;
    }
    if (pathname === "/api/drafts/discard-open" && method === "POST") {
      await world.discardOpen(route);
      return;
    }
    if (/^\/api\/drafts\/[^/]+\/confirm$/.test(pathname) && method === "POST") {
      await world.confirm(route);
      return;
    }
    if (/^\/api\/drafts\/[^/]+\/discard$/.test(pathname) && method === "POST") {
      await world.discard(route);
      return;
    }
    if (pathname === "/api/drafts" && method === "GET") {
      await fulfillJson(route, { drafts: world.drafts });
      return;
    }
    if (pathname === "/api/inbox" && method === "GET") {
      if (world.inboxStatus !== 200) {
        await fulfillJson(route, { error: "inbox down" }, world.inboxStatus);
        return;
      }
      await fulfillJson(route, { emails: world.emails });
      return;
    }
    if (/^\/api\/inbox\/[^/]+\/read$/.test(pathname) && method === "POST") {
      await world.markRead(route);
      return;
    }
    if (/^\/api\/inbox\/[^/]+\/reply$/.test(pathname) && method === "POST") {
      await world.reply(route);
      return;
    }
    await fulfillJson(route, { error: `unexpected ${method} ${pathname}` }, 500);
  });
}

function callsEnding(world: World, suffix: string, method?: string) {
  return world.calls.filter(
    (call) => call.pathname.endsWith(suffix) && (method === undefined || call.method === method),
  );
}

function callsTo(world: World, pathname: string, method?: string) {
  return world.calls.filter(
    (call) => call.pathname === pathname && (method === undefined || call.method === method),
  );
}

function deferred() {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function interfaceAlert(page: Page) {
  return page.locator("form").getByRole("alert");
}

async function openChat(page: Page) {
  await page.goto("/");
  await expect(page.getByText(/^API (online|offline)$/)).toBeVisible();
}

async function boxOf(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) {
    throw new Error("Element has no bounding box");
  }
  return box;
}

function channels(color: string): [number, number, number] {
  const matches = color.match(/[\d.]+/g);
  if (!matches || matches.length < 3) {
    throw new Error(`Unparsed color: ${color}`);
  }
  return [Number(matches[0]), Number(matches[1]), Number(matches[2])];
}

function isBrandBlue(color: string): boolean {
  const [red, green, blue] = channels(color);
  return red === 62 && green === 92 && blue === 133;
}

function isWhite(color: string): boolean {
  const [red, green, blue] = channels(color);
  return red === 255 && green === 255 && blue === 255;
}

function isGreenDominant(color: string): boolean {
  const [red, green, blue] = channels(color);
  return green > red + 15 && green > blue + 15;
}

let world: World;

test.beforeEach(async ({ page }) => {
  world = createWorld();
  await install(page, world);
});

test("opens a Portuguese session without a backend console", async ({ page }) => {
  await openChat(page);

  await expect(page).toHaveTitle("Assistente de e-mail");
  await expect(page.locator("html")).toHaveAttribute("lang", "pt");
  await expect(page.getByRole("heading", { name: "Assistente de e-mail" })).toBeVisible();
  await expect(page.getByRole("banner").getByRole("paragraph")).toHaveText(
    "Pesquisa, caixa de entrada e rascunhos.",
  );
  await expect(page.getByRole("region", { name: "Conversa" }).getByRole("paragraph")).toHaveCount(0);
  await expect(page.getByText(/Ask the agent|History is kept|LangGraph|Clear chat/)).toHaveCount(0);
  await expect(page.getByLabel("Backend URL")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /test connection|testar conexão/i })).toHaveCount(0);
  for (const prompt of EXAMPLES) {
    await expect(page.getByRole("button", { name: prompt, exact: true })).toBeVisible();
  }
  expect(callsTo(world, "/api/config")).toHaveLength(0);
  for (const call of world.calls) {
    expect(call.search).not.toContain("backendUrl");
    expect(call.body).not.toContain("backendUrl");
  }
});

test("health chip moves from checking to online or offline", async ({ page }) => {
  const gate = deferred();
  world.holdHealth = gate.promise;
  await page.goto("/");
  await expect(page.getByText("Verificando…", { exact: true })).toBeVisible();
  gate.resolve();
  await expect(page.getByText("API online", { exact: true })).toBeVisible();

  world.online = false;
  world.holdHealth = null;
  await page.reload();
  await expect(page.getByText("API offline", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Mensagem" })).toBeEnabled();
});

test("composer sends on Enter, breaks on Shift+Enter, and ignores an empty message", async ({ page }) => {
  await openChat(page);
  const composer = page.getByRole("textbox", { name: "Mensagem" });
  await composer.press("Enter");
  await expect(page.getByRole("article", { name: "Você" })).toHaveCount(0);

  await composer.fill("linha 1");
  await composer.press("Shift+Enter");
  await composer.type("linha 2");
  await expect(composer).toHaveValue("linha 1\nlinha 2");

  await composer.press("Enter");
  await expect(page.getByRole("article", { name: "Você" })).toContainText("linha 1");
  const chat = callsTo(world, "/api/chat", "POST").at(-1);
  expect(JSON.parse(chat?.body ?? "{}").message).toBe("linha 1\nlinha 2");
  expect(JSON.parse(chat?.body ?? "{}")).not.toHaveProperty("to_email");
  expect(JSON.parse(chat?.body ?? "{}")).not.toHaveProperty("backendUrl");
});

test("shows the reply as plain text and places the human message on the right", async ({ page }) => {
  world.chat = async (route) => {
    await fulfillJson(route, {
      content: "**não interprete**\nsegunda linha",
      drafts: [],
    });
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("Olá");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();

  const human = page.getByRole("article", { name: "Você" });
  const assistant = page.getByRole("article", { name: "Assistente" });
  await expect(human).toBeVisible();
  await expect(assistant).toBeVisible();
  const humanBox = await boxOf(human);
  const assistantBox = await boxOf(assistant);
  expect(humanBox.x).toBeGreaterThan(assistantBox.x);

  const reply = await assistant.locator("p").nth(1).evaluate((node) => node.textContent);
  expect(reply).toBe("**não interprete**\nsegunda linha");
  await expect(assistant.locator("strong")).toHaveCount(0);

  const talk = await page
    .getByRole("button", { name: "Enviar mensagem", exact: true })
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  const bubble = await human.evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(bubble).toBe(talk);
});

test("locks the composer while the reply is prepared", async ({ page }) => {
  const gate = deferred();
  world.chat = async (route) => {
    await gate.promise;
    await fulfillJson(route, { content: "Pronto.", drafts: [] });
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("Pesquisa");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();

  const transcript = page.getByRole("region", { name: "Conversa" });
  await expect(transcript.getByText("Preparando a resposta… Pode levar alguns minutos.")).toBeVisible();
  await expect(transcript.getByRole("article", { name: "Você" })).toContainText("Pesquisa");
  await expect(page.getByRole("textbox", { name: "Mensagem" })).toBeDisabled();
  await expect(page.getByRole("button", { name: EXAMPLES[0], exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Limpar conversa", exact: true })).toBeDisabled();
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /cancelar|cancel/i })).toHaveCount(0);

  gate.resolve();
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("Pronto.");
  await expect(page.getByRole("textbox", { name: "Mensagem" })).toBeEnabled();
});

test("connection, timeout, and rejected turns are alerts above the composer", async ({ page }) => {
  world.chat = async (route) => {
    await route.abort("failed");
  };
  await openChat(page);
  const composer = page.getByRole("textbox", { name: "Mensagem" });
  await composer.fill("ainda aqui");
  await composer.press("Enter");
  const transcript = page.getByRole("region", { name: "Conversa" });
  await expect(interfaceAlert(page)).toHaveText("Não foi possível falar com a API.");
  await expect(transcript.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Assistente" })).toHaveCount(0);
  await expect(composer).toHaveValue("ainda aqui");
  await expect(composer).toBeEnabled();

  world.chat = async (route) => {
    await fulfillJson(
      route,
      { error: "Request timed out. Research and email flows can take several minutes." },
      502,
    );
  };
  await composer.fill("demora");
  await composer.press("Enter");
  await expect(interfaceAlert(page)).toHaveText("A resposta demorou demais.");
  await expect(page.getByRole("article", { name: "Assistente" })).toHaveCount(0);
  await expect(composer).toHaveValue("demora");

  world.chat = async (route) => {
    await fulfillJson(route, { error: "Inbox unavailable." }, 502);
  };
  await composer.fill("recusa");
  await composer.press("Enter");
  await expect(interfaceAlert(page)).toHaveText("Inbox unavailable.");
  await expect(transcript.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Assistente" })).toHaveCount(0);
});

test("an example sends immediately with the current pin and does not fill the composer", async ({ page }) => {
  await openChat(page);
  await page.getByRole("radio", { name: "Outro destinatário" }).check();
  await page.getByRole("button", { name: EXAMPLES[0], exact: true }).click();
  await expect(interfaceAlert(page)).toHaveText("Informe o e-mail do destinatário.");
  expect(callsTo(world, "/api/chat")).toHaveLength(0);

  await page.getByRole("textbox", { name: "E-mail do destinatário" }).fill("nope");
  await page.getByRole("button", { name: EXAMPLES[1], exact: true }).click();
  await expect(interfaceAlert(page)).toHaveText("Informe um e-mail válido.");
  expect(callsTo(world, "/api/chat")).toHaveLength(0);

  await page.getByRole("textbox", { name: "E-mail do destinatário" }).fill("ana@example.com");
  await page.getByRole("textbox", { name: "Mensagem" }).fill("rascunho local");
  await page.getByRole("button", { name: EXAMPLES[2], exact: true }).click();
  await expect(page.getByRole("article", { name: "Você" })).toContainText(EXAMPLES[2]);
  await expect(page.getByRole("textbox", { name: "Mensagem" })).toHaveValue("rascunho local");
  await expect(interfaceAlert(page)).toHaveCount(0);
  const chat = JSON.parse(callsTo(world, "/api/chat", "POST").at(-1)?.body ?? "{}") as {
    message: string;
    to_email?: string;
  };
  expect(chat.message).toBe(EXAMPLES[2]);
  expect(chat.to_email).toBe("ana@example.com");
  await expect(page.getByRole("radio", { name: "Outro destinatário" })).toBeChecked();
  await expect(page.getByRole("textbox", { name: "E-mail do destinatário" })).toHaveValue(
    "ana@example.com",
  );
});

test("pins another recipient only when the address is valid", async ({ page }) => {
  await openChat(page);
  await expect(page.getByRole("radio", { name: "Minha caixa de entrada" })).toBeChecked();
  await expect(page.getByRole("radio", { name: "Outro destinatário" })).not.toBeChecked();
  await expect(
    page.getByText("Os e-mails saem para o endereço configurado na aplicação."),
  ).toBeVisible();
  await expect(page.getByRole("textbox", { name: "E-mail do destinatário" })).toHaveCount(0);

  await page.getByRole("textbox", { name: "Mensagem" }).fill("para mim");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const inboxCall = JSON.parse(callsTo(world, "/api/chat", "POST").at(-1)?.body ?? "{}");
  expect(inboxCall).not.toHaveProperty("to_email");
  await expect(interfaceAlert(page)).toHaveCount(0);

  await page.getByRole("radio", { name: "Outro destinatário" }).check();
  await expect(page.getByRole("radio", { name: "Minha caixa de entrada" })).not.toBeChecked();
  await expect(
    page.getByText("Os e-mails saem para o endereço configurado na aplicação."),
  ).toHaveCount(0);
  await page.getByRole("textbox", { name: "E-mail do destinatário" }).fill("bia@example.com");
  await page.getByRole("textbox", { name: "Mensagem" }).fill("para a bia");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const pinned = JSON.parse(callsTo(world, "/api/chat", "POST").at(-1)?.body ?? "{}") as {
    to_email: string;
  };
  expect(pinned.to_email).toBe("bia@example.com");
  await expect(page.getByRole("radio", { name: "Outro destinatário" })).toBeChecked();
});

test("offers each prior recipient once while an address is typed", async ({ page }) => {
  world.recipients = ["bia@example.com", "ana@example.com"];
  await openChat(page);
  await expect(page.getByRole("list", { name: "Destinatários anteriores" })).toHaveCount(0);

  await page.getByRole("radio", { name: "Outro destinatário" }).check();
  await expect(page.getByRole("list", { name: "Destinatários anteriores" })).toHaveCount(0);

  const field = page.getByRole("textbox", { name: "E-mail do destinatário" });
  await field.fill("ANA");
  const list = page.getByRole("list", { name: "Destinatários anteriores" });
  await expect(list.getByRole("button")).toHaveText(["ana@example.com"]);
  await list.getByRole("button", { name: "ana@example.com", exact: true }).click();
  await expect(field).toHaveValue("ana@example.com");

  await field.fill("example");
  await expect(list.getByRole("button")).toHaveText(["bia@example.com", "ana@example.com"]);
  await page.getByRole("radio", { name: "Minha caixa de entrada" }).check();
  await expect(list).toHaveCount(0);

  await page.getByRole("radio", { name: "Outro destinatário" }).check();
  await field.fill("nova@example.com");
  await page.getByRole("textbox", { name: "Mensagem" }).fill("nova");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const pinned = JSON.parse(callsTo(world, "/api/chat", "POST").at(-1)?.body ?? "{}") as {
    to_email: string;
  };
  expect(pinned.to_email).toBe("nova@example.com");
});

test("a pin change leaves the open review card recipient as it was", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", recipient: "ana@example.com" })];
  world.recipients = ["bia@example.com"];
  await openChat(page);
  const card = page.getByRole("article", { name: "Rascunho: Assunto" });
  await page.getByRole("radio", { name: "Outro destinatário" }).check();
  await page.getByRole("textbox", { name: "E-mail do destinatário" }).fill("bi");
  await page.getByRole("button", { name: "bia@example.com", exact: true }).click();
  await expect(card.getByRole("textbox", { name: "Destinatário", exact: true })).toHaveValue(
    "ana@example.com",
  );
});

test("shows open drafts on review cards, oldest first, and hides the region when none are open", async ({ page }) => {
  await openChat(page);
  await expect(page.getByRole("region", { name: "Rascunhos" })).toHaveCount(0);

  world.drafts = [
    draft({ id: "draft-secret-id-999", subject: "Mais antigo", recipient: "ana@example.com" }),
    draft({ id: "draft-2", subject: "Mais novo", recipient: "bia@example.com" }),
  ];
  await page.reload();
  await expect(page.getByText("API online", { exact: true })).toBeVisible();

  const cards = page.getByRole("region", { name: "Rascunhos" }).getByRole("article");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toHaveAccessibleName("Rascunho: Mais antigo");
  await expect(cards.nth(1)).toHaveAccessibleName("Rascunho: Mais novo");
  await expect(cards.nth(0).getByText("Rascunho", { exact: true })).toBeVisible();
  await expect(cards.nth(0).getByRole("textbox", { name: "Assunto", exact: true })).toHaveValue(
    "Mais antigo",
  );
  await expect(cards.nth(0).getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toBeVisible();
  await expect(cards.nth(0).getByRole("textbox", { name: "Destinatário", exact: true })).toHaveValue(
    "ana@example.com",
  );
  await expect(page.getByText("draft-secret-id-999")).toHaveCount(0);
});

test("places review cards beside the conversation on a wide page and above the composer on a narrow one", async ({ page }) => {
  const longBody = Array.from({ length: 40 }, (_, index) => `Linha ${index} do corpo do rascunho.`).join("\n");
  world.drafts = [draft({ id: "open-1", subject: "Ao lado", body: longBody })];
  await page.setViewportSize({ width: 1280, height: 800 });
  await openChat(page);

  const sidebar = page.getByRole("complementary");
  const transcript = page.getByRole("region", { name: "Conversa" });
  const review = page.getByRole("region", { name: "Rascunhos" });
  const composer = page.locator("form");

  const wideSidebar = await boxOf(sidebar);
  const wideTranscript = await boxOf(transcript);
  const wideReview = await boxOf(review);
  expect(wideSidebar.x).toBeLessThan(wideTranscript.x);
  expect(wideTranscript.x).toBeLessThan(wideReview.x);
  expect(wideReview.width).toBeGreaterThan(31 * 16);
  expect(wideReview.width).toBeLessThan(33 * 16);
  await expect(page.getByRole("menu")).toHaveCount(0);

  await page.setViewportSize({ width: 800, height: 1100 });
  const narrowSidebar = await boxOf(sidebar);
  const narrowTranscript = await boxOf(transcript);
  const narrowReview = await boxOf(review);
  const narrowComposer = await boxOf(composer);
  expect(narrowSidebar.y).toBeLessThan(narrowTranscript.y);
  expect(narrowTranscript.y + narrowTranscript.height).toBeLessThanOrEqual(narrowReview.y + 4);
  expect(narrowReview.y).toBeLessThan(narrowComposer.y);
  expect(Math.abs(narrowReview.x - narrowTranscript.x)).toBeLessThan(40);
  expect(narrowReview.height).toBeGreaterThan(1100 * 0.55);
  expect(narrowReview.height).toBeLessThanOrEqual(1100 * 0.65);
});

test("keeps the review cards in view while the transcript scrolls", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", subject: "Fixo" })];
  world.chat = async (route) => {
    const lines = Array.from({ length: 40 }, (_, index) => `linha ${index + 1}`).join("\n");
    await fulfillJson(route, { content: lines, drafts: [] });
  };
  await page.setViewportSize({ width: 1280, height: 800 });
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("longo");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "Assistente" })).toBeVisible();

  const transcript = page.getByRole("region", { name: "Conversa" });
  const review = page.getByRole("region", { name: "Rascunhos" });
  const before = await boxOf(review);
  await transcript.evaluate((node) => {
    node.scrollTop = 0;
  });
  const after = await boxOf(review);
  expect(Math.abs(after.y - before.y)).toBeLessThan(2);
  await expect(review).toBeInViewport();
});

test("refresh restores stored open drafts into an empty session", async ({ page }) => {
  world.drafts = [
    draft({
      id: "draft-secret-id-999",
      subject: "Guardado",
      body: "corpo guardado",
      recipient: "ana@example.com",
    }),
  ];
  await openChat(page);
  const review = page.getByRole("region", { name: "Rascunhos" });
  await review.getByRole("textbox", { name: "Corpo do e-mail", exact: true }).fill("edição local");
  await page.getByRole("textbox", { name: "Mensagem" }).fill("não enviado");
  await page.reload();
  await expect(page.getByText("API online", { exact: true })).toBeVisible();
  await expect(review.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue(
    "corpo guardado",
  );
  await expect(page.getByRole("article", { name: "Você" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Mensagem" })).toHaveValue("");
  await expect(page.getByText("draft-secret-id-999")).toHaveCount(0);
});

test("the next message submits the open cards as they stand", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", subject: "Original", body: "corpo", recipient: "ana@example.com" })];
  await openChat(page);
  const card = page.getByRole("region", { name: "Rascunhos" }).getByRole("article");
  await card.getByRole("textbox", { name: "Assunto", exact: true }).fill("Editado");
  await card.getByRole("textbox", { name: "Corpo do e-mail", exact: true }).fill("corpo editado");
  await page.getByRole("textbox", { name: "Mensagem" }).fill("encurta");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "Assistente" })).toBeVisible();
  const payload = JSON.parse(callsTo(world, "/api/chat", "POST").at(-1)?.body ?? "{}") as {
    open_drafts: { id: string; subject: string; body: string; recipient: string }[];
  };
  expect(payload.open_drafts).toEqual([
    {
      id: "open-1",
      subject: "Editado",
      body: "corpo editado",
      recipient: "ana@example.com",
    },
  ]);
});

test("a turn locks every card, revises one, and appends a new draft", async ({ page }) => {
  world.drafts = [
    draft({ id: "old", subject: "Mais antigo", body: "corpo antigo", recipient: "ana@example.com" }),
    draft({ id: "new", subject: "Mais novo", body: "corpo novo", recipient: "bia@example.com" }),
  ];
  const gate = deferred();
  world.chat = async (route) => {
    await gate.promise;
    await fulfillJson(route, {
      content: "Atualizei o primeiro e abri outro.",
      drafts: [
        draft({
          id: "old",
          subject: "Mais antigo",
          body: "Olá,\n\nCurto.\n\nAté mais!",
          recipient: "ana@example.com",
        }),
        draft({
          id: "fresh",
          subject: "Novo",
          body: "Olá,\n\nOutro.\n\nAté mais!",
          recipient: "cia@example.com",
        }),
      ],
    });
  };
  await openChat(page);
  const review = page.getByRole("region", { name: "Rascunhos" });
  const older = review.getByRole("article", { name: "Rascunho: Mais antigo" });
  const newer = review.getByRole("article", { name: "Rascunho: Mais novo" });
  await older.getByRole("textbox", { name: "Corpo do e-mail", exact: true }).fill("corpo antigo EDIT-A");
  await older.getByRole("textbox", { name: "Destinatário", exact: true }).fill("kept@example.com");
  await newer.getByRole("textbox", { name: "Corpo do e-mail", exact: true }).fill("corpo novo EDIT-B");
  await page.getByRole("textbox", { name: "Mensagem" }).fill("encurta o primeiro e escreve outro");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();

  await expect(older.getByRole("textbox", { name: "Assunto", exact: true })).toBeDisabled();
  await expect(newer.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toBeDisabled();
  await expect(older.getByRole("button", { name: "Confirmar envio", exact: true })).toBeDisabled();
  await expect(newer.getByRole("button", { name: "Descartar", exact: true })).toBeDisabled();

  gate.resolve();
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("Atualizei o primeiro");
  await expect(page.getByRole("region", { name: "Conversa" }).getByText("Rascunho", { exact: true })).toHaveCount(0);

  const cards = review.getByRole("article");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0)).toHaveAccessibleName("Rascunho: Mais antigo");
  await expect(cards.nth(1)).toHaveAccessibleName("Rascunho: Mais novo");
  await expect(cards.nth(2)).toHaveAccessibleName("Rascunho: Novo");
  await expect(cards.nth(0).getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue(
    "Olá,\n\nCurto.\n\nAté mais!",
  );
  await expect(cards.nth(0).getByRole("textbox", { name: "Destinatário", exact: true })).toHaveValue(
    "kept@example.com",
  );
  await expect(cards.nth(1).getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue(
    "corpo novo EDIT-B",
  );
  await expect(cards.nth(0).getByRole("textbox", { name: "Assunto", exact: true })).toBeEnabled();
});

test("a failed turn unlocks the snapshotted cards and does not invent a reply", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", subject: "Vivo", body: "corpo", recipient: "ana@example.com" })];
  world.chat = async (route) => {
    await fulfillJson(route, { error: "Inbox unavailable." }, 502);
  };
  await openChat(page);
  const card = page.getByRole("article", { name: "Rascunho: Vivo" });
  await card.getByRole("textbox", { name: "Corpo do e-mail", exact: true }).fill("KEEP");
  const composer = page.getByRole("textbox", { name: "Mensagem" });
  await composer.fill("encurta");
  await composer.press("Enter");
  await expect(interfaceAlert(page)).toHaveText("Inbox unavailable.");
  await expect(page.getByRole("region", { name: "Conversa" }).getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Assistente" })).toHaveCount(0);
  await expect(composer).toHaveValue("encurta");
  await expect(page.getByRole("article", { name: "Você" })).toHaveCount(0);
  await expect(card.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue("KEEP");
  await expect(card.getByRole("textbox", { name: "Assunto", exact: true })).toBeEnabled();

  world.chat = defaultChat;
  await composer.press("Enter");
  await expect(page.getByRole("article", { name: "Você" })).toHaveCount(1);
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("Pronto.");
});

test("confirm and discard append a receipt at the end of the session", async ({ page }) => {
  world.chat = async (route) => {
    await fulfillJson(route, {
      content: "O rascunho está pronto.",
      drafts: [draft({ id: "open-1", subject: "Reunião", body: "só o texto", recipient: "ana@example.com" })],
    });
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("escreve");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const card = page.getByRole("article", { name: "Rascunho: Reunião" });
  await expect(card).toBeVisible();
  const act = await card
    .getByRole("button", { name: "Confirmar envio", exact: true })
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  await card.getByRole("textbox", { name: "Assunto", exact: true }).fill("");
  const priorBefore = callsTo(world, "/api/drafts/prior-recipients", "GET").length;
  await page.getByRole("button", { name: "Confirmar envio", exact: true }).click();

  const transcript = page.getByRole("region", { name: "Conversa" });
  const articles = transcript.getByRole("article");
  await expect(articles).toHaveCount(3);
  await expect(articles.nth(2)).toHaveAccessibleName(/^Enviado/);
  await expect(transcript.getByText("Rascunho", { exact: true })).toHaveCount(0);
  await expect(transcript.getByRole("button", { name: "Confirmar envio" })).toHaveCount(0);
  await expect(articles.nth(2)).toContainText("só o texto");
  await expect(articles.nth(2)).toContainText("ana@example.com");
  await expect(page.getByRole("region", { name: "Rascunhos" })).toHaveCount(0);
  await expect(interfaceAlert(page)).toHaveCount(0);
  await expect
    .poll(() => callsTo(world, "/api/drafts/prior-recipients", "GET").length)
    .toBeGreaterThan(priorBefore);

  const confirmCall = callsTo(world, "/api/drafts/open-1/confirm", "POST").at(-1);
  const confirmBody = JSON.parse(confirmCall?.body ?? "{}") as {
    subject: string;
    body: string;
    recipient: string;
  };
  expect(confirmBody).toEqual({ subject: "", body: "só o texto", recipient: "ana@example.com" });
  expect(confirmCall?.body ?? "").not.toContain("backendUrl");

  const chip = await transcript.getByText("Enviado", { exact: true }).evaluate((node) => {
    return getComputedStyle(node).backgroundColor;
  });
  expect(chip).not.toBe(act);
  expect(isGreenDominant(chip)).toBe(false);
});

test("a loaded draft with an invalid recipient alerts before confirm", async ({ page }) => {
  world.drafts = [draft({ id: "bad", subject: "Ruim", recipient: "nope" })];
  await openChat(page);
  await expect(interfaceAlert(page)).toHaveText("Informe um e-mail válido.");
  await expect(page.getByRole("button", { name: "Confirmar envio", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Descartar", exact: true })).toBeEnabled();
});

test("an invalid recipient disables only confirm and a rejected confirm leaves the card open", async ({ page }) => {
  world.drafts = [
    draft({ id: "bad", subject: "Ruim", recipient: "ana@example.com" }),
    draft({ id: "good", subject: "Bom", recipient: "bia@example.com" }),
  ];
  await openChat(page);
  const review = page.getByRole("region", { name: "Rascunhos" });
  const bad = review.getByRole("article", { name: "Rascunho: Ruim" });
  const good = review.getByRole("article", { name: "Rascunho: Bom" });
  await bad.getByRole("textbox", { name: "Destinatário", exact: true }).fill("nope");
  await expect(bad.getByRole("button", { name: "Confirmar envio", exact: true })).toBeDisabled();
  await expect(bad.getByRole("button", { name: "Descartar", exact: true })).toBeEnabled();
  await expect(good.getByRole("button", { name: "Confirmar envio", exact: true })).toBeEnabled();
  await expect(interfaceAlert(page)).toHaveText("Informe um e-mail válido.");
  await expect(page.getByRole("region", { name: "Conversa" }).getByRole("alert")).toHaveCount(0);

  world.confirm = async (route) => {
    await fulfillJson(route, { error: "smtp down" }, 502);
  };
  await good.getByRole("button", { name: "Confirmar envio", exact: true }).click();
  await expect(interfaceAlert(page)).toHaveText("Não foi possível confirmar o envio.");
  await expect(good).toBeVisible();
  await expect(good.getByRole("textbox", { name: "Assunto", exact: true })).toBeEnabled();
  await expect(page.getByRole("region", { name: "Conversa" }).getByText("Enviado")).toHaveCount(0);
});

test("discard appends a muted receipt and a rejected discard leaves the card open", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", subject: "Abandono", body: "texto vivo", recipient: "ana@example.com" })];
  world.discard = async (route) => {
    await fulfillJson(route, { error: "nope" }, 502);
  };
  await openChat(page);
  const card = page.getByRole("article", { name: "Rascunho: Abandono" });
  await card.getByRole("button", { name: "Descartar", exact: true }).click();
  await expect(interfaceAlert(page)).toHaveText("Não foi possível descartar.");
  await expect(card.getByRole("textbox", { name: "Assunto", exact: true })).toBeEnabled();

  world.discard = defaultDiscard;
  await card.getByRole("button", { name: "Descartar", exact: true }).click();
  const receipt = page.getByRole("region", { name: "Conversa" }).getByRole("article", { name: "Descartado: Abandono" });
  await expect(receipt).toBeVisible();
  await expect(receipt).toContainText("texto vivo");
  await expect(receipt).toContainText("ana@example.com");
  await expect(receipt.getByRole("button", { name: "Confirmar envio" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Rascunhos" })).toHaveCount(0);
  const opacity = await receipt.evaluate((node) => getComputedStyle(node).opacity);
  expect(Number(opacity)).toBeLessThan(1);
  const decoration = await receipt.getByText("texto vivo").evaluate((node) => {
    return getComputedStyle(node).textDecorationLine;
  });
  expect(decoration).not.toContain("line-through");
});

test("confirm on one card leaves the other usable", async ({ page }) => {
  world.drafts = [
    draft({ id: "first", subject: "Primeiro", recipient: "ana@example.com" }),
    draft({ id: "second", subject: "Segundo", recipient: "bia@example.com" }),
  ];
  const gate = deferred();
  world.confirm = async (route) => {
    await gate.promise;
    await defaultConfirm(route);
  };
  await openChat(page);
  const review = page.getByRole("region", { name: "Rascunhos" });
  const first = review.getByRole("article", { name: "Rascunho: Primeiro" });
  const second = review.getByRole("article", { name: "Rascunho: Segundo" });
  await first.getByRole("button", { name: "Confirmar envio", exact: true }).click();
  await expect(first.getByRole("button", { name: "Confirmando…", exact: true })).toBeVisible();
  await expect(second.getByRole("button", { name: "Confirmar envio", exact: true })).toBeEnabled();
  await expect(second.getByRole("textbox", { name: "Assunto", exact: true })).toBeEnabled();
  await second.getByRole("textbox", { name: "Assunto", exact: true }).fill("Ainda dá");
  gate.resolve();
  await expect(page.getByRole("article", { name: "Enviado: Primeiro" })).toBeVisible();
  await expect(
    review.getByRole("article", { name: "Rascunho: Ainda dá" }).getByRole("textbox", { name: "Assunto", exact: true }),
  ).toHaveValue("Ainda dá");
});

test("send and confirm share one blue on a white page, and failure stays distinct", async ({ page }) => {
  world.online = false;
  world.drafts = [draft({ id: "open-1", subject: "Cor", recipient: "ana@example.com" })];
  await openChat(page);
  const card = page.getByRole("article", { name: "Rascunho: Cor" });
  await card.getByRole("textbox", { name: "Destinatário", exact: true }).fill("nope");
  await expect(interfaceAlert(page)).toBeVisible();

  const talk = await page
    .getByRole("button", { name: "Enviar mensagem", exact: true })
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  const act = await card
    .getByRole("button", { name: "Confirmar envio", exact: true })
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  const border = await card.evaluate((node) => getComputedStyle(node).borderTopColor);
  const offline = await page.getByText("API offline", { exact: true }).evaluate((node) => {
    return getComputedStyle(node).color;
  });
  const alert = await interfaceAlert(page).evaluate((node) => getComputedStyle(node).color);
  const paper = await page.locator("body").evaluate((node) => getComputedStyle(node).backgroundColor);

  expect(isBrandBlue(talk)).toBe(true);
  expect(act).toBe(talk);
  expect(border).toBe(talk);
  expect(isWhite(paper)).toBe(true);
  expect(offline).toBe(alert);
  expect(alert).not.toBe(talk);
  const heading = await page
    .getByRole("heading", { name: "Assistente de e-mail" })
    .evaluate((node) => getComputedStyle(node).color);
  expect(channels(heading)[0]).toBeLessThan(80);
});

test("clears an empty session on the first click, including receipts", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", subject: "Enviado depois", recipient: "ana@example.com" })];
  await openChat(page);
  await page.getByRole("button", { name: "Confirmar envio", exact: true }).click();
  await expect(page.getByRole("article", { name: "Enviado: Enviado depois" })).toBeVisible();
  await page.getByRole("textbox", { name: "Mensagem" }).fill("oi");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "Você" })).toBeVisible();

  const discardCalls = callsTo(world, "/api/drafts/discard-open", "POST").length;
  await page.getByRole("button", { name: "Limpar conversa", exact: true }).click();
  await expect(page.getByText(/Descartar \d+ rascunho/)).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /desfazer|undo/i })).toHaveCount(0);
  expect(callsTo(world, "/api/drafts/discard-open", "POST")).toHaveLength(discardCalls);
});

test("asks before clearing open drafts, and Voltar leaves them in place", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", subject: "Fica" })];
  await openChat(page);
  await page.getByRole("button", { name: "Limpar conversa", exact: true }).click();
  await expect(page.getByText("Descartar 1 rascunho e limpar a conversa?", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(callsTo(world, "/api/drafts/discard-open", "POST")).toHaveLength(0);
  await page.getByRole("button", { name: "Voltar", exact: true }).click();
  await expect(page.getByRole("button", { name: "Limpar conversa", exact: true })).toBeVisible();
  await expect(page.getByRole("article", { name: "Rascunho: Fica" })).toBeVisible();
  expect(callsTo(world, "/api/drafts/discard-open", "POST")).toHaveLength(0);
});

test("Limpar discards every open draft and empties the session", async ({ page }) => {
  world.drafts = [
    draft({ id: "one", subject: "Um" }),
    draft({ id: "two", subject: "Dois" }),
  ];
  const gate = deferred();
  world.discardOpen = async (route) => {
    await gate.promise;
    await defaultDiscardOpen(route);
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("oi");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "Você" })).toBeVisible();
  await page.getByRole("button", { name: "Limpar conversa", exact: true }).click();
  await expect(page.getByText("Descartar 2 rascunhos e limpar a conversa?", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Limpar", exact: true }).click();
  await expect(page.getByRole("button", { name: "Limpando…", exact: true })).toBeVisible();
  gate.resolve();
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Rascunhos" })).toHaveCount(0);
  expect(callsTo(world, "/api/drafts/discard-open", "POST")).toHaveLength(1);
  await expect(page.getByRole("button", { name: /desfazer|undo/i })).toHaveCount(0);
});

test("a rejected clear leaves the session as it was", async ({ page }) => {
  world.drafts = [draft({ id: "open-1", subject: "Fica" })];
  world.discardOpen = async (route) => {
    await fulfillJson(route, { error: "nope" }, 502);
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("oi");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await page.getByRole("button", { name: "Limpar conversa", exact: true }).click();
  await page.getByRole("button", { name: "Limpar", exact: true }).click();
  await expect(interfaceAlert(page)).toHaveText("Não foi possível limpar a conversa.");
  await expect(page.getByRole("article", { name: "Você" })).toContainText("oi");
  await expect(page.getByRole("article", { name: "Rascunho: Fica" })).toBeVisible();
  await expect(page.getByText("Descartar 1 rascunho e limpar a conversa?", { exact: true })).toBeVisible();
});

async function setTabVisible(page: Page, visible: boolean) {
  await page.evaluate((isVisible) => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (isVisible ? "visible" : "hidden"),
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }, visible);
}

test("an empty session lists the ten recent inbound emails and moves them to the sidebar", async ({ page }) => {
  const longSubject = "Assunto muito longo que não cabe na barra lateral sem ser cortado de verdade";
  world.emails = [
    inbound({ id: "new", sender: "Novo Remetente", subject: longSubject, date: "25 set 2026", unread: true }),
    inbound({
      id: "old",
      sender: "Antigo Remetente",
      address: "antigo@example.com",
      subject: "Mais antigo",
      date: "20 set 2026",
      unread: false,
    }),
  ];
  await openChat(page);

  const list = page.getByRole("region", { name: "Conversa" }).getByRole("list", { name: "E-mails recebidos" });
  await expect(list.getByRole("link")).toHaveCount(2);
  await expect(list.getByRole("link").nth(0)).toContainText("Novo Remetente");
  await expect(list.getByRole("link").nth(0)).toContainText(longSubject);
  await expect(list.getByRole("link").nth(0)).toContainText("25 set 2026");
  await expect(list.getByRole("link").nth(0).getByLabel("Não lido")).toBeVisible();
  await expect(list.getByRole("link").nth(1).getByLabel("Não lido")).toHaveCount(0);
  const mark = await list.getByRole("link").nth(0).getByLabel("Não lido").evaluate((node) => {
    return getComputedStyle(node).backgroundColor;
  });
  expect(isBrandBlue(mark)).toBe(true);
  const linkColor = await list.getByRole("link").nth(1).evaluate((node) => getComputedStyle(node).color);
  expect(isBrandBlue(linkColor)).toBe(true);
  expect(callsTo(world, "/api/inbox", "GET").at(0)?.search).toContain("limit=10");
  expect(callsTo(world, "/api/inbox", "GET").at(0)?.search).toContain("days=7");
  expect(callsTo(world, "/api/inbox", "GET").at(0)?.search ?? "").not.toContain("folder");
  expect(callsEnding(world, "/read", "POST")).toHaveLength(0);
  await expect(page.getByRole("button", { name: /mais antigos|carregar mais/i })).toHaveCount(0);

  await page.getByRole("textbox", { name: "Mensagem" }).fill("oi");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const sidebarList = page.getByRole("complementary").getByRole("list", { name: "E-mails recebidos" });
  await expect(sidebarList).toBeVisible();
  await expect(page.getByRole("region", { name: "Conversa" }).getByRole("list", { name: "E-mails recebidos" })).toHaveCount(0);
  const clipped = sidebarList.getByText(longSubject);
  const clip = await clipped.evaluate((node) => {
    const style = getComputedStyle(node);
    return { overflow: style.textOverflow, whiteSpace: style.whiteSpace, clipped: node.scrollWidth > node.clientWidth + 1 };
  });
  expect(clip.overflow).toBe("ellipsis");
  expect(clip.whiteSpace).toBe("nowrap");
  expect(clip.clipped).toBe(true);

  await page.getByRole("button", { name: "Limpar conversa", exact: true }).click();
  await expect(page.getByRole("region", { name: "Conversa" }).getByRole("list", { name: "E-mails recebidos" })).toBeVisible();
  await expect(sidebarList).toHaveCount(0);
  await expect(list.getByRole("link")).toHaveCount(2);
});

test("a failed first listing alerts and a later failure keeps the rows", async ({ page }) => {
  world.inboxStatus = 502;
  world.drafts = [draft({ id: "open-1", subject: "Ainda aqui" })];
  await openChat(page);
  await expect(interfaceAlert(page)).toHaveText("Não foi possível carregar a caixa de entrada.");
  await expect(page.getByRole("list", { name: "E-mails recebidos" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Rascunho: Ainda aqui" })).toBeVisible();

  world.inboxStatus = 200;
  world.emails = [inbound({ id: "kept", subject: "Fica na lista", unread: true })];
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  const list = page.getByRole("list", { name: "E-mails recebidos" });
  await expect(list.getByRole("link")).toContainText("Fica na lista");

  world.inboxStatus = 502;
  const shown = callsTo(world, "/api/inbox", "GET").length;
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  await expect.poll(() => callsTo(world, "/api/inbox", "GET").length).toBeGreaterThan(shown);
  await expect(list.getByRole("link")).toContainText("Fica na lista");
  await expect(page.getByRole("article", { name: "Rascunho: Ainda aqui" })).toBeVisible();
  await page.getByRole("textbox", { name: "Mensagem" }).fill("ainda dá");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("Pronto.");
});

test("opening an inbound email shows plain text, marks it read, and Voltar restores the list", async ({ page }) => {
  world.emails = [
    inbound({
      id: "html",
      subject: "Com marca",
      body: "veja <strong>segredo</strong>",
      unread: true,
    }),
    inbound({ id: "empty", sender: "Sem corpo", subject: "Vazio", date: "24 set 2026", body: "", unread: true }),
  ];
  await openChat(page);
  await page.getByRole("link", { name: /Com marca/ }).click();
  const opened = page.getByRole("article", { name: "E-mail: Com marca" });
  await expect(opened).toContainText("Maria Silva");
  await expect(opened).toContainText("veja <strong>segredo</strong>");
  await expect(opened.locator("strong")).toHaveCount(0);
  await expect(opened.getByRole("button", { name: /anexo|attachment/i })).toHaveCount(0);
  await expect.poll(() => callsEnding(world, "/html/read", "POST").length).toBe(1);
  await expect(page.getByRole("list", { name: "E-mails recebidos" }).getByLabel("Não lido")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Mensagem" })).toBeEnabled();

  world.markRead = async (route) => {
    await fulfillJson(route, { error: "nope" }, 502);
  };
  await opened.getByRole("button", { name: "Voltar", exact: true }).click();
  await expect(page.getByRole("list", { name: "E-mails recebidos" })).toBeVisible();
  await page.getByRole("link", { name: /Vazio/ }).click();
  const empty = page.getByRole("article", { name: "E-mail: Vazio" });
  await expect(empty).toContainText("Sem corpo");
  await expect(empty).toContainText("Vazio");
  await expect(empty).toContainText("24 set 2026");
  await expect(interfaceAlert(page)).toHaveText("Não foi possível marcar o e-mail como lido.");
  await expect(empty).toBeVisible();

  await empty.getByRole("button", { name: "Voltar", exact: true }).click();
  await page.getByRole("textbox", { name: "Mensagem" }).fill("fecha");
  await page.getByRole("link", { name: /Com marca/ }).click();
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "E-mail: Com marca" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Você" })).toContainText("fecha");
});

test("Responder creates one reply without the pin, and a failure leaves no draft", async ({ page }) => {
  world.emails = [inbound({ id: "mail-1", subject: "Re: Reunião", unread: true })];
  world.drafts = [draft({ id: "open-1", subject: "Já aberto", recipient: "bia@example.com" })];
  await openChat(page);
  await page.getByRole("radio", { name: "Outro destinatário" }).check();
  await page.getByRole("textbox", { name: "E-mail do destinatário" }).fill("pin@example.com");
  await page.getByRole("link", { name: /Reunião/ }).click();
  const before = page.getByRole("region", { name: "Conversa" }).getByRole("article");
  await expect(before).toHaveCount(1);
  await page.getByRole("button", { name: "Responder", exact: true }).click();
  await expect(page.getByRole("article", { name: "Rascunho: Re: Reunião" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Rascunhos" }).getByRole("article")).toHaveCount(2);
  await expect(before).toHaveCount(1);
  await expect(page.getByRole("article", { name: "Você" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Assistente" })).toHaveCount(0);
  const replyCall = callsEnding(world, "/mail-1/reply", "POST").at(-1);
  expect(replyCall?.body ?? "").not.toContain("pin@example.com");
  expect(replyCall?.body ?? "").not.toContain("to_email");
  const card = page.getByRole("article", { name: "Rascunho: Re: Reunião" });
  await expect(card.getByRole("textbox", { name: "Destinatário", exact: true })).toHaveValue("maria@example.com");
  await expect(card.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toContainText("Olá, Maria Silva,");
  await expect(card.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).not.toContainText("Texto do e-mail.");

  world.reply = async (route) => {
    await fulfillJson(route, { error: "Invalid sender address." }, 400);
  };
  await page.getByRole("article", { name: "E-mail: Re: Reunião" }).getByRole("button", { name: "Voltar", exact: true }).click();
  await page.getByRole("link", { name: /Reunião/ }).click();
  const cards = await page.getByRole("region", { name: "Rascunhos" }).getByRole("article").count();
  await page.getByRole("button", { name: "Responder", exact: true }).click();
  await expect(interfaceAlert(page)).toHaveText("Não foi possível criar a resposta.");
  await expect(page.getByRole("region", { name: "Rascunhos" }).getByRole("article")).toHaveCount(cards);
});

test("Responder stays unavailable while a chat message is in flight", async ({ page }) => {
  world.emails = [inbound({ id: "mail-1", subject: "Pausa" })];
  const gate = deferred();
  world.chat = async (route) => {
    await gate.promise;
    await fulfillJson(route, { content: "Pronto.", drafts: [] });
  };
  await openChat(page);
  await page.getByRole("link", { name: /Pausa/ }).click();
  await page.getByRole("textbox", { name: "Mensagem" }).fill("em curso");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "E-mail: Pausa" })).toHaveCount(0);
  await page.getByRole("complementary").getByRole("link", { name: /Pausa/ }).click();
  await expect(page.getByRole("button", { name: "Responder", exact: true })).toBeDisabled();
  expect(callsEnding(world, "/reply", "POST")).toHaveLength(0);
  gate.resolve();
  await expect(page.getByRole("button", { name: "Responder", exact: true })).toBeEnabled();
  expect(callsEnding(world, "/reply", "POST")).toHaveLength(0);
  await page.getByRole("button", { name: "Voltar", exact: true }).click();
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("Pronto.");
});

test("the review card shows the opening returned for that turn", async ({ page }) => {
  world.chat = async (route) => {
    const body = route.request().postDataJSON() as { message: string };
    const opening = body.message.includes("Meu Amor") ? "Meu Amor," : "Olá, Maria,";
    await fulfillJson(route, {
      content: "O rascunho está pronto para ana@example.com.",
      drafts: [draft({ id: body.message.includes("Meu Amor") ? "love" : "named", body: `${opening}\n\nTexto.\n\nAté mais!` })],
    });
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("Escreva para minha esposa, Meu Amor");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue(
    "Meu Amor,\n\nTexto.\n\nAté mais!",
  );
  await page.getByRole("textbox", { name: "Mensagem" }).fill("Escreva para Maria");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const cards = page.getByRole("region", { name: "Rascunhos" }).getByRole("article");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(1).getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue(
    "Olá, Maria,\n\nTexto.\n\nAté mais!",
  );
  await expect(page.getByRole("list", { name: "Destinatários anteriores" })).toHaveCount(0);
});

test("a revision that does not change the card alerts, and an unidentified draft does not", async ({ page }) => {
  world.drafts = [draft({ id: "only", subject: "Original", body: "corpo", recipient: "ana@example.com" })];
  world.chat = async (route) => {
    await fulfillJson(route, {
      content: "O rascunho está pronto para ana@example.com.",
      drafts: [draft({ id: "only", subject: "Original", body: "corpo", recipient: "ana@example.com" })],
      revision: "failed",
    });
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("encurta o rascunho");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(interfaceAlert(page)).toHaveText("Não foi possível atualizar o rascunho.");
  await expect(page.getByRole("article", { name: "Assistente" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Você" })).toContainText("encurta o rascunho");
  await expect(page.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue("corpo");

  world.drafts = [
    draft({ id: "old", subject: "Mais antigo", body: "antigo", recipient: "ana@example.com" }),
    draft({ id: "new", subject: "Mais novo", body: "novo", recipient: "bia@example.com" }),
  ];
  world.chat = async (route) => {
    await fulfillJson(route, {
      content: "Qual rascunho? Mais antigo para ana@example.com, 1 set, e Mais novo para bia@example.com, 2 set.",
      drafts: [],
      revision: "unidentified",
    });
  };
  await page.reload();
  await expect(page.getByText("API online", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Mensagem" }).fill("muda o e-mail");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("Qual rascunho?");
  await expect(interfaceAlert(page)).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Corpo do e-mail", exact: true }).first()).toHaveValue("antigo");

  world.chat = async (route) => {
    await fulfillJson(route, {
      content: "O rascunho está pronto para ana@example.com.",
      drafts: [draft({ id: "old", subject: "Curto", body: "Olá,\n\nCurto.\n\nAté mais!", recipient: "ana@example.com" })],
    });
  };
  await page.getByRole("textbox", { name: "Mensagem" }).fill("encurta o mais antigo");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const older = page.getByRole("article", { name: "Rascunho: Curto" });
  await expect(older.getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toHaveValue(
    "Olá,\n\nCurto.\n\nAté mais!",
  );
  await expect(page.getByRole("article", { name: "Assistente" }).last()).toContainText("O rascunho está pronto");
});

test("a chat reply uses the inbound sender, and an ambiguous match creates none", async ({ page }) => {
  world.emails = [
    inbound({ id: "m1", sender: "Maria Silva", subject: "Jantar", date: "25 set 2026" }),
    inbound({ id: "m2", sender: "Maria Souza", address: "souza@example.com", subject: "Almoço", date: "24 set 2026" }),
  ];
  await openChat(page);
  await page.getByRole("radio", { name: "Outro destinatário" }).check();
  await page.getByRole("textbox", { name: "E-mail do destinatário" }).fill("pin@example.com");
  world.chat = async (route) => {
    await fulfillJson(route, {
      content: "Qual e-mail? Maria Silva, Jantar, 25 set 2026, ou Maria Souza, Almoço, 24 set 2026.",
      drafts: [],
    });
  };
  await page.getByRole("textbox", { name: "Mensagem" }).fill("Responda a Maria");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("Maria Silva, Jantar, 25 set 2026");
  await expect(page.getByRole("region", { name: "Rascunhos" })).toHaveCount(0);

  world.drafts = [draft({ id: "open-1", subject: "Original", body: "corpo", recipient: "bia@example.com" })];
  world.chat = async (route) => {
    await fulfillJson(route, {
      content: "O rascunho está pronto para maria@example.com.",
      drafts: [
        draft({ id: "open-1", subject: "Curto", body: "Olá,\n\nCurto.\n\nAté mais!", recipient: "bia@example.com" }),
        draft({
          id: "reply-m1",
          subject: "Re: Jantar",
          body: "Querida,\n\nCombinado.\n\nAté mais!",
          recipient: "maria@example.com",
          inboundId: "late",
        } as Draft & { inboundId: string }),
      ],
    });
  };
  await page.reload();
  await expect(page.getByText("API online", { exact: true })).toBeVisible();
  world.emails = [
    inbound({ id: "late", sender: "Tarde", address: "tarde@example.com", subject: "Aviso", date: "26 set 2026", unread: true }),
    ...world.emails,
  ];
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  await expect(page.getByRole("article", { name: "Chegou: Aviso" })).toBeVisible();
  expect(callsEnding(world, "/late/reply", "POST")).toHaveLength(0);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("Encurta o rascunho e responda o jantar, Querida");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  const cards = page.getByRole("region", { name: "Rascunhos" }).getByRole("article");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(1).getByRole("textbox", { name: "Destinatário", exact: true })).toHaveValue("maria@example.com");
  await expect(cards.nth(1).getByRole("textbox", { name: "Corpo do e-mail", exact: true })).toContainText("Querida,");
  await expect(page.getByRole("article", { name: "Assistente" })).toContainText("maria@example.com");
  await expect(page.getByRole("article", { name: "Chegou: Aviso" })).toHaveCount(0);
});

test("arrival notices follow the baseline and open one reply when the review card is free", async ({ page }) => {
  world.emails = [inbound({ id: "base", subject: "Já estava", unread: true })];
  await openChat(page);
  await expect(page.getByRole("region", { name: "Avisos de chegada" })).toHaveCount(0);
  expect(callsEnding(world, "/reply", "POST")).toHaveLength(0);

  world.emails = [
    inbound({ id: "fresh", sender: "Novo", address: "novo@example.com", subject: "Chegou agora", unread: true }),
    inbound({ id: "other", sender: "Outro", address: "outro@example.com", subject: "Também novo", unread: true }),
    inbound({ id: "base", subject: "Já estava", unread: true }),
  ];
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  const notices = page.getByRole("region", { name: "Avisos de chegada" });
  await expect(notices.getByRole("article")).toHaveCount(1);
  await expect(notices.getByRole("article").nth(0)).toContainText("Também novo");
  await expect(page.getByRole("article", { name: "Rascunho: Re: Chegou agora" })).toBeVisible();
  expect(callsEnding(world, "/fresh/reply", "POST")).toHaveLength(1);
  expect(callsEnding(world, "/fresh/read", "POST")).toHaveLength(0);
  await expect(page.getByRole("article", { name: "Você" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /dispensar todos/i })).toHaveCount(0);

  await notices.getByRole("button", { name: "Também novo", exact: true }).click();
  await expect(page.getByRole("article", { name: "E-mail: Também novo" })).toBeVisible();
  await expect(notices.getByRole("article")).toContainText("Também novo");
  await page.getByRole("article", { name: "E-mail: Também novo" }).getByRole("button", { name: "Voltar", exact: true }).click();
  await notices.getByRole("button", { name: "Dispensar", exact: true }).click();
  await expect(notices).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Rascunho: Re: Chegou agora" })).toBeVisible();

  const repliesWhileOpen = callsEnding(world, "/reply", "POST").length;
  world.emails = [
    inbound({ id: "waiting", sender: "Espera", address: "espera@example.com", subject: "Ainda não", unread: true }),
    ...world.emails,
  ];
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  await expect(page.getByRole("article", { name: "Chegou: Ainda não" })).toBeVisible();
  expect(callsEnding(world, "/reply", "POST")).toHaveLength(repliesWhileOpen);
  const reviewBox = await boxOf(page.getByRole("region", { name: "Rascunhos" }));
  const noticeBox = await boxOf(page.getByRole("article", { name: "Chegou: Ainda não" }));
  expect(reviewBox.x).toBeGreaterThan(noticeBox.x);

  world.emails = [
    inbound({ id: "third", sender: "Terceiro", address: "terceiro@example.com", subject: "Espera", unread: true }),
    ...world.emails,
  ];
  world.reply = async (route) => {
    await fulfillJson(route, { error: "nope" }, 502);
  };
  await page.getByRole("button", { name: "Confirmar envio", exact: true }).click();
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  await expect(page.getByRole("article", { name: "Chegou: Espera" })).toBeVisible();
  await expect(interfaceAlert(page)).toHaveText("Não foi possível criar a resposta.");
  expect(callsEnding(world, "/third/read", "POST")).toHaveLength(0);
});

test("a notice waits through a chat turn and becomes a reply when the card is free", async ({ page }) => {
  world.emails = [inbound({ id: "base", subject: "Base" })];
  const gate = deferred();
  world.chat = async (route) => {
    await gate.promise;
    await fulfillJson(route, { content: "Pronto.", drafts: [] });
  };
  await openChat(page);
  await page.getByRole("textbox", { name: "Mensagem" }).fill("pesquisando");
  await page.getByRole("button", { name: "Enviar mensagem", exact: true }).click();
  await expect(page.getByText("Preparando a resposta… Pode levar alguns minutos.")).toBeVisible();
  world.emails = [
    inbound({ id: "during", sender: "Durante", address: "durante@example.com", subject: "No meio", unread: true }),
    ...world.emails,
  ];
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  await expect(page.getByRole("article", { name: "Chegou: No meio" })).toBeVisible();
  expect(callsEnding(world, "/during/reply", "POST")).toHaveLength(0);
  await page.getByRole("button", { name: "Dispensar", exact: true }).click();
  await expect(page.getByRole("article", { name: "Chegou: No meio" })).toHaveCount(0);

  world.emails = [
    inbound({ id: "after", sender: "Depois", address: "depois@example.com", subject: "Ao terminar", unread: true }),
    ...world.emails,
  ];
  await setTabVisible(page, false);
  await setTabVisible(page, true);
  await expect(page.getByRole("article", { name: "Chegou: Ao terminar" })).toBeVisible();
  expect(callsEnding(world, "/reply", "POST")).toHaveLength(0);
  gate.resolve();
  await expect(page.getByRole("article", { name: "Rascunho: Re: Ao terminar" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Chegou: Ao terminar" })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "Você" })).toContainText("pesquisando");
  expect(callsEnding(world, "/after/read", "POST")).toHaveLength(0);
});

test("a visible tab looks again after 60 seconds and a hidden tab does not", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-09-25T15:00:00Z") });
  world.emails = [inbound({ id: "base", subject: "Base" })];
  await openChat(page);
  await expect(page.getByRole("link", { name: /Base/ })).toBeVisible();
  const first = callsTo(world, "/api/inbox", "GET").length;
  world.emails = [
    inbound({ id: "later", sender: "Relógio", address: "relogio@example.com", subject: "Sessenta", unread: true }),
    ...world.emails,
  ];
  await page.clock.fastForward(60_000);
  await expect(page.getByRole("article", { name: "Rascunho: Re: Sessenta" })).toBeVisible();
  expect(callsTo(world, "/api/inbox", "GET").length).toBeGreaterThan(first);

  await setTabVisible(page, false);
  const hidden = callsTo(world, "/api/inbox", "GET").length;
  world.emails = [
    inbound({ id: "hidden", subject: "Oculto" }),
    ...world.emails,
  ];
  await page.clock.fastForward(60_000);
  expect(callsTo(world, "/api/inbox", "GET").length).toBe(hidden);
  await expect(page.getByRole("link", { name: /Oculto/ })).toHaveCount(0);
});
