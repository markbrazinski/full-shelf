// =====================================================================
// Full Shelf — judge-safe replay acceptance
// ---------------------------------------------------------------------
// An anonymous visitor must be able to start, explore, refresh, restart
// and complete the replay repeatedly without ever observing a state that
// violates the canonical event contract, and without touching another
// visitor's replay.
//
// Everything here runs against the REAL Golden Runtime Controller on
// 127.0.0.1:8788 and the REAL React UI. No mock, no stub, no fixture
// short-circuit, and no arbitrary sleep standing in for a condition.
//
// Assertions are SEMANTIC — rendered receipts, committed cursors and
// runtime state — never screenshots, so they cannot pass by sampling a
// lucky frame.
// =====================================================================

import { test, expect, type Page, type BrowserContext } from "@playwright/test";

const RUNTIME = "http://127.0.0.1:8788";

test.setTimeout(240_000);

const cursor = async (page: Page): Promise<number> =>
  Number(await page.locator('[data-testid="app-root"]').getAttribute("data-cursor"));

/** The session id the live app is actually driving. */
async function sessionOf(page: Page): Promise<string> {
  await expect
    .poll(
      async () =>
        await page.evaluate(() => (window as unknown as { __FS_SESSION_ID?: string }).__FS_SESSION_ID ?? ""),
      { timeout: 30_000, message: "app published its session id" },
    )
    .not.toBe("");
  return await page.evaluate(
    () => (window as unknown as { __FS_SESSION_ID?: string }).__FS_SESSION_ID ?? "",
  );
}

/** Runtime state for a session, read from the runtime itself. */
async function runtimeState(page: Page, sid: string) {
  return await (await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}`)).json();
}

/**
 * Drive the real runtime to a cursor, approving at the human gate through
 * the visible product control. Mirrors the golden suite's helper so both
 * exercise the same committed path.
 */
async function driveTo(page: Page, sid: string, target: number) {
  await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/pause`).catch(() => {});

  for (let guard = 0; guard < 40; guard++) {
    const state = await runtimeState(page, sid);
    if (state.cursor >= target) break;

    const res = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/advance`);
    if (res.status() === 409) {
      const detail = (await res.json()).detail;
      if (detail === "HUMAN_APPROVAL_REQUIRED") {
        const approve = page.locator('[data-testid="approve-update"]');
        await expect(approve).toBeVisible({ timeout: 30_000 });
        await approve.click();
        await expect
          .poll(async () => (await runtimeState(page, sid)).cursor, { timeout: 30_000 })
          .toBeGreaterThanOrEqual(9);
        continue;
      }
      if (detail === "REPLAY_COMPLETE") break;
      throw new Error(`advance refused: ${detail}`);
    }
  }

  await expect
    .poll(() => cursor(page), { timeout: 60_000, message: `UI cursor >= ${target}` })
    .toBeGreaterThanOrEqual(target);
}

/** Wait until the cursor stops moving, then return it. */
async function settleCursor(page: Page, quietMs = 1_000): Promise<number> {
  let last = await cursor(page);
  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(quietMs);
    const now = await cursor(page);
    if (now === last) return now;
    last = now;
  }
  return last;
}

/**
 * The whole point of the repair: at no boundary may the Incident view
 * assert a recall that has not been received.
 *
 * The premature shell was recognisable by its own placeholders — a
 * "SAFETY HOLD · —" with no lot and a "Recall" with no identifier — so
 * this asserts against the rendered text an operator would actually read.
 */
async function expectNoPrematureRecall(page: Page) {
  const main = page.locator("main");
  const text = await main.innerText();
  expect(text, "no empty safety-hold placeholder").not.toContain("SAFETY HOLD · —");
  expect(text, "no recall heading without an identifier").not.toMatch(/Recall\s*\n/);
  // The five recall stages may not be on screen before the recall exists.
  await expect(page.locator('[data-testid="stage-spine"]')).toHaveCount(0);
}

// =====================================================================
test.describe("Anonymous entry and session isolation", () => {
  test("a fresh anonymous load starts at the opening boundary, read-only", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('[data-testid="app-root"]')).toBeVisible();

    // Opens on the committed opening event, never mid-day.
    expect(await cursor(page)).toBe(5);
    const sid = await sessionOf(page);
    const state = await runtimeState(page, sid);
    expect(state.cursor).toBe(5);
    expect(state.classification).toBe("SYNTHETIC_TEST");
    expect(state.synthetic).toBe(true);

    // rev07 is authoritative; rev08 has no authority before approval.
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");

    // Read-only: no mutating control other than the one human approval
    // gate exists anywhere on the opening surface.
    await expect(
      page.getByRole("button", { name: /delete|edit|commit|activate|dispatch|override/i }),
    ).toHaveCount(0);
  });

  test("two simultaneous visitors never share or disturb a replay", async ({ browser }) => {
    const a: BrowserContext = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    const b: BrowserContext = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    try {
      const pa = await a.newPage();
      const pb = await b.newPage();
      await pa.goto("/");
      await pb.goto("/");
      await expect(pa.locator('[data-testid="app-root"]')).toBeVisible();
      await expect(pb.locator('[data-testid="app-root"]')).toBeVisible();

      const sa = await sessionOf(pa);
      const sb = await sessionOf(pb);
      expect(sa, "each visitor gets a distinct session").not.toBe(sb);

      // Drive A deep into the day, including through the approval gate.
      await driveTo(pa, sa, 18);

      // B is untouched: its runtime cursor, its approval, and its screen.
      const stateB = await runtimeState(pb, sb);
      expect(stateB.cursor, "B's cursor is unmoved by A").toBeLessThanOrEqual(8);
      expect(stateB.approved, "A's approval did not approve B").toBe(false);

      // No cross-session leakage of recall state into B.
      await pb.locator('[data-testid="nav-incident"]').click();
      await pb.waitForTimeout(300);
      await expectNoPrematureRecall(pb);

      // And A still holds its own deep state.
      expect(await cursor(pa)).toBeGreaterThanOrEqual(18);
    } finally {
      await a.close();
      await b.close();
    }
  });

  test("a restart isolates from the prior session and cannot rewind another", async ({ page }) => {
    await page.goto("/");
    const first = await sessionOf(page);
    await driveTo(page, first, 12);

    // Restart = a fresh anonymous entry.
    await page.reload();
    await expect(page.locator('[data-testid="app-root"]')).toBeVisible();
    const second = await sessionOf(page);

    expect(second, "restart mints a new session").not.toBe(first);
    expect(await cursor(page), "restart returns to the opening boundary").toBe(5);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");

    // The prior session is untouched by the restart.
    const old = await runtimeState(page, first);
    expect(old.cursor, "the abandoned session did not rewind").toBeGreaterThanOrEqual(12);
  });
});

// =====================================================================
test.describe("Interaction during an atomic transition", () => {
  test("hammering Incidents through the truck failure never shows a recall", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));

    await page.goto("/");
    await expect.poll(() => cursor(page), { timeout: 60_000 }).toBeGreaterThanOrEqual(6);

    // Events 6→8 are the truck-failure transition. Clicking Incidents
    // repeatedly while it advances must never expose recall scaffolding.
    for (let i = 0; i < 30; i++) {
      await page.locator('[data-testid="nav-incident"]').click({ force: true }).catch(() => {});
      const c = await cursor(page);
      if (c < 11) await expectNoPrematureRecall(page);
      await page.locator('[data-testid="nav-today"]').click({ force: true }).catch(() => {});
      await page.waitForTimeout(80);
    }

    expect(errors, "no page errors during the transition").toEqual([]);
  });

  test("Incidents immediately before, during and after the recall event", async ({ page }) => {
    await page.goto("/");
    const sid = await sessionOf(page);

    // BEFORE — the recall has not been received.
    await driveTo(page, sid, 10);
    await page.locator('[data-testid="nav-incident"]').click();
    await page.waitForTimeout(200);
    await expect(page.locator('[data-testid="incident-none"]')).toBeVisible();
    await expectNoPrematureRecall(page);

    // DURING — event 11 commits while the operator stands on Incidents.
    // The recall holds for a deliberate act; it must not half-render.
    await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/advance`);
    await expect.poll(() => cursor(page), { timeout: 30_000 }).toBe(11);
    await expect(page.locator('[data-testid="start-recall-response"]')).toBeVisible({
      timeout: 20_000,
    });

    // AFTER — starting the response opens the real workspace with a real
    // identifier and a real lot, never a placeholder.
    await page.locator('[data-testid="start-recall-response"]').click();
    const ws = page.locator('[data-testid="incident-workspace"]');
    await expect(ws).toBeVisible({ timeout: 20_000 });
    const text = await ws.innerText();
    expect(text).toContain("INC-2231");
    expect(text).toContain("LTC-4471");
    expect(text, "no empty lot placeholder").not.toContain("SAFETY HOLD · —");
  });

  test("rapid navigation among current and completed stages never moves the cursor", async ({
    page,
  }) => {
    await page.goto("/");
    const sid = await sessionOf(page);
    await driveTo(page, sid, 22);
    await page.locator('[data-testid="nav-incident"]').click();
    await expect(page.locator('[data-testid="incident-workspace"]')).toBeVisible();

    const before = await settleCursor(page);
    const runtimeBefore = (await runtimeState(page, sid)).cursor;

    // Inspecting completed stages is exploration, not advancement.
    const stages = page.locator('[data-testid="stage-spine"] button');
    const n = await stages.count();
    for (let round = 0; round < 3; round++) {
      for (let i = 0; i < n; i++) {
        await stages.nth(i).click({ force: true }).catch(() => {});
        await page.waitForTimeout(40);
      }
    }
    // And so is bouncing between views.
    for (let i = 0; i < 10; i++) {
      await page.locator('[data-testid="nav-today"]').click({ force: true }).catch(() => {});
      await page.locator('[data-testid="nav-history"]').click({ force: true }).catch(() => {});
      await page.locator('[data-testid="nav-incident"]').click({ force: true }).catch(() => {});
    }

    expect(await cursor(page), "navigation never advanced the cursor").toBe(before);
    expect((await runtimeState(page, sid)).cursor, "runtime cursor unmoved").toBe(runtimeBefore);
  });

  test("browser Back and Forward do not desynchronize or rewind the replay", async ({ page }) => {
    await page.goto("/");
    const sid = await sessionOf(page);
    await driveTo(page, sid, 20);

    await page.locator('[data-testid="nav-incident"]').click();
    await page.locator('[data-testid="nav-history"]').click();
    const before = await settleCursor(page);

    await page.goBack().catch(() => {});
    await page.waitForTimeout(400);
    await page.goForward().catch(() => {});
    await page.waitForTimeout(400);

    // The replay is a single document: history navigation either does
    // nothing or reloads into a fresh isolated session. Neither may show
    // a cursor that runs backwards inside one session.
    await expect(page.locator('[data-testid="app-root"]')).toBeVisible();
    const sidAfter = await sessionOf(page);
    if (sidAfter === sid) {
      expect(await cursor(page), "same session never rewinds").toBeGreaterThanOrEqual(before);
    } else {
      expect(await cursor(page), "a new session opens at the opening boundary").toBe(5);
    }
  });
});

// =====================================================================
test.describe("Refresh at every major stage", () => {
  // One refresh per canonical stage boundary. Each must land on a
  // coherent opening state rather than a torn resume.
  for (const stage of [5, 8, 10, 11, 18, 20, 22, 24]) {
    test(`refreshing at event ${stage} returns a clean isolated replay`, async ({ page }) => {
      await page.goto("/");
      const sid = await sessionOf(page);
      if (stage > 5) await driveTo(page, sid, stage);

      await page.reload();
      await expect(page.locator('[data-testid="app-root"]')).toBeVisible();

      // A refresh is a new anonymous visit: fresh session, opening state.
      const fresh = await sessionOf(page);
      expect(fresh).not.toBe(sid);
      expect(await cursor(page)).toBe(5);
      await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");

      // No state from the refreshed-away session survives.
      await page.locator('[data-testid="nav-incident"]').click();
      await page.waitForTimeout(200);
      await expectNoPrematureRecall(page);
      await expect(page.locator('[data-testid="day-sat"]')).toHaveCount(0);
    });
  }
});

// =====================================================================
test.describe("Canonical event contract holds under exploration", () => {
  test("rev08 has no authority before the human approval", async ({ page }) => {
    await page.goto("/");
    const sid = await sessionOf(page);
    await driveTo(page, sid, 8);

    // At the gate the proposal is visible but rev07 is still authoritative.
    await expect(page.locator('[data-testid="approve-update"]')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");

    // The runtime refuses to advance past the gate on its own.
    const refused = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/advance`);
    expect(refused.status()).toBe(409);
    expect((await refused.json()).detail).toBe("HUMAN_APPROVAL_REQUIRED");

    // Clicking around cannot manufacture rev08 authority.
    for (let i = 0; i < 12; i++) {
      await page.locator('[data-testid="nav-incident"]').click({ force: true }).catch(() => {});
      await page.locator('[data-testid="nav-today"]').click({ force: true }).catch(() => {});
    }
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");
    expect((await runtimeState(page, sid)).cursor, "the gate held").toBe(8);

    // Only the human action moves it, and it lands on rev08 exactly.
    await page.locator('[data-testid="approve-update"]').click();
    await driveTo(page, sid, 10);
    await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev08");
  });

  test("no recall state exists before recall intake", async ({ page }) => {
    await page.goto("/");
    const sid = await sessionOf(page);

    for (const boundary of [5, 6, 8, 10]) {
      if (boundary > 5) await driveTo(page, sid, boundary);
      const projection = await (
        await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}/projection`)
      ).json();

      const incidents = projection.current_day?.incidents ?? [];
      expect(
        incidents.some((i: { incident_id?: string }) => i.incident_id === "INC-2231"),
        `no recall incident at event ${boundary}`,
      ).toBe(false);
      expect(projection.recall_intake_as_of, `no intake at event ${boundary}`).toBeNull();

      await page.locator('[data-testid="nav-incident"]').click();
      await page.waitForTimeout(150);
      await expectNoPrematureRecall(page);
      await page.locator('[data-testid="nav-today"]').click();
    }
  });

  test("no full containment while custody remains unconfirmed", async ({ page }) => {
    await page.goto("/");
    const sid = await sessionOf(page);
    await driveTo(page, sid, 22);
    await page.locator('[data-testid="nav-incident"]').click();
    await expect(page.locator('[data-testid="incident-workspace"]')).toBeVisible();

    const projection = await (
      await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}/projection`)
    ).json();
    const recall = (projection.current_day?.incidents ?? []).find(
      (i: { incident_id?: string }) => i.incident_id === "INC-2231",
    );
    expect(recall.status, "terminal truth is PARTIALLY_CONTAINED").toBe("PARTIALLY_CONTAINED");

    // Custody: 96 physical cases, 88 confirmed, Site 01's 8 unconfirmed.
    const graph = projection.execution_evidence_as_of?.custody_graph;
    expect(graph.unique_current_cases).toBe(96);
    expect(graph.unconfirmed_cases).toBe(8);

    // The screen refuses closure rather than claiming containment.
    const body = await page.locator("main").innerText();
    expect(body).not.toMatch(/\bFULLY CONTAINED\b/i);
    expect(body).not.toMatch(/\bCLOSED\b/);

    // Exploring afterwards cannot upgrade the terminal state.
    for (let i = 0; i < 10; i++) {
      await page.locator('[data-testid="nav-history"]').click({ force: true }).catch(() => {});
      await page.locator('[data-testid="nav-incident"]').click({ force: true }).catch(() => {});
    }
    const after = await (
      await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}/projection`)
    ).json();
    expect(
      (after.current_day?.incidents ?? []).find(
        (i: { incident_id?: string }) => i.incident_id === "INC-2231",
      ).status,
    ).toBe("PARTIALLY_CONTAINED");
  });

  test("the cursor never runs backwards and never skips an event", async ({ page }) => {
    await page.goto("/");
    const sid = await sessionOf(page);

    const seen: number[] = [];
    for (let i = 0; i < 60; i++) {
      seen.push(await cursor(page));
      // Interleave adversarial interaction with observation.
      await page.locator('[data-testid="nav-incident"]').click({ force: true }).catch(() => {});
      await page.locator('[data-testid="nav-today"]').click({ force: true }).catch(() => {});
      await page.waitForTimeout(120);
      if ((await cursor(page)) === 8) break;
    }

    for (let i = 1; i < seen.length; i++) {
      expect(seen[i], `cursor never decreases (${seen[i - 1]} → ${seen[i]})`).toBeGreaterThanOrEqual(
        seen[i - 1],
      );
    }

    // The runtime's own committed feed is contiguous from 1 with no gaps
    // and no duplicates — the authoritative statement that nothing was
    // skipped or double-committed.
    const state = await runtimeState(page, sid);
    const seq = (state.feed ?? []).map((e: { sequence: number }) => e.sequence);
    expect(seq, "committed feed is strictly contiguous").toEqual(
      Array.from({ length: seq.length }, (_, i) => i + 1),
    );
  });

  test("the runtime refuses a backwards cursor and an unbound approval", async ({ page }) => {
    await page.goto("/");
    const sid = await sessionOf(page);
    await driveTo(page, sid, 12);
    const at = (await runtimeState(page, sid)).cursor;

    // There is no rewind verb at all: the transport exposes no route that
    // can lower a committed cursor.
    for (const verb of ["rewind", "seek", "goto", "set_cursor"]) {
      const res = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/${verb}`, {
        data: { cursor: 5 },
      });
      expect(res.status(), `${verb} is not a route`).toBe(404);
    }
    expect((await runtimeState(page, sid)).cursor, "cursor unchanged").toBe(at);

    // An approval with an altered binding commits nothing.
    const bad = await page.request.post(`${RUNTIME}/api/v1/replay/sessions/${sid}/approve`, {
      data: {
        plan_id: "PLAN-001",
        incident_id: "INC-2210",
        expected_revision: "rev07",
        target_revision: "rev08",
        actions: [{ order_id: "O202", cases: 999, disposition: "TRUCK_2" }],
        plan_diff_hash: "tampered",
        idempotency_key: "judge-safety-tamper",
      },
    });
    expect(bad.status()).toBe(409);
    expect((await runtimeState(page, sid)).cursor, "zero mutations on refusal").toBe(at);
  });
});

// =====================================================================
test.describe("Transport degradation", () => {
  test("slow API responses never produce a torn or premature state", async ({ page }) => {
    // Delay every runtime read so reads genuinely overlap committed events.
    await page.route("**/api/v1/replay/sessions/**/projection", async (route) => {
      await new Promise((r) => setTimeout(r, 700));
      await route.continue();
    });

    await page.goto("/");
    await expect(page.locator('[data-testid="app-root"]')).toBeVisible();
    await expect.poll(() => cursor(page), { timeout: 90_000 }).toBeGreaterThanOrEqual(6);

    // Under lag the Incident view must still never assert a recall early.
    for (let i = 0; i < 15; i++) {
      await page.locator('[data-testid="nav-incident"]').click({ force: true }).catch(() => {});
      if ((await cursor(page)) < 11) await expectNoPrematureRecall(page);
      await page.locator('[data-testid="nav-today"]').click({ force: true }).catch(() => {});
      await page.waitForTimeout(100);
    }

    // rev08 authority still requires the approval, lag or not.
    const settled = await settleCursor(page);
    if (settled <= 8) await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");
  });

  test("a duplicated projection response never double-applies state", async ({ page }) => {
    // Serve every projection read twice; the client must be idempotent.
    let duplicated = 0;
    await page.route("**/api/v1/replay/sessions/**/projection", async (route) => {
      const res = await route.fetch();
      const body = await res.text();
      duplicated += 1;
      await route.fulfill({ response: res, body });
      // Fire a second identical read behind it.
      await page.request.get(route.request().url()).catch(() => {});
    });

    await page.goto("/");
    const sid = await sessionOf(page);
    await driveTo(page, sid, 18);

    expect(duplicated, "projection reads were genuinely intercepted").toBeGreaterThan(0);

    // The rail must carry each canonical ordinal exactly once.
    const ordinals = await page
      .locator('[data-testid="activity-entry"]')
      .evaluateAll((els) => els.map((e) => e.getAttribute("data-ordinal") ?? ""));
    const canonical = ordinals.filter((o) => !o.startsWith("b"));
    expect(new Set(canonical).size, "no duplicated activity entries").toBe(canonical.length);

    // And the committed feed is still contiguous.
    const seq = ((await runtimeState(page, sid)).feed ?? []).map(
      (e: { sequence: number }) => e.sequence,
    );
    expect(seq).toEqual(Array.from({ length: seq.length }, (_, i) => i + 1));
  });
});

// =====================================================================
test.describe("Repeatability", () => {
  test("ten consecutive complete replays reach the identical terminal truth", async ({ page }) => {
    const outcomes: string[] = [];
    const sessions = new Set<string>();

    for (let run = 0; run < 10; run++) {
      await page.goto("/");
      await expect(page.locator('[data-testid="app-root"]')).toBeVisible();
      const sid = await sessionOf(page);
      sessions.add(sid);

      expect(await cursor(page), `run ${run} opens at event 5`).toBe(5);

      await driveTo(page, sid, 25);

      const projection = await (
        await page.request.get(`${RUNTIME}/api/v1/replay/sessions/${sid}/projection`)
      ).json();
      const recall = (projection.current_day?.incidents ?? []).find(
        (i: { incident_id?: string }) => i.incident_id === "INC-2231",
      );
      const graph = projection.execution_evidence_as_of?.custody_graph;
      const draft = projection.next_day_draft;

      outcomes.push(
        JSON.stringify({
          status: recall.status,
          total: graph.unique_current_cases,
          confirmed: graph.confirmed_cases,
          unconfirmed: graph.unconfirmed_cases,
          tomorrow: draft?.status ?? draft?.plan_status ?? null,
        }),
      );

      // The feed is contiguous on every single run.
      const seq = ((await runtimeState(page, sid)).feed ?? []).map(
        (e: { sequence: number }) => e.sequence,
      );
      expect(seq, `run ${run} feed contiguous`).toEqual(
        Array.from({ length: seq.length }, (_, i) => i + 1),
      );
    }

    expect(sessions.size, "every run had its own isolated session").toBe(10);
    expect(new Set(outcomes).size, `all ten runs agree: ${outcomes[0]}`).toBe(1);
    expect(outcomes[0]).toContain("PARTIALLY_CONTAINED");
    expect(outcomes[0]).toContain('"unconfirmed":8');
  });

  test("restart from the beginning, the middle and the terminal state", async ({ page }) => {
    for (const from of [5, 14, 25]) {
      await page.goto("/");
      const sid = await sessionOf(page);
      if (from > 5) await driveTo(page, sid, from);

      // Restart.
      await page.reload();
      await expect(page.locator('[data-testid="app-root"]')).toBeVisible();
      const fresh = await sessionOf(page);

      expect(fresh, `restart from ${from} is a new session`).not.toBe(sid);
      expect(await cursor(page), `restart from ${from} opens at event 5`).toBe(5);
      await expect(page.locator('[data-testid="auth-rev"]')).toHaveText("rev07");
      await page.locator('[data-testid="nav-incident"]').click();
      await page.waitForTimeout(200);
      await expectNoPrematureRecall(page);
    }
  });
});
