import { describe, expect, it } from "vitest";
import type { Opportunity } from "../api/types";
import {
  applyFilters,
  countActive,
  DEFAULT_FILTERS,
  EMPTY_FILTERS,
  parseFilters,
  writeFilters,
} from "./filters";

function opp(over: Partial<Opportunity>): Opportunity {
  return {
    opportunity_id: Math.random().toString(36).slice(2),
    source_id: "s", source_name: "S", external_id: null,
    title: "t", url: "u", county: "broward", agency: "A", department: null,
    solicitation_type: "ITB", offer_type: "construction", categories: [],
    posted_date: null, due_date: null, status: "open",
    description: null, brief: null, contact: null, budget: null,
    budget_amount: null, scope: null, requirements: [], documents: [],
    submittal_info: null, pre_bid_meeting: null, questions_due: null,
    contact_email: null, contact_phone: null, bid_opening: null,
    project_location: null, duration_days: null, liquidated_damages: null,
    licenses: null, prior_cycles: 0, last_cycle_closed: null,
    days_until_due: null, detail_score: 0,
    tracked: false, stage: null, decision: null, archived: false,
    tracked_on: null, checks: {}, notes: "", result: null, has_summary: false,
    ...over,
  };
}

describe("parse/write round trip", () => {
  it("defaults to Open when no params are set", () => {
    expect(parseFilters(new URLSearchParams())).toEqual(DEFAULT_FILTERS);
  });

  it("round-trips a full filter set", () => {
    const filters = {
      ...EMPTY_FILTERS,
      statuses: ["open", "upcoming"],
      regions: ["federal", "broward"],
      types: ["construction"],
      minValue: 50_000,
      maxValue: 500_000,
      dueWithin: 14,
      trackedOnly: true,
      noBond: true,
    };
    const params = writeFilters(new URLSearchParams(), filters);
    expect(parseFilters(params)).toEqual(filters);
  });

  it("legacy single-value URLs still parse", () => {
    const params = new URLSearchParams("f=open&c=broward&t=construction");
    const filters = parseFilters(params);
    expect(filters.statuses).toEqual(["open"]);
    expect(filters.regions).toEqual(["broward"]);
    expect(filters.types).toEqual(["construction"]);
  });

  it("explicit empty status list means 'all statuses'", () => {
    const params = writeFilters(new URLSearchParams(), { ...EMPTY_FILTERS, regions: ["federal"] });
    const filters = parseFilters(params);
    expect(filters.statuses).toEqual([]);
    expect(filters.regions).toEqual(["federal"]);
  });

  it("writing defaults clears all params", () => {
    const params = writeFilters(new URLSearchParams("f=closed&c=broward"), DEFAULT_FILTERS);
    expect([...params.keys()]).toEqual([]);
  });
});

describe("applyFilters", () => {
  const open = opp({ title: "open-bro", status: "open", county: "broward",
                     budget_amount: 100_000, days_until_due: 5 });
  const fed = opp({ title: "open-fed", status: "open", county: "federal",
                    offer_type: "goods", days_until_due: 20, has_summary: true });
  const closed = opp({ title: "closed", status: "cancelled", county: "broward" });
  const bonded = opp({ title: "bonded", status: "open",
                       requirements: ["Bid bond 5%"], prior_cycles: 2, tracked: true });
  const catalogRow = opp({ title: "cat", status: "catalog" });
  const pool = [open, fed, closed, bonded, catalogRow];

  it("default shows open only, never catalog", () => {
    expect(applyFilters(pool, DEFAULT_FILTERS).map((o) => o.title))
      .toEqual(["open-bro", "open-fed", "bonded"]);
  });

  it("empty filters show everything except catalog", () => {
    expect(applyFilters(pool, EMPTY_FILTERS)).toHaveLength(4);
  });

  it("closed bucket includes cancelled", () => {
    expect(applyFilters(pool, { ...EMPTY_FILTERS, statuses: ["closed"] })
      .map((o) => o.title)).toEqual(["closed"]);
  });

  it("regions OR together, sections AND", () => {
    const got = applyFilters(pool, {
      ...EMPTY_FILTERS, statuses: ["open"], regions: ["federal", "palm-beach"],
    });
    expect(got.map((o) => o.title)).toEqual(["open-fed"]);
  });

  it("value bounds exclude bids without a value", () => {
    const got = applyFilters(pool, { ...EMPTY_FILTERS, minValue: 50_000 });
    expect(got.map((o) => o.title)).toEqual(["open-bro"]);
  });

  it("due window excludes undated and past-due", () => {
    const got = applyFilters(pool, { ...EMPTY_FILTERS, dueWithin: 7 });
    expect(got.map((o) => o.title)).toEqual(["open-bro"]);
  });

  it("flags: tracked, rebids, brief, no-bond", () => {
    expect(applyFilters(pool, { ...EMPTY_FILTERS, trackedOnly: true })[0].title).toBe("bonded");
    expect(applyFilters(pool, { ...EMPTY_FILTERS, rebidsOnly: true })[0].title).toBe("bonded");
    expect(applyFilters(pool, { ...EMPTY_FILTERS, hasBrief: true })[0].title).toBe("open-fed");
    const noBond = applyFilters(pool, { ...EMPTY_FILTERS, noBond: true }).map((o) => o.title);
    expect(noBond).not.toContain("bonded");
  });
});

describe("countActive", () => {
  it("counts sections, not selections", () => {
    expect(countActive(EMPTY_FILTERS)).toBe(0);
    expect(countActive(DEFAULT_FILTERS)).toBe(1);
    expect(countActive({
      ...EMPTY_FILTERS, regions: ["broward", "federal"], minValue: 1,
      trackedOnly: true,
    })).toBe(3);
  });
});
