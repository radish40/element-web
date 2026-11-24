/*
Copyright 2026 radish40
SPDX-License-Identifier: AGPL-3.0-only
*/

import { chromium, type BrowserContext, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

interface TestAccount {
    username: string;
    password: string;
}

interface GroupAccounts {
    room_id: string;
    group_name: string;
    users: TestAccount[];
}

interface Session {
    context: BrowserContext;
    page: Page;
    account: TestAccount;
}

const credentialsPath = process.argv[2];
if (!credentialsPath) throw new Error("Pass the path to the private test-accounts.json file");
const privateDirectory = dirname(resolve(credentialsPath));
const accounts: GroupAccounts = JSON.parse(await readFile(credentialsPath, "utf8"));
const sessions: Session[] = [];
const errors: string[] = [];

async function openGroup(session: Session): Promise<void> {
    const { page, account } = session;
    const roomUrl = "https://chat.547626.xyz/#/room/" + encodeURIComponent(accounts.room_id);
    await page.goto(roomUrl, { waitUntil: "domcontentloaded" });
    let submittedLogin = false;
    let requestedReset = false;
    let startedReset = false;
    let submittedPassword = false;
    for (let attempt = 0; attempt < 120; attempt++) {
        const body = await page.locator("body").innerText();
        if (body.includes("M_LIMIT_EXCEEDED")) throw new Error("Login rate limit reached for " + account.username);
        const next = page.getByRole("button", { name: "Continue", exact: true });
        const username = page.locator('input[name="username"]');
        const password = page.locator('input[type="password"]');
        const done = page.getByRole("button", { name: "Done", exact: true });
        const later = page.getByRole("button", { name: "Not now", exact: true });
        const cannotConfirm = page.getByText("Can't confirm?", { exact: true });
        if (body.includes("open in another window") && await next.isVisible()) {
            await next.click();
        } else if (!submittedLogin && await username.isVisible()) {
            await username.fill(account.username);
            await password.fill(account.password);
            await page.getByRole("button", { name: "Sign in", exact: true }).click();
            submittedLogin = true;
        } else if (!submittedPassword && body.includes("Confirm your identity by entering") && await password.isVisible()) {
            await password.fill(account.password);
            await next.click();
            submittedPassword = true;
        } else if (!startedReset && body.includes("You'll lose any encrypted chat history") && await next.isVisible()) {
            // These dedicated accounts contain only deployment test data.
            await next.click();
            startedReset = true;
        } else if (!requestedReset && await cannotConfirm.isVisible()) {
            await cannotConfirm.click();
            requestedReset = true;
        } else if (await done.isVisible() && !await password.isVisible()) {
            // The password confirmation dialog can arrive immediately after this screen appears.
            await done.click({ timeout: 1000 }).catch(() => undefined);
        } else if (await later.isVisible()) {
            await later.click();
        } else if (await page.getByRole("textbox", { name: /Send.*message/ }).isVisible()) {
            if (!body.includes(accounts.group_name)) throw new Error("Expected group is missing");
            return;
        } else if (page.url().endsWith("/#/home")) {
            await page.goto(roomUrl, { waitUntil: "domcontentloaded" });
        }
        await page.waitForTimeout(1000);
    }
    throw new Error("Could not open group for " + account.username);
}

try {
    for (const account of accounts.users) {
        if (!/^test_(alice|bob|carol)$/.test(account.username)) throw new Error("Expected a dedicated test account");
        const context = await chromium.launchPersistentContext(
            resolve(privateDirectory, "chat-browser", account.username),
            {
                executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH,
                headless: true,
                locale: "en-US",
                viewport: { width: 1440, height: 1000 },
            },
        );
        const existingPages = context.pages();
        const page = existingPages[0] ?? await context.newPage();
        for (const extra of existingPages.slice(1)) await extra.close();
        page.on("pageerror", (error) => errors.push(account.username + ": " + error.message));
        const session = { context, page, account };
        sessions.push(session);
        try {
            await openGroup(session);
        } catch (error) {
            console.error("Browser state", account.username, page.url(), await page.locator("body").innerText());
            await page.screenshot({ path: resolve(privateDirectory, "chat-group-failure.png"), fullPage: true });
            throw error;
        }
        console.log("PASS signed in and opened group", account.username);
    }
    const stamp = Date.now();
    for (const sender of sessions) {
        const message = "浏览器群聊验收 " + sender.account.username + " " + stamp;
        const editor = sender.page.getByRole("textbox", { name: /Send.*message/ });
        await editor.fill(message);
        await editor.press("Enter");
        for (const receiver of sessions) {
            await receiver.page.getByText(message, { exact: true }).waitFor({ state: "visible", timeout: 45000 });
        }
        console.log("PASS UI message sent and received by all three accounts", sender.account.username);
    }
    for (const session of sessions) {
        await session.page.screenshot({
            path: resolve(privateDirectory, "chat-group-" + session.account.username + ".png"),
            fullPage: true,
        });
    }
    if (errors.length) throw new Error(errors.join("\n"));
    console.log("PASS three simultaneous browser sessions, group messaging, and JavaScript error checks");
} finally {
    for (const session of sessions) await session.context.close();
}
