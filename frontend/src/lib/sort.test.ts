import { describe, expect, it } from "vitest";
import type { Opportunity } from "../api/types";
import { sortOpportunities } from "./sort";

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

describe("sortOpportunities", () => {
  const a = opp({ title: "Alpha", days_until_due: 10, budget_amount: 500_000 });
  const b = opp({ title: "Bravo", days_until_due: 2, budget_amount: null });
  const c = opp({ title: "Charlie", days_until_due: null, budget_amount: 100_000 });

  it("sorts by due date ascending with nulls last", () => {
    expect(sortOpportunities([a, b, c], "due", "asc").map((o) => o.title))
      .toEqual(["Bravo", "Alpha", "Charlie"]);
  });

  it("keeps nulls last when descending too", () => {
    expect(sortOpportunities([a, b, c], "due", "desc").map((o) => o.title))
      .toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("sorts by value with missing values last", () => {
    expect(sortOpportunities([a, b, c], "value", "desc").map((o) => o.title))
      .toEqual(["Alpha", "Charlie", "Bravo"]);
  });

  it("sorts strings case-insensitively and flips with direction", () => {
    const x = opp({ title: "zeta", agency: "beta" });
    const y = opp({ title: "Eta", agency: "Alpha" });
    expect(sortOpportunities([x, y], "agency", "asc")[0].agency).toBe("Alpha");
    expect(sortOpportunities([x, y], "agency", "desc")[0].agency).toBe("beta");
  });

  it("does not mutate the input", () => {
    const input = [a, b, c];
    sortOpportunities(input, "due", "asc");
    expect(input.map((o) => o.title)).toEqual(["Alpha", "Bravo", "Charlie"]);
  });
});
