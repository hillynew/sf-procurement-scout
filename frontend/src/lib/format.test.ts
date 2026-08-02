import { describe, expect, it } from "vitest";
import { dueText, dueTone, fmtMoney, fmtMoneyCents, fmtMoneyFull } from "./format";

describe("fmtMoney", () => {
  it("formats magnitudes", () => {
    expect(fmtMoney(920)).toBe("$920");
    expect(fmtMoney(92_400)).toBe("$92k");
    expect(fmtMoney(1_500_000)).toBe("$1.5M");
    expect(fmtMoney(2_000_000)).toBe("$2M");
  });
  it("passes null through", () => {
    expect(fmtMoney(null)).toBeNull();
    expect(fmtMoney(undefined)).toBeNull();
  });
  it("converts cents", () => {
    expect(fmtMoneyCents(9_240_000)).toBe("$92k");
    expect(fmtMoneyFull(9_240_000)).toBe("$92,400");
  });
});

describe("due badges", () => {
  it("buckets urgency", () => {
    expect(dueTone(1, "open")).toBe("danger");
    expect(dueTone(5, "open")).toBe("warn");
    expect(dueTone(20, "open")).toBe("ok");
    expect(dueTone(-1, "open")).toBe("closed");
    expect(dueTone(10, "closed")).toBe("closed");
    expect(dueTone(null, "open")).toBe("none");
  });
  it("labels days", () => {
    expect(dueText(0, "open")).toBe("due today");
    expect(dueText(1, "open")).toBe("due tomorrow");
    expect(dueText(9, "open")).toBe("9d left");
    expect(dueText(null, "open")).toBe("no due date");
    expect(dueText(5, "cancelled")).toBe("cancelled");
  });
});
